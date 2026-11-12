#!/usr/bin/env python3
"""Parameter-agnostic zero-call pre-launch checks for DAMJS_V03_PILOT (operator request 2026-11-07, item 2).

These check WHEN and HOW the mechanisms act, not which parameter values are right (the EV parameter
decision is open, see DAMJS_V0_3_PILOT_ERRATUM_1.md). All runs are replays of archived real
responses through the pilot child (network tripwire, no credentials).

P1 repair-call failure (smoke DAMJS S3 record, 240 s), four arms:
     first J1 call_outcome (ok) precedes the first J1 decision, which is unlatched and chooses
     Z_structure in every arm; the failed repair's call_outcome precedes the next J1 decision,
     which is latched; in ND arms the rollback precedes J2's dispatch
P2 first-call failure (smoke Current-Proposed S4 record, J1 #1 capped; 320 s so repair is
     deadline-feasible), four arms: the capped call's outcome latches before the J1 decision;
     EV arms record an EV_gate exclusion of Z_structure, non-EV arms choose it; no rollback in any
     arm (v1 invalid -> nothing to protect)
P3 posterior bookkeeping: at every decision, the estimator's observed (calls, fails) for GLM equals
     the J1 call_outcome events logged before that decision
P4 node-level scope on the executor path in both ND arms (rollback only on direct targets)
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import test_v03_pilot as TP
import v03_runner as VR

SMOKE_REC = STAGE_D / "damjs_r2" / "runs_real" / "exec_records"
ARMS = ("R2", "ND-only", "EV-only", "V0.3")
EV_ARMS, ND_ARMS = {"EV-only", "V0.3"}, {"ND-only", "V0.3"}
RES = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "tests": [], "runs": []}


def check(tid, name, ok, **ev):
    RES["tests"].append(dict(id=tid, name=name, ok=bool(ok), evidence=ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {tid} {name}", flush=True)


def run(tag, arm, sc, src, deadline):
    runs = TP.tmp("pre")
    rec = VR.run_one(tag=tag, arm=arm, scenario=sc, rep=1, deadline=deadline, mode="replay", runs_dir=runs,
                     caps=dict(calls=140, tokens=450_000, yuan=0.95), manifest=VR.MANIFEST, replay_src=src,
                     clock_scale=TP.SCALE)
    prog = TP.R.read_progress(runs / "progress" / f"{tag}.jsonl")
    RES["runs"].append(dict(tag=tag, status=rec["status"], net=rec["network_attempts"]))
    return rec, prog


def ts(x):
    return x.get("ts", 0.0)


def j1_events(prog):
    outs = [x for x in prog if x.get("ev") == "call_outcome" and x["node"] == "J1"]
    decs = [x for x in prog if x.get("ev") == "damjs_decide" and x["node"] == "J1"]
    return outs, decs


def p1():
    rows, ok = [], True
    for arm in ARMS:
        rec, prog = run(f"p1_{arm}", arm, "S3", SMOKE_REC / "DAMJS__S3__r1__D240.json", 240.0)
        outs, decs = j1_events(prog)
        rb = [x for x in prog if x.get("ev") == "node_rollback"]
        j2 = next((x for x in prog if x.get("ev") == "node_start" and x["node"] == "J2"), None)
        g0 = (decs[0].get("estimator") or {}).get("glm53flash", {}) if decs else {}
        g1 = (decs[1].get("estimator") or {}).get("glm53flash", {}) if len(decs) > 1 else {}
        r = dict(arm=arm, outcomes=[(x["failed"], round(ts(x), 3)) for x in outs],
                 decisions=[(x["chosen"], round(ts(x), 3)) for x in decs],
                 first_latched=g0.get("slow"), first_p=g0.get("p"), second_latched=g1.get("slow"),
                 rollback=[x["node"] for x in rb])
        good = (len(outs) >= 2 and len(decs) >= 2 and not outs[0]["failed"] and outs[1]["failed"]
                and ts(outs[0]) <= ts(decs[0]) and ts(outs[1]) <= ts(decs[1])
                and g0.get("slow") is False and decs[0]["chosen"] == "Z_structure" and g1.get("slow") is True
                and ((arm in ND_ARMS) == bool(rb)) and (not rb or (j2 and ts(rb[0]) <= ts(j2))))
        r["ok"] = good
        ok &= good
        rows.append(r)
    check("P1", "repair-call failure: estimator updated before each decision; first decision unlatched and repairs "
                "in all arms; second latched; ND rollback precedes J2 dispatch", ok, rows=rows)


def p2():
    rows, ok = [], True
    for arm in ARMS:
        rec, prog = run(f"p2_{arm}", arm, "S4", SMOKE_REC / "Current-Proposed__S4__r1__D240.json", 320.0)
        outs, decs = j1_events(prog)
        d0 = decs[0] if decs else {}
        excl = [e for e in d0.get("excluded", []) if e.get("kind") == "Z_structure"
                and str(e.get("why", "")).startswith("EV_gate")]
        rb = [x for x in prog if x.get("ev") == "node_rollback"]
        g = (d0.get("estimator") or {}).get("glm53flash", {})
        r = dict(arm=arm, first_outcome=(outs[0]["failed"], outs[0].get("capped")) if outs else None,
                 latched_at_decision=g.get("slow"), chosen=d0.get("chosen"), ev_gate_excluded=bool(excl),
                 ev_record=(excl[0].get("ev_record") if excl else None), rollbacks=len(rb),
                 order_ok=bool(outs and decs and ts(outs[0]) <= ts(d0)))
        good = (r["first_outcome"] == (True, True) and r["order_ok"] and g.get("slow") is True and not rb
                and ((arm in EV_ARMS and excl and d0.get("chosen") == "NONE")
                     or (arm not in EV_ARMS and not excl and d0.get("chosen") == "Z_structure")))
        r["ok"] = good
        ok &= good
        rows.append(r)
    check("P2", "first-call failure: latch set before the J1 decision; EV arms exclude Z_structure (EV_gate), "
                "non-EV arms choose it; no rollback anywhere (v1 invalid)", ok, rows=rows)


def p3():
    bad, n = [], 0
    for r in RES["runs"]:
        pass
    for tag in [x["tag"] for x in RES["runs"]]:
        pass
    for arm in ARMS:
        for name, sc, src, dl in (("p3a", "S3", "DAMJS__S3__r1__D240.json", 240.0),
                                  ("p3b", "S4", "Current-Proposed__S4__r1__D240.json", 320.0)):
            rec, prog = run(f"{name}_{arm}", arm, sc, SMOKE_REC / src, dl)
            seen_calls = seen_fails = 0
            for x in prog:
                if x.get("ev") == "call_outcome" and x.get("alias") == "glm53flash":
                    seen_calls += 1
                    seen_fails += bool(x["failed"])
                elif x.get("ev") == "damjs_decide":
                    n += 1
                    obs = ((x.get("estimator") or {}).get("glm53flash") or {}).get("observed") or dict(calls=0, fails=0)
                    if (obs.get("calls"), obs.get("fails")) != (seen_calls, seen_fails):
                        bad.append((arm, sc, x["node"], obs, (seen_calls, seen_fails)))
    check("P3", "posterior bookkeeping: every decision's GLM (calls, fails) equals the outcomes logged before it",
          n > 0 and not bad, decisions=n, mismatches=bad[:8])


def p4():
    rows, ok = [], True
    for arm in ND_ARMS:
        rec, prog = run(f"p4_{arm}", arm, "S3", SMOKE_REC / "DAMJS__S3__r1__D240.json", 240.0)
        rb = [x["node"] for x in prog if x.get("ev") == "node_rollback"]
        direct = {x["target"] for x in prog if x.get("ev") == "node_invalidate"}
        down = {n for x in prog if x.get("ev") == "node_invalidate" for n in x["nodes"]} - direct
        committed = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1]["output"]
        good = rb == ["J1"] and set(rb) <= direct and not (set(rb) & down) and TP.V03._valid(committed)
        ok &= good
        rows.append(dict(arm=arm, rollbacks=rb, direct=sorted(direct), downstream=sorted(down), ok=good))
    check("P4", "node-level scope in both ND arms: exactly one rollback, on the directly repaired J1; committed J1 valid",
          ok, rows=rows)


def main():
    t0 = time.time()
    p1(); p2(); p3(); p4()
    net = sum(r["net"] for r in RES["runs"])
    check("P5", "zero network attempts across all pre-launch replay executions", net == 0, executions=len(RES["runs"]))
    n = sum(t["ok"] for t in RES["tests"])
    RES["summary"] = dict(passed=n, failed=len(RES["tests"]) - n, executions=len(RES["runs"]),
                          wall_s=round(time.time() - t0, 1), manifest_sha256=VR.sha_file(VR.MANIFEST),
                          note="parameter-agnostic mechanics; run under the v1 parameter set, which the erratum voids for launch")
    (HERE / "PRELAUNCH_RESULTS.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nRESULT: {n} passed, {len(RES['tests']) - n} failed ({len(RES['runs'])} replay executions)")
    return 0 if n == len(RES["tests"]) else 1


if __name__ == "__main__":
    sys.exit(main())
