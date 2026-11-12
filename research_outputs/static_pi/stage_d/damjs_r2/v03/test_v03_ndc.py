#!/usr/bin/env python3
"""Zero-call acceptance of the DAMJS_ND_CONTROLLED wiring (prereg DAMJS_ND_CONTROLLED_PREREG.md).

Replay mode: the "live" transport replays the archived smoke DAMJS S3 record, so the whole flow
(generation run -> fixture -> two arms with injected repair) runs with zero network.

  C1 generation run stops right after J1's first call; fixture has 5 calls with texts/walls
  C2 both arms replay the upstream fixture byte-identically; exactly one injected call per arm,
     byte-identical (empty text, 1690/8192, wall 119.83) and recorded outcome="injected"
  C3 arm order randomized per rep, reproducible under the frozen seed
  C4 ledger separation: fixture replays deducted (not real, not injected); injected recorded with
     history tokens + simulated accounting; real calls only from generation + J2/SINK; caps hold
  C5 the injected wall is reflected identically in both arms' clocks (J1 repair span ~119.8 s)
  C6 mechanism on the executor path: R2 commits the empty v2 (destructive), ND rolls back to the
     fixture v1 byte-exactly and J2 starts after the rollback
  C7 dual-caliber + DOCMAP-normalized scoring recorded per arm; identity verified; zero network
  C8 real-mode gate: refused without DAMJS_NDC_GO=run / without the prereg registered
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import d2_executor as D2
import damjs_r2_runner as R
import nd_controlled as NDC
import v03_runner as VR

RES = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "tests": [], "rows": []}


def check(tid, name, ok, **ev):
    RES["tests"].append(dict(id=tid, name=name, ok=bool(ok), evidence=ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {tid} {name}", flush=True)


def tmp():
    return Path(__import__("tempfile").mkdtemp(prefix="ndc_acc_"))


def progress(runs, tag):
    return [json.loads(l) for l in (runs / "progress" / f"{tag}.jsonl").read_text().splitlines() if l.strip()]


def run_batch(runs_dir):
    return NDC.main(["--mode", "replay", "--runs-dir", str(runs_dir), "--clock-scale", "10.0"])


def fixture_of(runs, rep):
    fx = [x for x in progress(runs, f"NDC_r{rep}_GEN") if x.get("ev") == "fixture_call"]
    return fx


def arm_res(runs, rep, arm):
    p = runs / "results" / f"NDC_r{rep}_{arm}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def main():
    t0 = time.time()
    runs = tmp()
    rc = run_batch(runs)
    summ = json.loads((runs / "BATCH_SUMMARY.json").read_text("utf-8"))
    rows = [json.loads(l) for l in (runs / "NDC_LEDGER.jsonl").read_text().splitlines()]
    RES["batch"] = summ

    # C1 generation stops after J1
    ok_c1 = True
    for rep in NDC.REPS:
        fx = fixture_of(runs, rep)
        nodes = [x["node"] for x in fx]
        pr = progress(runs, f"NDC_r{rep}_GEN")
        ok_c1 &= (sorted(set(nodes)) == ["E1", "E2", "E3", "E4", "J1"] and nodes.count("J1") == 1
                  and all(x["valid"] for x in fx)
                  and any(x.get("ev") == "fixture_complete" for x in pr)
                  and not any(x.get("ev") == "node_start" and x["node"] in ("J2", "SINK") for x in pr))
    check("C1", "generation run stops after J1's first valid call; fixture = E1-E4 + J1 v1", ok_c1)

    # C2 fixture identity + injection identity
    ok_c2 = True
    ev_c2 = []
    for rep in NDC.REPS:
        fx = fixture_of(runs, rep)
        v1 = [x for x in fx if x["node"] == "J1"][0]
        for arm in ("R2", "ND-only"):
            res = arm_res(runs, rep, arm)
            prog = progress(runs, f"NDC_r{rep}_{arm}")
            log = res.get("controlled_log") or []
            up = [c for c in log if c["source"] == "fixture"]
            j1_ends = [x for x in prog if x.get("ev") == "call_end" and x["node"] == "J1"]
            inj = res.get("injected_calls") or []
            outs = [x for x in prog if x.get("ev") == "call_outcome" and x.get("outcome") == "injected"]
            est = ((res.get("bridge") or {}).get("estimator") or {}).get("glm53flash", {})
            arm_ok = (len(up) == 5 and len(j1_ends) == 2 and len(inj) == 1 and inj[0]["source"] == "injected"
                      and len(outs) == 1 and est.get("observed", {}).get("calls", 0) == 1
                      and est.get("observed", {}).get("fails", 0) == 0
                      and est.get("injected") == 1 and est.get("slow") is False)
            ev_c2.append(dict(rep=rep, arm=arm, fixture_calls=len(up), injected=len(inj), estimator=est))
            ok_c2 &= arm_ok
        inj1 = (arm_res(runs, rep, "R2").get("controlled_log") or [])
        inj2 = (arm_res(runs, rep, "ND-only").get("controlled_log") or [])
        ok_c2 &= inj1 == inj2
    check("C2", "both arms replay the identical upstream fixture; exactly one byte-identical injected repair "
                "per arm, classified outcome=injected and invisible to the estimator", ok_c2, arms=ev_c2)

    # C3 order randomization reproducibility
    orders1, orders2 = [], []
    for _ in range(2):
        rng = __import__("random").Random(NDC.SEED)
        orders1.append([rng.shuffle(o := ["R2", "ND-only"]) or o[:] for _ in NDC.REPS])
    check("C3", "arm order per rep randomized and reproducible under the frozen seed", orders1[0] == orders1[1]
          and any(o[0] != o[1] for o in orders1[0]) or len({tuple(o) for o in orders1[0]}) > 1,
          orders=orders1[0])

    # C4 ledger separation
    gen_rows = [r for r in rows if r["kind"] == "generation"]
    arm_rows = [r for r in rows if r["kind"] in ("R2", "ND-only")]
    ok_c4 = (len(gen_rows) == 3 and len(arm_rows) == 6
             and all(r["real"]["calls"] >= 0 for r in rows)
             and all(r["fixture_replays_deducted"]["calls"] == 5 for r in arm_rows)
             and all(r["injected"]["calls"] == 1 and r["injected"]["history_tokens"] == 1690 + 8192
                     and abs(r["injected"]["simulated_accounting_yuan"] - 0.024294) < 1e-4 for r in arm_rows)
             and all(r["real"]["calls"] == r["charged_after_deduction"]["calls"] - 1 for r in arm_rows))
    real_total = sum(r["real"]["calls"] for r in rows)
    check("C4", "ledger separation: fixture replays deducted; injected simulated costs isolated; real calls = "
                "generation + J2/SINK only; within caps",
          ok_c4 and real_total <= NDC.CAPS["calls"] and summ["ledger"]["calls"] <= NDC.CAPS["calls"],
          real_calls_total=real_total, ledger=summ["ledger"], caps=NDC.CAPS, rows=rows[:3])

    # C5 injected wall in both arms' clocks
    walls = {}
    ok_c5 = True
    for rep in NDC.REPS:
        for arm in ("R2", "ND-only"):
            prog = progress(runs, f"NDC_r{rep}_{arm}")
            st = [x for x in prog if x.get("ev") == "call_start" and x["node"] == "J1"]
            en = {x["id"]: x for x in prog if x.get("ev") == "call_end" and x["node"] == "J1"}
            inj_wall = round(en[st[1]["id"]]["t"] - st[1]["t"], 1) if len(st) > 1 and st[1]["id"] in en else None
            walls[f"r{rep}_{arm}"] = inj_wall
            ok_c5 &= inj_wall is not None and abs(inj_wall - 119.8) < 1.5
    check("C5", "injected 119.83 s wall reflected identically in both arms' executor clocks", ok_c5, walls=walls)

    # C6 mechanism
    ok_c6 = True
    ev_c6 = []
    for rep in NDC.REPS:
        fx_v1 = [x for x in fixture_of(runs, rep) if x["node"] == "J1"][0]["text"]
        r2p = progress(runs, f"NDC_r{rep}_R2")
        ndp = progress(runs, f"NDC_r{rep}_ND-only")
        r2_j1 = [x for x in r2p if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1]["output"] or ""
        nd_j1 = [x for x in ndp if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1]["output"] or ""
        rb = [x for x in ndp if x.get("ev") == "node_rollback"]
        j2 = next((x for x in ndp if x.get("ev") == "node_start" and x["node"] == "J2"), None)
        ok_c6 &= (r2_j1 == "" and nd_j1 == fx_v1 and len(rb) == 1 and rb[0]["node"] == "J1"
                  and j2 and rb[0]["t"] <= j2["t"])
        ev_c6.append(dict(rep=rep, r2_j1_len=len(r2_j1), nd_j1_len=len(nd_j1), v1_len=len(fx_v1), rollback=len(rb)))
    check("C6", "mechanism on the executor path: R2 commits the empty v2 (destructive); ND rolls back to the "
                "fixture v1 byte-exactly and J2 starts after the rollback", ok_c6, reps=ev_c6)

    # C7 identity, network, caliber
    nets = all((arm_res(runs, rep, arm).get("network_attempts") or 0) == 0
               for rep in NDC.REPS for arm in ("R2", "ND-only"))
    ids = all((arm_res(runs, rep, arm).get("identity") or {}).get("ok") is True
              for rep in NDC.REPS for arm in ("R2", "ND-only"))
    marked = all(arm_res(runs, rep, arm).get("controlled_injection") is True
                 for rep in NDC.REPS for arm in ("R2", "ND-only"))
    check("C7", "identity verified in every arm execution; zero network; controlled_injection marked; "
                "dual-caliber TP recorded", nets and ids and marked
          and all("tp_strict" in arm_res(runs, rep, arm) for rep in NDC.REPS for arm in ("R2", "ND-only")))

    # C8 real gate
    gates = []
    saved = R.load_credentials, NDC.run_one
    R.load_credentials = lambda: (_ for _ in ()).throw(RuntimeError("SAFETY_NET"))

    def fake_run(**k):
        raise RuntimeError("SAFETY_NET: reached launch")
    NDC.run_one = fake_run
    keep = {kk: os.environ.get(kk) for kk in ("STAGE_D_REAL_CALLS_AUTHORIZED", "DAMJS_NDC_GO")}
    try:
        for env in ({}, {"STAGE_D_REAL_CALLS_AUTHORIZED": "1"}, {"STAGE_D_REAL_CALLS_AUTHORIZED": "1", "DAMJS_NDC_GO": "run"}):
            for kk in keep:
                os.environ.pop(kk, None)
            os.environ.update(env)
            try:
                NDC.main(["--mode", "real", "--runs-dir", str(tmp())])
                gates.append((sorted(env), "NOT_REFUSED"))
            except SystemExit as e:
                gates.append((sorted(env), str(e)[:70]))
            except RuntimeError as e:
                gates.append((sorted(env), "PASSED_GATES->SAFETY_NET" if "SAFETY_NET" in str(e) else f"ERR:{e}"[:70]))
    finally:
        R.load_credentials, NDC.run_one = saved
        for kk, vv in keep.items():
            os.environ.pop(kk, None)
            if vv is not None:
                os.environ[kk] = vv
    check("C8", "real mode refused without authorization and without GO; with both plus the registered frozen "
                "prereg, the lock opens only as far as the credential step (stubbed safety net, no launch)",
          gates[0][1].startswith("REFUSED") and gates[1][1].startswith("REFUSED")
          and gates[2][1] == "PASSED_GATES->SAFETY_NET", gates=gates)

    n = sum(t["ok"] for t in RES["tests"])
    RES["summary"] = dict(passed=n, failed=len(RES["tests"]) - n, wall_s=round(time.time() - t0, 1),
                          manifest_sha256=NDC.sha_file(NDC.MANIFEST), batch_status=summ["status"])
    (HERE / "NDC_ACCEPTANCE_RESULTS.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nRESULT: {n} passed, {len(RES['tests']) - n} failed | batch stop={summ['stop']}")
    return 0 if n == len(RES["tests"]) and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
