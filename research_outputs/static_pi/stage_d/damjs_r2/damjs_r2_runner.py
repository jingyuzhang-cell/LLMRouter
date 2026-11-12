"""DAMJS_EXP_36 runner: 3 arms x 3 deadlines x 2 scenarios x 2 reps = 36 executions (exploratory).

Each execution runs damjs_r2_child.py in its own process under damsj_executor.run_isolated
(L3 terminate at deadline - 15 s, L4 degraded output). All children share one GlobalBudget
ledger (state/GLOBAL_BUDGET.json) capped at 350 calls / 1.25M tokens / Y2.30; after every
child the runner adds a worst-case charge for calls that errored or were cut off, and stops the
batch as soon as any cap is reached or a reservation was denied.

  replay mode (zero-call):  python3 damjs_r2_runner.py --mode replay [--phase smoke|main|all]
  real mode:                python3 damjs_r2_runner.py --mode real --phase smoke|main
                            needs STAGE_D_REAL_CALLS_AUTHORIZED=1 and DAMJS_R2_GO=<phase>
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
STAGE_D = HERE.parent
sys.path.insert(0, str(STAGE_D))
from damsj_executor import run_isolated

BATCH = "DAMJS_EXP_36"
ARMS = ["Static", "Current-Proposed", "DAMJS"]
DEADLINES = [130.0, 150.0, 240.0]
SCENARIOS = ["S3", "S4"]
REPS = [1, 2]
SMOKE_BLOCKS = [(240.0, "S3", 1), (240.0, "S4", 1)]
ORDER_SEED = 20261106
CAPS = dict(calls=350, tokens=1_250_000, yuan=2.30)
PHASE_CAPS = {"smoke": dict(calls=50, tokens=190_000, yuan=0.37)}   # operator GO 2026-11-06
RESERVE_S = 15.0
KILL_GRACE_S = 3.0
MANIFEST = STAGE_D / "DAMJS_R2_BATCH_MANIFEST.json"
CHILD = HERE / "damjs_r2_child.py"
REPLAY_ARM = {"Static": "Static", "Current-Proposed": "Proposed-Dynamic", "DAMJS": "Proposed-Dynamic"}
# Smallest single-call worst-case reservation in this DAG (E4 on DS@4000: 933 prompt chars + 64 + 4000
# max output; Y = 933*0.8e-6 + 4000*2.8e-6). Below this headroom no further call can be reserved.
MIN_CALL_TOKENS, MIN_CALL_YUAN = 4_997, 0.011946


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def build_order(seed=ORDER_SEED):
    rng = random.Random(seed)
    rest = [(d, s, r) for d in DEADLINES for s in SCENARIOS for r in REPS if (d, s, r) not in SMOKE_BLOCKS]
    rng.shuffle(rest)
    plan = []
    for phase, blocks in (("smoke", SMOKE_BLOCKS), ("main", rest)):
        for d, s, r in blocks:
            arms = ARMS[:]
            rng.shuffle(arms)
            for a in arms:
                plan.append(dict(phase=phase, block=f"{int(d)}s|{s}|r{r}", arm=a, scenario=s, rep=r,
                                 deadline=d, tag=f"{int(d)}s_{s}_r{r}_{a}"))
    return plan


def verify_manifest(path=MANIFEST):
    mf = json.loads(Path(path).read_text("utf-8"))
    mism = []
    for c in mf["components"]:
        p = c["path"] if os.path.isabs(c["path"]) else str(STAGE_D / c["path"])
        actual = sha_file(p) if os.path.exists(p) else "ABSENT"
        if actual != c["sha256"]:
            mism.append(dict(role=c["role"], path=c["path"], expected=c["sha256"][:16], actual=actual[:16]))
    return dict(ok=not mism, mismatches=mism, manifest_sha256=sha_file(path), n=len(mf["components"]))


def load_credentials():
    """Real mode only. Returns env entries for the child; values are never printed or stored."""
    env = {}
    for var, file_var, prov_var, default_prov in (
            ("STAGE_D_GLM_KEY", "DAMJS_R2_GLM_KEY_FILE", "DAMJS_R2_GLM_PROVIDER", None),
            ("DEEPSEEK_API_KEY", "DAMJS_R2_DS_KEY_FILE", "DAMJS_R2_DS_PROVIDER", "deepseek")):
        val = os.environ.get(var, "").strip()
        if not val and os.environ.get(file_var):
            val = Path(os.environ[file_var]).read_text().strip()
        prov = os.environ.get(prov_var, default_prov or "")
        if not val and prov:
            cfg = json.loads(Path(os.environ.get("DAMJS_R2_PROVIDER_CONFIG",
                                                 "/root/.zcode/v2/provider_config.json")).read_text())
            rules = cfg["config"]["providerConfigRules"]["providerRules"]
            val = next((r["config"]["access"]["apiKey"].strip() for r in rules
                        if r.get("providerId") == prov and r["config"]["access"].get("apiKey")), "")
        env[var] = val
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise SystemExit(f"REFUSED: credentials missing for {missing} (values are never printed)")
    return env


def read_progress(path):
    out = []
    try:
        for line in Path(path).read_text("utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return out


def partial_outputs(records, cutoff_ts=None):
    """Latest completed output per node, dropping outputs later invalidated by an action."""
    outs = {}
    for r in records:
        if cutoff_ts is not None and r.get("ts", 0) > cutoff_ts:
            continue
        if r.get("ev") == "node_end" and r.get("ok") and r.get("output") is not None:
            outs[r["node"]] = r["output"]
        elif r.get("ev") == "node_invalidate":
            for n in r.get("nodes", []):
                outs.pop(n, None)
    return outs


def score_text(text):
    import d2_executor as D2
    from terminal_quality import evaluate_terminal_quality
    parsed = D2.extract_json(text or "")
    if not parsed:
        return 0
    term = D2.SA_EX.build_terminal_output(json.loads(json.dumps(parsed)))
    q = evaluate_terminal_quality(D2.SA_EX.CONTRACT, term, D2.SRC())
    return sum(1 for c in q["claim_results"] if c["status"].startswith("CORRECT"))


def degraded_result(records, cutoff_ts):
    outs = partial_outputs(records, cutoff_ts)
    if "FMT" in outs:
        src, tp = "partial_fmt", score_text(outs["FMT"])
    elif "SINK" in outs:
        src, tp = "partial_sink", score_text(outs["SINK"])
    else:
        src, tp = "unknown_all", 0
    return dict(tp=tp, slot_success=round(tp / 23, 4), scored_from=src, completed_nodes=sorted(outs))


def caps_for(phase):
    """Hard caps on the cumulative batch ledger while running `phase` (phase cap within batch cap)."""
    pc = PHASE_CAPS.get(phase) or {}
    return {k: min(v, pc.get(k, v)) for k, v in CAPS.items()}


def ledger_path(runs_dir):
    return Path(runs_dir) / "state" / "GLOBAL_BUDGET.json"


def read_ledger(runs_dir):
    p = ledger_path(runs_dir)
    if not p.exists():
        return dict(calls=0, yuan=0.0, tokens=0)
    d = json.loads(p.read_text("utf-8"))
    return dict(calls=int(d.get("calls", 0)), yuan=float(d.get("yuan", 0.0)), tokens=int(d.get("tokens", 0)))


def reconcile(runs_dir, records):
    """Worst-case charge for calls that started but never settled (error or cut off)."""
    starts = {r["id"]: r for r in records if r.get("ev") == "call_start"}
    ends = {r["id"]: r for r in records if r.get("ev") == "call_end"}
    unsettled = [s for cid, s in starts.items() if not ends.get(cid, {}).get("ok")]
    add_tok = sum(int(s.get("est_tokens", 0)) for s in unsettled)
    add_yuan = sum(float(s.get("est_yuan", 0.0)) for s in unsettled)
    if unsettled:
        led = read_ledger(runs_dir)
        led["tokens"] += add_tok
        led["yuan"] = round(led["yuan"] + add_yuan, 6)
        p = ledger_path(runs_dir)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(led, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
    return dict(n_calls_started=len(starts), n_unsettled=len(unsettled),
                topup_tokens=add_tok, topup_yuan=round(add_yuan, 6),
                unsettled=[dict(node=s["node"], alias=s.get("alias")) for s in unsettled])


def budget_exhausted(led, caps):
    if led["calls"] >= caps["calls"]:
        return "calls"
    if led["tokens"] + MIN_CALL_TOKENS > caps["tokens"]:
        return "tokens"
    if led["yuan"] + MIN_CALL_YUAN > caps["yuan"]:
        return "yuan"
    return None


def run_one(*, tag, arm, scenario, rep, deadline, mode, runs_dir, caps, manifest=MANIFEST,
            replay_src=None, clock_scale=1.0, creds=None, phase="", block=""):
    runs_dir = Path(runs_dir)
    for sub in ("progress", "results", "exec_records", "state", "quarantine"):
        (runs_dir / sub).mkdir(parents=True, exist_ok=True)
    prog = runs_dir / "progress" / f"{tag}.jsonl"
    canc = runs_dir / "progress" / f"{tag}.cancel"
    out = runs_dir / "results" / f"{tag}.json"
    child_out = runs_dir / "progress" / f"{tag}.child.json"
    stamp = time.strftime("%Y%m%dT%H%M%S")
    for p in (prog, child_out):
        if p.exists():
            p.rename(runs_dir / "quarantine" / f"{p.name}.attempt_{stamp}")
    scale = 1.0 if mode == "real" else float(clock_scale)
    env = {k: v for k, v in os.environ.items() if k not in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY")}
    if mode == "real":
        env.update(creds or {})
    launch = time.time()
    env.update(APILOT_ARM=arm, APILOT_SCEN=scenario, APILOT_REP=str(rep), APILOT_DEADLINE=str(deadline),
               APILOT_MODE=mode, APILOT_LAUNCH_WALL=repr(launch), APILOT_STATE=str(runs_dir / "state"),
               APILOT_EXEC_DIR=str(runs_dir / "exec_records"), APILOT_CAPS=json.dumps(caps),
               APILOT_OUT=str(child_out), APILOT_PROGRESS=str(prog), APILOT_CANCEL=str(canc),
               APILOT_BATCH=BATCH, APILOT_MANIFEST=str(manifest) if manifest else "",
               APILOT_REPLAY_SRC=str(replay_src or ""), APILOT_CLOCK_SCALE=str(scale))
    wd = run_isolated(arm=arm, scenario=scenario, rep=rep, deadline_s=deadline / scale,
                      exec_cmd=[sys.executable, str(CHILD)], progress_path=str(prog),
                      cancel_path=str(canc), reserve_s=RESERVE_S / scale,
                      kill_grace_s=max(0.2, KILL_GRACE_S / scale), poll_s=0.05 if scale > 1 else 0.2,
                      env=env, log_path=str(prog) + ".out")
    records = read_progress(prog)
    abort_wall = launch + (deadline - RESERVE_S) / scale
    aborted = wd.get("status") == "INCOMPLETE_DEADLINE_DEGRADED"
    child = json.loads(child_out.read_text("utf-8")) if child_out.exists() else None
    if aborted:
        if child is not None:
            (runs_dir / "quarantine" / f"{tag}.late.json").write_text(
                json.dumps(child, ensure_ascii=False, indent=1), "utf-8")
        deg = degraded_result(records, abort_wall)
        result = dict(arm=arm, scenario=scenario, rep=rep, deadline_s=deadline, mode=mode,
                      status="INCOMPLETE_DEADLINE_DEGRADED", degradation="L4",
                      late_result_quarantined=child is not None, **deg)
    elif child is not None:
        result = child
    else:
        deg = degraded_result(records, None)
        result = dict(arm=arm, scenario=scenario, rep=rep, deadline_s=deadline, mode=mode,
                      status=wd.get("status") or "CHILD_FAILED", degradation="child_failed",
                      child_stderr=wd.get("stderr"), **deg)
    led_before = read_ledger(runs_dir)
    recon = reconcile(runs_dir, records)
    led_after = read_ledger(runs_dir)
    tp = result.get("tp") or 0
    elapsed = wd.get("elapsed")
    rec = dict(batch=BATCH, phase=phase, block=block, tag=tag, arm=arm, scenario=scenario, rep=rep,
               deadline_s=deadline, mode=mode, watchdog=wd.get("status"), elapsed_s=elapsed,
               aborted=aborted, status=result.get("status"), tp=tp,
               joint_success=bool((not aborted) and result.get("status") == "COMPLETE" and tp >= 12),
               identity_ok=(result.get("identity") or {}).get("ok"),
               network_attempts=max(int(result.get("network_attempts") or 0),
                                    sum(1 for r in records if r.get("ev") == "call_end"
                                        and "NETWORK_TRIPWIRE" in str(r.get("err", "")))),
               reconcile=recon, ledger_before=led_before, ledger_after=led_after,
               replay_src=str(replay_src) if replay_src else None)
    result["runner"] = rec
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, out)
    with open(runs_dir / "LEDGER.jsonl", "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def stop_reason(rec, caps):
    if rec["status"] == "INCOMPLETE_BUDGET":
        return "INCOMPLETE_BUDGET: a reservation was denied by the batch ledger"
    hit = budget_exhausted(rec["ledger_after"], caps)
    if hit:
        return f"BUDGET_CAP_REACHED:{hit}"
    if rec["identity_ok"] is False:
        return "INTEGRITY_FAIL: component SHA mismatch inside the execution"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["replay", "real"], default="replay")
    ap.add_argument("--phase", choices=["smoke", "main", "all"], default="smoke")
    ap.add_argument("--runs-dir", default=None)
    ap.add_argument("--clock-scale", type=float, default=50.0)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.mode == "real":
        if a.phase == "all":
            raise SystemExit("REFUSED: real mode runs one phase per explicit GO")
        if os.environ.get("STAGE_D_REAL_CALLS_AUTHORIZED") != "1" or os.environ.get("DAMJS_R2_GO") != a.phase:
            raise SystemExit(f"REFUSED: real {a.phase} needs STAGE_D_REAL_CALLS_AUTHORIZED=1 and DAMJS_R2_GO={a.phase}")
    runs_dir = Path(a.runs_dir or (HERE / ("runs_real" if a.mode == "real" else "runs_replay")))
    pre = verify_manifest()
    if not pre["ok"]:
        raise SystemExit(f"STOP INTEGRITY_FAIL before batch: {pre['mismatches']}")
    plan = [p for p in build_order() if a.phase == "all" or p["phase"] == a.phase]
    if a.mode == "real" and a.phase == "main":
        smoke = [p for p in build_order() if p["phase"] == "smoke"]
        missing = [p["tag"] for p in smoke if not (runs_dir / "results" / f"{p['tag']}.json").exists()]
        if missing:
            raise SystemExit(f"REFUSED: smoke phase incomplete: {missing}")
    creds = load_credentials() if a.mode == "real" else None
    done, stop = 0, None
    for p in plan:
        if a.limit is not None and done >= a.limit:
            break
        if (runs_dir / "results" / f"{p['tag']}.json").exists():
            continue
        if a.mode == "real" and (runs_dir / "progress" / f"{p['tag']}.jsonl").exists():
            stop = f"ORPHAN_ATTEMPT: {p['tag']} has a progress log but no result; not retried automatically"
            break
        caps = caps_for(p["phase"])
        hit = budget_exhausted(read_ledger(runs_dir), caps)
        if hit:
            stop = f"BUDGET_CAP_REACHED:{hit} (before launching {p['tag']})"
            break
        src = None
        if a.mode == "replay":
            src = STAGE_D / "runs_final" / f"{REPLAY_ARM[p['arm']]}__{p['scenario']}__r{p['rep']}.json"
        rec = run_one(tag=p["tag"], arm=p["arm"], scenario=p["scenario"], rep=p["rep"],
                      deadline=p["deadline"], mode=a.mode, runs_dir=runs_dir, caps=caps,
                      replay_src=src, clock_scale=a.clock_scale, creds=creds,
                      phase=p["phase"], block=p["block"])
        done += 1
        print(f"[{done:2d}] {p['tag']}: status={rec['status']} tp={rec['tp']} watchdog={rec['watchdog']} "
              f"ledger={rec['ledger_after']}", flush=True)
        stop = stop_reason(rec, caps)
        if stop:
            break
    post = verify_manifest()
    summary = dict(batch=BATCH, mode=a.mode, phase=a.phase, executed=done, stop=stop,
                   status="INCOMPLETE" if stop else ("PHASE_DONE" if all(
                       (runs_dir / "results" / f"{q['tag']}.json").exists() for q in plan) else "PARTIAL_LIMIT"),
                   ledger=read_ledger(runs_dir), caps=CAPS,
                   phase_caps={ph: caps_for(ph) for ph in sorted({q["phase"] for q in plan})},
                   manifest_pre=pre, manifest_post=post,
                   integrity="OK" if (pre["ok"] and post["ok"]) else "INTEGRITY_FAIL")
    (runs_dir / f"BATCH_SUMMARY_{a.phase}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
