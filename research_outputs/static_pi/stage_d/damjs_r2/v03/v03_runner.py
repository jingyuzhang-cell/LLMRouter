"""DAMJS_V03_PILOT runner (pre-registration draft DAMJS_V0_3_PILOT_PREREG_DRAFT.md).

  plan A: R2 / ND-only / EV-only / V0.3  x  S3, S4  x  reps 1-2  = 16 executions, 240 s
  plan B: R2 / V0.3                      x  S3, S4  x  reps 1-3  = 12 executions, 240 s

Reuses damjs_r2_runner (read-only import) for the isolated launch, L3/L4 watchdog, degraded
scoring, ledger reconciliation and stop rules; only the child, batch id, manifest, plans, caps and
the extra gates below are new. Arms run block-adjacent in a pre-randomized order.

Real mode is code-locked until ALL of:
  * DAMJS_V0_3_PILOT_PREREG.md exists (the frozen, operator-approved prereg), declares
    PILOT_PLAN=<plan>, and its SHA is registered in DAMJS_V03_PILOT_MANIFEST.json;
  * STAGE_D_REAL_CALLS_AUTHORIZED=1 and DAMJS_V03_GO=<plan>:<phase>;
  * the smoke phase is complete before main.
Effective caps = min(plan/phase caps, operator authorization remaining after the R2 ledger), enforced
at reservation time by the children's shared GlobalBudget ledger.
"""
import argparse
import contextlib
import hashlib
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import d2_executor as D2
import damjs_r2_runner as R

BATCH = "DAMJS_V03_PILOT"
CHILD = HERE / "v03_child.py"
MANIFEST = STAGE_D / "DAMJS_V03_PILOT_MANIFEST.json"
PREREG_FROZEN = STAGE_D / "DAMJS_V0_3_PILOT_PREREG.md"
R2_RUNS = STAGE_D / "damjs_r2" / "runs_real"
DEADLINE = 240.0
ORDER_SEED = 20261107
ND_ARMS = {"ND-only", "V0.3"}
# Operator authorization remaining at the 2026-11-06 ruling; the R2 batch ledger draws from it too.
AUTH = dict(calls=377, tokens=1_348_528, yuan=2.3788)
SMOKE_CAPS = dict(calls=40, tokens=130_000, yuan=0.25)
PLANS = {
    "A": dict(arms=["R2", "ND-only", "EV-only", "V0.3"], reps=[1, 2], smoke_blocks=[("S3", 1)],
              caps=dict(calls=140, tokens=450_000, yuan=0.95)),
    "B": dict(arms=["R2", "V0.3"], reps=[1, 2, 3], smoke_blocks=[("S3", 1), ("S4", 1)],
              caps=dict(calls=105, tokens=370_000, yuan=0.70)),
}
REPLAY_SRC = {s: STAGE_D / "damjs_r2" / "runs_real" / "exec_records" / f"DAMJS__{s}__r1__D240.json"
              for s in ("S3", "S4")}


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_order(plan, seed=ORDER_SEED):
    P = PLANS[plan]
    rng = random.Random(f"{seed}:{plan}")
    blocks = [(s, r) for s in ("S3", "S4") for r in P["reps"]]
    rest = [b for b in blocks if b not in P["smoke_blocks"]]
    rng.shuffle(rest)
    out = []
    for phase, bl in (("smoke", list(P["smoke_blocks"])), ("main", rest)):
        for s, r in bl:
            arms = P["arms"][:]
            rng.shuffle(arms)
            for a in arms:
                out.append(dict(phase=phase, block=f"{int(DEADLINE)}s|{s}|r{r}", arm=a, scenario=s, rep=r,
                                deadline=DEADLINE, tag=f"{plan}_{int(DEADLINE)}s_{s}_r{r}_{a}"))
    return out


def caps_for(plan, phase, runs_dir, r2_runs=None):
    """Plan/phase caps on this batch's ledger, further limited by the authorization ceiling."""
    caps = dict(PLANS[plan]["caps"])
    if phase == "smoke":
        caps = {k: min(v, SMOKE_CAPS[k]) for k, v in caps.items()}
    r2 = R.read_ledger(r2_runs or R2_RUNS)
    room = {k: AUTH[k] - r2[k] for k in AUTH}
    return {k: (min(caps[k], room[k]) if k != "yuan" else round(min(caps[k], room[k]), 6)) for k in caps}


def prereg_gate(plan, manifest=None, prereg=None):
    manifest, prereg = manifest or MANIFEST, prereg or PREREG_FROZEN
    if not Path(prereg).exists():
        return "frozen prereg absent (operator approval pending)"
    if f"PILOT_PLAN={plan}" not in Path(prereg).read_text("utf-8"):
        return f"frozen prereg does not declare PILOT_PLAN={plan}"
    mf = json.loads(Path(manifest).read_text("utf-8"))
    entry = next((c for c in mf["components"] if c["role"] == "prereg_frozen"), None)
    if not entry or entry["sha256"] != sha_file(prereg):
        return "frozen prereg not registered in the batch manifest"
    return None


def c1_violation(records):
    """A re-dispatched node whose previous committed output was valid must never commit an invalid one."""
    last_valid, redispatched = {}, {}
    for r in records:
        if r.get("ev") == "node_invalidate":
            for n in r.get("nodes", []):
                redispatched[n] = last_valid.get(n, False)
        elif r.get("ev") == "node_end" and r.get("ok"):
            valid = isinstance(D2.extract_json(r.get("output") or ""), dict)
            if redispatched.pop(r["node"], False) and not valid:
                return r["node"]
            last_valid[r["node"]] = valid
    return None


