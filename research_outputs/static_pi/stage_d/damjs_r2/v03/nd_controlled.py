"""DAMJS_ND_CONTROLLED runner (preregistration DAMJS_ND_CONTROLLED_PREREG.md, frozen).

Per repetition: one REAL generation run (E1-E4 + J1 first call, stopped after J1 -> upstream
fixture), then the R2 and ND-only arms back-to-back in a seeded-random order; both arms replay the
fixture upstream and receive the identical injected capped repair response; J2/SINK/FMT are real.

Real mode requires: STAGE_D_REAL_CALLS_AUTHORIZED=1, DAMJS_NDC_GO=run, and the frozen prereg
registered in DAMJS_ND_CONTROLLED_MANIFEST.json. Ledger separates real vs injected (tokens/calls of
injected responses are charged to the caps conservatively; their cash is not).
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import damjs_r2_runner as R
import v03_runner as VR

BATCH = "DAMJS_ND_CONTROLLED"
CHILD = HERE / "v03_child.py"
MANIFEST = STAGE_D / "DAMJS_ND_CONTROLLED_MANIFEST.json"
PREREG = HERE / "DAMJS_ND_CONTROLLED_PREREG.md"
REPS = [1, 2, 3]
SEED = 20261107
DEADLINE = 240.0
CAPS = dict(calls=50, tokens=160_000, yuan=0.35)
INJECT = dict(node="J1", at="repair", text="", **{"in": 1690}, out=8192, wall=119.83,
              source="smoke DAMJS S3 J1#2 (2026-11-06, recorded)")
R2_RUNS = STAGE_D / "damjs_r2" / "runs_real"
AUTH = VR.AUTH
ARMS = {"R2": dict(nd=False, ev=False), "ND-only": dict(nd=True, ev=False)}


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prereg_gate(manifest=None, prereg=None):
    manifest, prereg = Path(manifest or MANIFEST), Path(prereg or PREREG)
    if not prereg.exists():
        return "frozen prereg absent"
    mf = json.loads(Path(manifest).read_text("utf-8"))
    entry = next((c for c in mf["components"] if c["role"] == "prereg_frozen"), None)
    if not entry or entry["sha256"] != sha_file(prereg):
        return "frozen prereg not registered in DAMJS_ND_CONTROLLED_MANIFEST.json"
    return None


def caps_now(runs_dir, plan_caps=None):
    caps = dict(plan_caps or CAPS)
    r2 = R.read_ledger(R2_RUNS)
    room = {k: AUTH[k] - r2[k] for k in AUTH}
    return {k: round(min(caps[k], room[k]), 6) if k == "yuan" else min(caps[k], room[k]) for k in caps}


def run_one(env_extra=None, **kw):
    """R2 run_one with the controlled-experiment switches passed through the child environment."""
    saved = R.CHILD, R.BATCH
    keys = ("APILOT_UPSTREAM_FIXTURE", "APILOT_INJECT", "APILOT_GEN_STOP_AFTER")
    old_env = {k: os.environ.get(k) for k in keys}
    R.CHILD, R.BATCH = CHILD, BATCH
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(env_extra or {})
    try:
        return R.run_one(**kw)
    finally:
        R.CHILD, R.BATCH = saved
        for k, v in old_env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def fixture_charges(fixture_path):
    """Calls/tokens/accounting Y of the fixture responses: already paid in the generation run."""
    calls = tokens = 0
    yuan = 0.0
    for line in Path(fixture_path).read_text("utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("ev") == "fixture_call":
                calls += 1
                tokens += int(r["in"]) + int(r["out"])
                yuan += int(r["in"]) * 0.8e-6 + int(r["out"]) * 2.8e-6
    return dict(calls=calls, tokens=tokens, yuan=round(yuan, 6))


def deduct(runs_dir, charges):
    """Remove the fixture replays' charges from the shared ledger (they are not API calls)."""
    p = R.ledger_path(runs_dir)
    led = R.read_ledger(runs_dir)
    led = dict(calls=led["calls"] - charges["calls"], tokens=led["tokens"] - charges["tokens"],
               yuan=round(led["yuan"] - charges["yuan"], 6))
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(led, ensure_ascii=False), "utf-8")
    os.replace(tmp, p)
    return led


