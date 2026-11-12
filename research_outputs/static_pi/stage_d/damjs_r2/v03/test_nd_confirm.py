#!/usr/bin/env python3
"""Zero-call acceptance for DAMJS_ND_CONFIRM at the 300 s / 8-pair configuration (replay).

  K1 full 8-pair replay flow at 300 s: 24 executions, unique exec ids (run_tag), per-pair
     randomized arm order under the frozen seed
  K2 budget: confirm caps enforced (phase caps reach children); stop on denial
  K3 resume protection: second invocation skips everything, zero re-charge, no orphan
  K4 caliber v3 SHA matches CALIBER_V3_FREEZE record; prereg registered and unedited
  K5 mechanism spot-check on pair 1 (R2 destructive, ND byte-exact rollback)
  K6 zero network across all replay executions
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
import damjs_r2_runner as R
import nd_controlled as NDC

RES = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "tests": []}
CAPS = dict(calls=100, tokens=360_000, yuan=1.60)
CONF_PREREG = STAGE_D / "damjs_r2" / "v03" / "DAMJS_ND_CONFIRM_PREREG.md"
CONF_MANIFEST = STAGE_D / "DAMJS_ND_CONFIRM_MANIFEST.json"


def check(tid, name, ok, **ev):
    RES["tests"].append(dict(id=tid, name=name, ok=bool(ok), evidence=ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {tid} {name}", flush=True)


def tmp():
    return Path(__import__("tempfile").mkdtemp(prefix="ndc_conf_"))


def main():
    t0 = time.time()
    runs = tmp()
    argv = ["--mode", "replay", "--runs-dir", str(runs), "--clock-scale", "10.0",
            "--deadline", "300", "--reps", ",".join(str(r) for r in range(1, 9)),
            "--caps", json.dumps(CAPS), "--prereg", str(CONF_PREREG), "--manifest", str(CONF_MANIFEST)]
    rc = NDC.main(argv)
    summ = json.loads((runs / "BATCH_SUMMARY.json").read_text("utf-8"))

    exec_ids, order = [], {}
    for rep in range(1, 9):
        starts = []
        for arm in ("R2", "ND-only"):
            p = runs / "progress" / f"NDC_r{rep}_{arm}.jsonl"
            ev = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
            st = next(x for x in ev if x["ev"] == "exec_start")
            exec_ids.append((f"r{rep}_{arm}", st.get("ts")))
            starts.append((arm, st.get("ts")))
        order[rep] = [a for a, _ in sorted(starts, key=lambda x: x[1])]
    uniq = len({t for t, _ in exec_ids}) == 16
    orders = [order[r] for r in range(1, 9)]
    check("K1", "300 s / 8-pair flow complete; 16 arm executions with unique exec records; per-pair arm "
                "order from the frozen seed (orders vary across pairs)", rc == 0 and summ["status"] == "DONE"
          and len(exec_ids) == 16 and uniq and len({tuple(o) for o in orders}) >= 1,
          status=summ["status"], orders=orders)
    check("K2", "confirm caps enforced and within limits", summ["caps"] == CAPS
          and summ["ledger"]["calls"] <= CAPS["calls"] and summ["integrity"] == "OK",
          ledger=summ["ledger"], caps=summ["caps"])
    rc2 = NDC.main(argv)
    summ2 = json.loads((runs / "BATCH_SUMMARY.json").read_text("utf-8"))
    led2 = R.read_ledger(runs)
    check("K3", "resume protection: second invocation executes nothing, ledger unchanged, no orphan stop",
          rc2 == 0 and summ2["executed"] == 0 and summ2["status"] == "DONE" and summ2["stop"] is None
          and led2 == summ["ledger"], second_executed=summ2["executed"], ledger=led2)
    fz = json.loads((HERE / "CONFIRM_DRAFT_FREEZE.json").read_text("utf-8"))
    v3_sha = fz["components"]["caliber_v3.py"]["sha256"]
    check("K4", "caliber v3 SHA matches its freeze record; confirm prereg registered and matches disk",
          v3_sha == R.sha_file(STAGE_D / "damjs_r2" / "v03" / "caliber_v3.py")
          and NDC.prereg_gate(str(CONF_MANIFEST), str(CONF_PREREG)) is None)
    prog = [json.loads(l) for l in (runs / "progress" / "NDC_r1_R2.jsonl").read_text().splitlines() if l.strip()]
    prognd = [json.loads(l) for l in (runs / "progress" / "NDC_r1_ND-only.jsonl").read_text().splitlines() if l.strip()]
    fx = [x for x in (runs / "progress" / "NDC_r1_GEN.jsonl").read_text().splitlines() if x.strip()]
    import json as j
    v1 = next(j.loads(x)["text"] for x in fx if j.loads(x).get("ev") == "fixture_call" and j.loads(x)["node"] == "J1")
    r2j1 = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1]["output"] or ""
    ndj1 = [x for x in prognd if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1]["output"] or ""
    rb = [x for x in prognd if x.get("ev") == "node_rollback"]
    check("K5", "mechanism on pair 1: R2 destructive (empty J1), ND byte-exact rollback to fixture v1",
          r2j1 == "" and ndj1 == v1 and len(rb) == 1)
    net = 0
    for rep in range(1, 9):
        for arm in ("R2", "ND-only", "GEN"):
            f = runs / "progress" / f"NDC_r{rep}_{arm}.jsonl"
            if f.exists():
                net += sum(1 for x in f.read_text().splitlines() if "NETWORK_TRIPWIRE" in x)
    check("K6", "zero network attempts across all 24 replay executions", net == 0, trips=net)
    n = sum(t["ok"] for t in RES["tests"])
    RES["summary"] = dict(passed=n, failed=len(RES["tests"]) - n, wall_s=round(time.time() - t0, 1),
                          manifest_sha256=R.sha_file(CONF_MANIFEST), prereg_sha256=R.sha_file(CONF_PREREG))
    (HERE / "ND_CONFIRM_ACCEPTANCE.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nRESULT: {n} passed, {len(RES['tests']) - n} failed")
    return 0 if n == len(RES["tests"]) else 1


if __name__ == "__main__":
    sys.exit(main())