def v03_stop(runs_dir, p):
    out = Path(runs_dir) / "progress" / f"{p['tag']}.jsonl.out"
    txt = out.read_text("utf-8", errors="replace") if out.exists() else ""
    if "Traceback" in txt and "damjs_v03" in txt:
        return "V03_PATH_EXCEPTION: traceback through damjs_v03 in the child"
    if p["arm"] in ND_ARMS:
        node = c1_violation(R.read_progress(Path(runs_dir) / "progress" / f"{p['tag']}.jsonl"))
        if node:
            return f"C1_VIOLATION: {node} committed an invalid output over a valid one in an ND arm"
    return None


@contextlib.contextmanager
def _pilot_child():
    saved = R.CHILD, R.BATCH
    R.CHILD, R.BATCH = CHILD, BATCH
    try:
        yield
    finally:
        R.CHILD, R.BATCH = saved


def run_one(**kw):
    with _pilot_child():
        return R.run_one(**kw)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", choices=sorted(PLANS), required=True)
    ap.add_argument("--mode", choices=["replay", "real"], default="replay")
    ap.add_argument("--phase", choices=["smoke", "main", "all"], default="smoke")
    ap.add_argument("--runs-dir", default=None)
    ap.add_argument("--clock-scale", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    runs_dir = Path(a.runs_dir or (HERE / f"runs_{a.mode}_{a.plan}"))
    if a.mode == "real":
        if a.phase == "all":
            raise SystemExit("REFUSED: real mode runs one phase per explicit GO")
        if (os.environ.get("STAGE_D_REAL_CALLS_AUTHORIZED") != "1"
                or os.environ.get("DAMJS_V03_GO") != f"{a.plan}:{a.phase}"):
            raise SystemExit(f"REFUSED: real {a.plan}:{a.phase} needs STAGE_D_REAL_CALLS_AUTHORIZED=1 "
                             f"and DAMJS_V03_GO={a.plan}:{a.phase}")
        gate = prereg_gate(a.plan)
        if gate:
            raise SystemExit(f"REFUSED: {gate}")
    pre = R.verify_manifest(MANIFEST)
    if not pre["ok"]:
        raise SystemExit(f"STOP INTEGRITY_FAIL before batch: {pre['mismatches']}")
    order = build_order(a.plan)
    plan = [p for p in order if a.phase == "all" or p["phase"] == a.phase]
    if a.mode == "real" and a.phase == "main":
        missing = [p["tag"] for p in order if p["phase"] == "smoke"
                   and not (runs_dir / "results" / f"{p['tag']}.json").exists()]
        if missing:
            raise SystemExit(f"REFUSED: smoke phase incomplete: {missing}")
    creds = R.load_credentials() if a.mode == "real" else None
    done, stop = 0, None
    for p in plan:
        if a.limit is not None and done >= a.limit:
            break
        if (runs_dir / "results" / f"{p['tag']}.json").exists():
            continue
        if a.mode == "real" and (runs_dir / "progress" / f"{p['tag']}.jsonl").exists():
            stop = f"ORPHAN_ATTEMPT: {p['tag']} has a progress log but no result; not retried automatically"
            break
        caps = caps_for(a.plan, p["phase"], runs_dir)
        hit = R.budget_exhausted(R.read_ledger(runs_dir), caps)
        if hit:
            stop = f"BUDGET_CAP_REACHED:{hit} (before launching {p['tag']})"
            break
        src = REPLAY_SRC[p["scenario"]] if a.mode == "replay" else None
        rec = run_one(tag=p["tag"], arm=p["arm"], scenario=p["scenario"], rep=p["rep"], deadline=p["deadline"],
                      mode=a.mode, runs_dir=runs_dir, caps=caps, manifest=MANIFEST, replay_src=src,
                      clock_scale=a.clock_scale, creds=creds, phase=p["phase"], block=p["block"])
        done += 1
        print(f"[{done:2d}] {p['tag']}: status={rec['status']} tp={rec['tp']} watchdog={rec['watchdog']} "
              f"ledger={rec['ledger_after']}", flush=True)
        stop = R.stop_reason(rec, caps) or v03_stop(runs_dir, p)
        if stop:
            break
    post = R.verify_manifest(MANIFEST)
    complete = all((runs_dir / "results" / f"{p['tag']}.json").exists() for p in plan)
    summary = dict(batch=BATCH, plan=a.plan, mode=a.mode, phase=a.phase, executed=done, stop=stop,
                   status="INCOMPLETE" if stop else ("PHASE_DONE" if complete else "PARTIAL_LIMIT"),
                   ledger=R.read_ledger(runs_dir), caps={ph: caps_for(a.plan, ph, runs_dir) for ph in ("smoke", "main")},
                   authorization=AUTH, r2_ledger=R.read_ledger(R2_RUNS), manifest_pre=pre, manifest_post=post,
                   integrity="OK" if (pre["ok"] and post["ok"]) else "INTEGRITY_FAIL")
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"BATCH_SUMMARY_{a.phase}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: summary[k] for k in ("plan", "mode", "phase", "executed", "stop", "status", "ledger",
                                               "integrity")}, ensure_ascii=False))
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