def account(runs_dir, tag, kind, before, after, charges, injected):
    """Separate ledger: real vs injected vs fixture-replayed (operator ruling 2026-11-07)."""
    inj_calls = len(injected)
    inj_tokens = inj_calls * (INJECT["in"] + INJECT["out"])
    inj_yuan = round(inj_calls * (INJECT["in"] * 0.8e-6 + INJECT["out"] * 2.8e-6), 6)
    d = {k: (round(after[k] - before[k], 6) if k == "yuan" else after[k] - before[k]) for k in after}
    row = dict(tag=tag, kind=kind, charged_after_deduction=d,
               injected=dict(calls=inj_calls, history_tokens=inj_tokens, simulated_accounting_yuan=inj_yuan,
                             simulated_wall_s=INJECT["wall"] * inj_calls),
               fixture_replays_deducted=charges,
               real=dict(calls=d["calls"] - inj_calls, tokens=d["tokens"] - inj_tokens,
                         accounting_yuan=round(d["yuan"] - inj_yuan, 6)))
    with open(Path(runs_dir) / "NDC_LEDGER.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["replay", "real"], default="replay")
    ap.add_argument("--runs-dir", default=None)
    ap.add_argument("--clock-scale", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--deadline", type=float, default=DEADLINE)
    ap.add_argument("--reps", default=",".join(str(r) for r in REPS))
    ap.add_argument("--caps", default=None)
    ap.add_argument("--prereg", default=str(PREREG))
    ap.add_argument("--manifest", default=str(MANIFEST))
    a = ap.parse_args(argv)
    reps = [int(x) for x in a.reps.split(",") if x.strip()]
    plan_caps = dict(json.loads(a.caps)) if a.caps else dict(CAPS)
    prereg, manifest = Path(a.prereg), Path(a.manifest)
    runs = Path(a.runs_dir or (HERE / f"runs_{a.mode}_ndc"))
    if a.mode == "real":
        if os.environ.get("STAGE_D_REAL_CALLS_AUTHORIZED") != "1" or os.environ.get("DAMJS_NDC_GO") != "run":
            raise SystemExit("REFUSED: real mode needs STAGE_D_REAL_CALLS_AUTHORIZED=1 and DAMJS_NDC_GO=run")
        gate = prereg_gate(manifest, prereg)
        if gate:
            raise SystemExit(f"REFUSED: {gate}")
    pre = R.verify_manifest(manifest)
    if not pre["ok"]:
        raise SystemExit(f"STOP INTEGRITY_FAIL before batch: {pre['mismatches']}")
    creds = R.load_credentials() if a.mode == "real" else None
    replay_src = STAGE_D / "damjs_r2" / "runs_real" / "exec_records" / "DAMJS__S3__r1__D240.json"
    rng = random.Random(SEED)
    done, stop = 0, None
    run_tag = E_TAG if (E_TAG := __import__("time").strftime("%H%M%S")) else "run"
    for rep in reps:
        order = ["R2", "ND-only"]
        rng.shuffle(order)
        caps = caps_now(runs, plan_caps)
        hit = R.budget_exhausted(R.read_ledger(runs), caps)
        if hit:
            stop = f"BUDGET_CAP_REACHED:{hit} (before rep {rep})"
            break
        if (runs / "results" / f"NDC_r{rep}_GEN.json").exists() and \
                all((runs / "results" / f"NDC_r{rep}_{a}.json").exists() for a in ("R2", "ND-only")):
            print(f"[skip] rep {rep}: results exist (resume-skip; no re-run, no re-charge)", flush=True)
            continue
        if (runs / "progress" / f"NDC_r{rep}_GEN.jsonl").exists() and \
                not (runs / "results" / f"NDC_r{rep}_GEN.json").exists():
            stop = f"ORPHAN_REP: rep {rep} has a generation progress log but no result; not retried automatically"
            break
        gen_tag = f"NDC_r{rep}_GEN"
        before = R.read_ledger(runs)
        gen = run_one(tag=gen_tag, arm="R2", scenario="S3", rep=rep, deadline=a.deadline, mode=a.mode,
                      runs_dir=runs, caps=caps, manifest=manifest, replay_src=replay_src,
                      clock_scale=a.clock_scale, creds=creds, phase=f"ndc-r{rep}", block=f"gen|r{rep}",
                      env_extra=dict(APILOT_GEN_STOP_AFTER="J1", APILOT_RUN_TAG=run_tag))
        account(runs, gen_tag, "generation", before, R.read_ledger(runs), dict(calls=0, tokens=0, yuan=0.0), [])
        done += 1
        print(f"[{done:2d}] {gen_tag}: watchdog={gen['watchdog']} ledger={gen['ledger_after']}", flush=True)
        fixture_path = runs / "progress" / f"{gen_tag}.jsonl"
        fx = [json.loads(l) for l in fixture_path.read_text().splitlines() if l.strip()]
        if not any(x.get("ev") == "fixture_complete" for x in fx):
            stop = f"INJECTION_POINT_MISS: generation run did not stop after J1 (rep {rep})"
            break
        for arm in order:
            if a.limit is not None and done >= a.limit:
                break
            if (runs / "results" / f"NDC_r{rep}_{arm}.json").exists():
                continue
            caps = caps_now(runs, plan_caps)
            hit = R.budget_exhausted(R.read_ledger(runs), caps)
            if hit:
                stop = f"BUDGET_CAP_REACHED:{hit} (before {arm} r{rep})"
                break
            tag = f"NDC_r{rep}_{arm}"
            env_extra = dict(APILOT_UPSTREAM_FIXTURE=str(fixture_path), APILOT_INJECT=json.dumps(INJECT), APILOT_RUN_TAG=run_tag)
            before = R.read_ledger(runs)
            rec = run_one(tag=tag, arm=arm, scenario="S3", rep=rep, deadline=a.deadline, mode=a.mode,
                          runs_dir=runs, caps=caps, manifest=manifest, replay_src=replay_src,
                          clock_scale=a.clock_scale, creds=creds, phase=f"ndc-r{rep}", block=f"{arm}|r{rep}",
                          env_extra=env_extra)
            done += 1
            res = json.loads((runs / "results" / f"{tag}.json").read_text("utf-8")) if \
                (runs / "results" / f"{tag}.json").exists() else {}
            src = res.get("controlled_log")
            if src is None and rec.get("aborted"):
                late_p = runs / "quarantine" / f"{tag}.late.json"
                if late_p.exists():
                    src = (json.loads(late_p.read_text("utf-8")).get("controlled_log"))
            served = [c for c in (src or []) if c["source"] == "fixture"]
            ch = fixture_charges(fixture_path)
            if len(served) != ch["calls"]:
                stop = (f"FIXTURE_MISMATCH: {tag} served {len(served)} fixture calls, fixture has {ch['calls']} "
                        f"(check source: {'late-child' if src is not None and res.get('controlled_log') is None else 'child-result'})")
                break
            rec["ledger_after"] = deduct(runs, ch)
            row = account(runs, tag, arm, before, rec["ledger_after"], ch, res.get("injected_calls") or [])
            assert row["real"]["calls"] >= 0 and row["charged_after_deduction"]["calls"] >= 0, \
                f"LEDGER_ASSERT: {tag} real={row['real']['calls']} charged={row['charged_after_deduction']['calls']}"
            if len(res.get("injected_calls") or []) != 1:
                stop = f"INJECTION_POINT_MISS: {tag} injected {len(res.get('injected_calls') or [])} calls (expected 1)"
                break
            print(f"[{done:2d}] {tag}: status={rec['status']} tp={rec['tp']} injected={len(res.get('injected_calls') or [])} "
                  f"ledger={rec['ledger_after']}", flush=True)
            stop = R.stop_reason(rec, caps) or VR.v03_stop(runs, dict(tag=tag, arm="ND-only" if arm == "ND-only" else "R2"))
            if stop:
                break
        if stop:
            break
    post = R.verify_manifest(manifest)
    summary = dict(batch=BATCH, mode=a.mode, executed=done, stop=stop,
                   status="INCOMPLETE" if stop else "DONE", ledger=R.read_ledger(runs), caps=plan_caps,
                   authorization=AUTH, r2_ledger=R.read_ledger(R2_RUNS), manifest_pre=pre, manifest_post=post,
                   integrity="OK" if (pre["ok"] and post["ok"]) else "INTEGRITY_FAIL",
                   note="real API calls not authorized; separate GO required (DAMJS_NDC_GO=run)")
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "BATCH_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: summary[k] for k in ("mode", "executed", "stop", "status", "ledger", "integrity")},
                     ensure_ascii=False))
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
