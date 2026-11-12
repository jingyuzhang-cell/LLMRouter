#!/usr/bin/env python3
"""Zero-call acceptance of the DAMJS_V03_PILOT wiring (v03_child + v03_runner + manifest).

A0  V0.3 mechanism suite (test_damjs_v03.py) still 7/7
A1  fidelity: the pilot's R2 arm replays the real R2 smoke DAMJS executions (S3, S4) field-for-field
A2  four arms on the S3 smoke replay: switches wired, rollback iff nd, uniform instrumentation
A3  four arms on the S4 smoke replay: Z_format kept, no rollback, TP equal
A4  budget: phase caps reach the children; denial -> INCOMPLETE_BUDGET -> stop; relaunch refused
A5  authorization ceiling shared with the R2 ledger blocks launch at zero room
A6  identity: manifest matches; per-execution identity ok; tamper -> INTEGRITY_FAIL; runner refuses
A7  real-mode gates incl. the frozen-prereg gate (absent today -> refused even with GO env)
A8  stop-rule detectors (C1 violation, V0.3 traceback) on synthetic records
A9  zero network across all replay executions; replay children receive no credentials
A10 rollback scope probe: CommitDict also protects re-dispatched downstream nodes (documents the
    version-skew question for the frozen prereg)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
for _p in (STAGE_D, STAGE_D / "damjs_r2", HERE):
    sys.path.insert(0, str(_p))
for _k in ("STAGE_D_GLM_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(_k, None)
import damjs_r2_runner as R
import v03_runner as VR
import damjs_v03 as V03

SMOKE = STAGE_D / "damjs_r2" / "runs_real"
RES = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "tests": [], "runs": []}
SCALE = 10.0


def check(tid, name, ok, **ev):
    RES["tests"].append(dict(id=tid, name=name, ok=bool(ok), evidence=ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {tid} {name}", flush=True)


def tmp(prefix):
    return Path(tempfile.mkdtemp(prefix=f"v03pilot_{prefix}_"))


def run(runs, tag, arm, sc, caps=None, manifest=None):
    rec = VR.run_one(tag=tag, arm=arm, scenario=sc, rep=1, deadline=240.0, mode="replay", runs_dir=runs,
                     caps=caps or dict(calls=140, tokens=450_000, yuan=0.95), manifest=manifest or VR.MANIFEST,
                     replay_src=VR.REPLAY_SRC[sc], clock_scale=SCALE)
    res = json.loads((Path(runs) / "results" / f"{tag}.json").read_text("utf-8"))
    prog = R.read_progress(Path(runs) / "progress" / f"{tag}.jsonl")
    RES["runs"].append(dict(tag=tag, arm=arm, scenario=sc, status=rec["status"], tp=rec["tp"],
                            tp_strict=res.get("tp_strict"), net=rec["network_attempts"],
                            identity_ok=rec["identity_ok"], rollbacks=len([x for x in prog if x.get("ev") == "node_rollback"])))
    return rec, res, prog


def smoke(sc):
    return json.loads((SMOKE / "results" / f"240s_{sc}_r1_DAMJS.json").read_text("utf-8"))


def a0():
    archived = HERE / "V03_VALIDATION_RESULTS_v2.json"
    keep = archived.read_bytes()
    try:
        p = subprocess.run([sys.executable, str(HERE / "test_damjs_v03.py")], capture_output=True, text=True,
                           timeout=1800, cwd=str(HERE))
        rerun = archived.read_bytes()
    finally:
        archived.write_bytes(keep)
    (HERE / "PILOT_ACCEPTANCE_A0_RERUN.json").write_bytes(rerun)
    check("A0", "V0.3 mechanism suite still 8/8 (archived results file restored byte-exact)",
          "8 passed, 0 failed" in p.stdout and archived.read_bytes() == keep,
          tail=(p.stdout.strip().splitlines() or [""])[-1])


def a1():
    runs, rows, ok = tmp("a1"), [], True
    for sc in ("S3", "S4"):
        rec, res, prog = run(runs, f"a1_R2_{sc}", "R2", sc)
        sm = smoke(sc)
        same = dict(tp=res["tp"] == sm["tp"], status=res["status"] == sm["status"], calls=res["calls"] == sm["calls"],
                    actions=[(a["kind"], a["node"]) for a in res["actions"]] == [(a["kind"], a["node"]) for a in sm["actions"]],
                    per_node=res["per_node_calls"] == sm["per_node_calls"],
                    chosen=[d.get("chosen") for d in res["decisions"]] == [d.get("chosen") for d in sm["decisions"]])
        ok &= all(same.values())
        rows.append(dict(scenario=sc, tp=res["tp"], smoke_tp=sm["tp"], tp_strict=res["tp_strict"], match=same))
    check("A1", "pilot R2 arm reproduces the real R2 smoke DAMJS executions (TP/status/calls/actions/decisions)",
          ok, rows=rows)


def a2():
    runs, rows = tmp("a2"), []
    for arm, (nd, ev) in V03_ARMS.items():
        rec, res, prog = run(runs, f"a2_{arm}_S3", arm, "S3")
        start = next(x for x in prog if x.get("ev") == "exec_start")
        rb = [x for x in prog if x.get("ev") == "node_rollback"]
        j1_commit = [x for x in prog if x.get("ev") == "node_end" and x["node"] == "J1" and x.get("ok")][-1]["output"] or ""
        first = next(x for x in prog if x.get("ev") == "damjs_decide" and x["node"] == "J1")
        est = res["bridge"]["estimator"].get("glm53flash", {})
        rows.append(dict(arm=arm, nd=start["nd"], ev_gate=start["ev_gate"], policy=start["policy"], rollbacks=len(rb),
                         committed_j1_valid=V03._valid(j1_commit), first_j1_choice=first["chosen"],
                         glm_latched=est.get("slow"), tp=res["tp"], tp_strict=res["tp_strict"]))
    ok = all(r["nd"] == V03_ARMS[r["arm"]][0] and r["ev_gate"] == V03_ARMS[r["arm"]][1]
             and r["policy"] == "damjs_v03.BridgeV03" and (r["rollbacks"] == 1) == r["nd"]
             and r["committed_j1_valid"] == r["nd"] and r["first_j1_choice"] == "Z_structure"
             and r["glm_latched"] is True for r in rows)
    check("A2", "S3 four arms: switches wired; rollback and valid committed J1 iff nd; first repair chosen in every "
                "arm (p=5.3% before any failure); GLM latch recorded in every arm", ok, rows=rows,
          note="order-served replay: downstream responses do not follow the committed J1, so TP recovery is "
               "verified only by the content-conditioned test_damjs_v03 N2, not here")


def a3():
    runs, rows = tmp("a3"), []
    for arm in V03_ARMS:
        rec, res, prog = run(runs, f"a3_{arm}_S4", arm, "S4")
        rows.append(dict(arm=arm, tp=res["tp"], tp_strict=res["tp_strict"],
                         rollbacks=len([x for x in prog if x.get("ev") == "node_rollback"]),
                         z_format=any(x.get("ev") == "damjs_decide" and x.get("chosen") == "Z_format" for x in prog)))
    check("A3", "S4 four arms: Z_format chosen, no rollback, TP 14 / strict 14 in every arm",
          all(r["tp"] == 14 and r["tp_strict"] == 14 and r["rollbacks"] == 0 and r["z_format"] for r in rows), rows=rows)


def a4():
    runs = tmp("a4")
    saved = dict(VR.PLANS["A"]["caps"]), dict(VR.SMOKE_CAPS)
    try:
        VR.PLANS["A"]["caps"] = dict(calls=9, tokens=450_000, yuan=0.95)
        rc = VR.main(["--plan", "A", "--mode", "replay", "--phase", "smoke", "--runs-dir", str(runs),
                      "--clock-scale", str(SCALE)])
        s = json.loads((runs / "BATCH_SUMMARY_smoke.json").read_text("utf-8"))
        led = [json.loads(l) for l in (runs / "LEDGER.jsonl").read_text().splitlines()]
        rc2 = VR.main(["--plan", "A", "--mode", "replay", "--phase", "smoke", "--runs-dir", str(runs),
                       "--clock-scale", str(SCALE)])
        s2 = json.loads((runs / "BATCH_SUMMARY_smoke.json").read_text("utf-8"))
    finally:
        VR.PLANS["A"]["caps"], _ = saved[0], None
        VR.SMOKE_CAPS.clear(); VR.SMOKE_CAPS.update(saved[1])
    check("A4", "phase caps reach the children: shared ledger; denial -> INCOMPLETE_BUDGET -> stop; relaunch refused",
          rc == 1 and s["stop"].startswith("INCOMPLETE_BUDGET") and s["ledger"]["calls"] <= 9
          and led[-1]["status"] == "INCOMPLETE_BUDGET" and rc2 == 1 and "before launching" in (s2["stop"] or ""),
          stop=s["stop"], ledger=s["ledger"], statuses=[x["status"] for x in led], relaunch_stop=s2["stop"])


def a5():
    fake_r2 = tmp("a5r2")
    (fake_r2 / "state").mkdir()
    (fake_r2 / "state" / "GLOBAL_BUDGET.json").write_text(json.dumps(dict(calls=VR.AUTH["calls"], yuan=0.0, tokens=0)))
    runs = tmp("a5")
    saved = VR.R2_RUNS
    try:
        VR.R2_RUNS = fake_r2
        caps = VR.caps_for("A", "smoke", runs)
        rc = VR.main(["--plan", "A", "--mode", "replay", "--phase", "smoke", "--runs-dir", str(runs)])
        s = json.loads((runs / "BATCH_SUMMARY_smoke.json").read_text("utf-8"))
        real_caps = None
    finally:
        VR.R2_RUNS = saved
    real_caps = VR.caps_for("A", "main", runs)
    check("A5", "authorization ceiling (shared with the R2 ledger): zero room -> no launch; real headroom leaves plan caps binding",
          caps["calls"] == 0 and rc == 1 and s["executed"] == 0 and "BUDGET_CAP_REACHED:calls" in (s["stop"] or "")
          and real_caps == VR.PLANS["A"]["caps"],
          caps_at_zero_room=caps, stop=s["stop"], caps_with_real_r2_ledger=real_caps)


def a6():
    v = R.verify_manifest(VR.MANIFEST)
    check("A6", "pilot MANIFEST: every registered component matches disk", v["ok"], n=v["n"],
          manifest_sha256=v["manifest_sha256"], mismatches=v["mismatches"])
    ids = [r for r in RES["runs"] if r["identity_ok"] is not None]
    check("A6", "every completed replay execution verified identity pre and post", ids and all(r["identity_ok"] for r in ids),
          n=len(ids))
    runs = tmp("a6")
    mf = json.loads(VR.MANIFEST.read_text("utf-8"))
    for c in mf["components"]:
        if c["role"] == "v03_mechanisms":
            c["sha256"] = "0" * 64
    bad = runs / "tampered.json"
    bad.write_text(json.dumps(mf, ensure_ascii=False), "utf-8")
    rec, res, _ = run(runs, "a6_tamper", "V0.3", "S4", manifest=bad)
    mism = [m["role"] for m in res["identity"]["pre"]["mismatches"]]
    saved = VR.MANIFEST
    try:
        VR.MANIFEST = bad
        try:
            VR.main(["--plan", "A", "--mode", "replay", "--phase", "smoke", "--runs-dir", str(runs / "b")])
            refused = False
        except SystemExit as e:
            refused = "INTEGRITY_FAIL" in str(e)
    finally:
        VR.MANIFEST = saved
    check("A6", "tampered manifest -> execution INTEGRITY_FAIL; runner refuses to start",
          mism == ["v03_mechanisms"] and (R.stop_reason(rec, R.CAPS) or "").startswith("INTEGRITY_FAIL") and refused,
          mismatches=mism, stop=R.stop_reason(rec, R.CAPS), runner_refused=refused)


def a7():
    def boom(*a, **k):
        raise RuntimeError("SAFETY_NET: real path reached during gate test")
    saved = R.load_credentials, VR.run_one
    R.load_credentials, VR.run_one = boom, boom
    gates = []
    try:
        for argv, env in ((["--plan", "A", "--mode", "real", "--phase", "smoke"], {}),
                          (["--plan", "A", "--mode", "real", "--phase", "smoke"], {"STAGE_D_REAL_CALLS_AUTHORIZED": "1"}),
                          (["--plan", "A", "--mode", "real", "--phase", "smoke"],
                           {"STAGE_D_REAL_CALLS_AUTHORIZED": "1", "DAMJS_V03_GO": "B:smoke"}),
                          (["--plan", "A", "--mode", "real", "--phase", "smoke"],
                           {"STAGE_D_REAL_CALLS_AUTHORIZED": "1", "DAMJS_V03_GO": "A:smoke"}),
                          (["--plan", "A", "--mode", "real", "--phase", "all"],
                           {"STAGE_D_REAL_CALLS_AUTHORIZED": "1", "DAMJS_V03_GO": "A:all"})):
            keep = {k: os.environ.get(k) for k in ("STAGE_D_REAL_CALLS_AUTHORIZED", "DAMJS_V03_GO")}
            for k in keep:
                os.environ.pop(k, None)
            os.environ.update(env)
            try:
                VR.main(argv + ["--runs-dir", str(tmp("a7"))])
                gates.append((" ".join(argv), env.get("DAMJS_V03_GO"), "NOT_REFUSED"))
            except SystemExit as e:
                gates.append((" ".join(argv), env.get("DAMJS_V03_GO"), str(e)[:90]))
            except RuntimeError as e:
                gates.append((" ".join(argv), env.get("DAMJS_V03_GO"),
                              "PASSED_ALL_GATES->SAFETY_NET" if "SAFETY_NET" in str(e) else f"ERR:{e}"[:90]))
            finally:
                for k, v in keep.items():
                    os.environ.pop(k, None)
                    if v is not None:
                        os.environ[k] = v
    finally:
        R.load_credentials, VR.run_one = saved
    d = tmp("a7p")
    pre = d / "prereg.md"
    pre.write_text("approved prereg\nPILOT_PLAN=A\n", "utf-8")
    mf = d / "mf.json"
    mf.write_text(json.dumps(dict(components=[dict(role="prereg_frozen", path="x", sha256=VR.sha_file(pre))])), "utf-8")
    g_ok = VR.prereg_gate("A", manifest=mf, prereg=pre)
    g_plan = VR.prereg_gate("B", manifest=mf, prereg=pre)
    pre.write_text("approved prereg\nPILOT_PLAN=A\nedited after freeze\n", "utf-8")
    g_edit = VR.prereg_gate("A", manifest=mf, prereg=pre)
    real_gate = VR.prereg_gate("A")   # the frozen, manifest-registered prereg now on disk
    check("A7", "real mode refused without authorization, with mismatched GO, and for phase=all; with ALL conditions "
                "(auth + GO=A:smoke + frozen registered prereg) the lock opens only as far as the credential step "
                "(stubbed safety net, no call); synthetic gate passes only for a registered, unedited prereg",
          all(gates[i][2].startswith("REFUSED") for i in (0, 1, 2, 4))
          and gates[3][2] == "PASSED_ALL_GATES->SAFETY_NET" and real_gate is None
          and g_ok is None and g_plan and g_edit, gates=gates, real_gate=real_gate, gate_ok=g_ok,
          gate_wrong_plan=g_plan, gate_edited=g_edit)


def a8():
    v = lambda: '{"a": 1}'
    good = [dict(ev="node_end", node="J1", ok=True, output=v()),
            dict(ev="node_invalidate", nodes=["J1"]), dict(ev="node_end", node="J1", ok=True, output=v())]
    bad = [dict(ev="node_end", node="J1", ok=True, output=v()),
           dict(ev="node_invalidate", nodes=["J1"]), dict(ev="node_end", node="J1", ok=True, output="")]
    benign = [dict(ev="node_end", node="J1", ok=True, output=""),
              dict(ev="node_invalidate", nodes=["J1"]), dict(ev="node_end", node="J1", ok=True, output="")]
    runs = tmp("a8")
    (runs / "progress").mkdir()
    (runs / "progress" / "t.jsonl.out").write_text('Traceback (most recent call last):\n  File ".../damjs_v03.py"\n')
    check("A8", "stop detectors: C1 violation caught; valid recommit and invalid-v1 cases not flagged; V0.3 traceback caught",
          VR.c1_violation(bad) == "J1" and VR.c1_violation(good) is None and VR.c1_violation(benign) is None
          and (VR.v03_stop(runs, dict(tag="t", arm="R2")) or "").startswith("V03_PATH_EXCEPTION"))


def a9():
    check("A9", "zero network attempts across every replay execution", sum(r["net"] for r in RES["runs"]) == 0,
          executions=len(RES["runs"]))
    captured = {}

    def fake(**kw):
        captured.update(kw["env"])
        return dict(status="CHILD_FAILED_rc9", elapsed=0.0)
    saved = R.run_isolated
    os.environ["STAGE_D_GLM_KEY"] = os.environ["DEEPSEEK_API_KEY"] = "dummy-not-a-key"
    try:
        R.run_isolated = fake
        VR.run_one(tag="a9", arm="V0.3", scenario="S3", rep=1, deadline=240.0, mode="replay", runs_dir=tmp("a9"),
                   caps=dict(calls=9, tokens=1, yuan=0.1), manifest=VR.MANIFEST, replay_src=VR.REPLAY_SRC["S3"],
                   clock_scale=SCALE)
    finally:
        R.run_isolated = saved
        os.environ.pop("STAGE_D_GLM_KEY", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)
    check("A9", "replay children receive no credential variables and run the pilot child",
          "STAGE_D_GLM_KEY" not in captured and "DEEPSEEK_API_KEY" not in captured
          and captured.get("APILOT_BATCH") == VR.BATCH)


def a10():
    """Node-level scope through the real executor path: only directly recovered nodes are ever armed."""
    rows = []
    for r in RES["runs"]:
        pass
    runs = tmp("a10")
    rec, res, prog = run(runs, "a10_V0.3_S3", "V0.3", "S3")
    rb_nodes = [x["node"] for x in prog if x.get("ev") == "node_rollback"]
    direct = {x["target"] for x in prog if x.get("ev") == "node_invalidate"}
    invalidated = {n for x in prog if x.get("ev") == "node_invalidate" for n in x["nodes"]}
    check("A10", "node-level protection on the executor path: every rollback is on a directly recovered node; "
                 "no downstream-invalidated node is ever rolled back",
          rb_nodes and set(rb_nodes) <= direct and not (set(rb_nodes) & (invalidated - direct)),
          rollback_nodes=rb_nodes, direct_targets=sorted(direct), downstream_invalidated=sorted(invalidated - direct))


def a11():
    """Every EV-evaluated candidate (kept or excluded) carries the frozen record (p, n_eff, CI95, mu, L, EV)."""
    need = ("p_fail", "n_eff", "ci95", "mu", "L", "ev")
    runs = tmp("a11")
    missing, seen = [], 0
    for arm in ("EV-only", "V0.3"):
        rec, res, prog = run(runs, f"a11_{arm}_S3", arm, "S3")
        for x in prog:
            if x.get("ev") != "damjs_decide":
                continue
            for c in x.get("candidates", []):
                if c["kind"] in ("Z_structure", "R"):
                    seen += 1
                    missing += [(arm, c["kind"], k) for k in need if k not in c]
            for e in x.get("excluded", []):
                if str(e.get("why", "")).startswith("EV_gate"):
                    seen += 1
                    missing += [(arm, e["kind"], k) for k in ("p", "n_eff", "ci95", "mu", "L", "ev")
                                if k not in (e.get("ev_record") or {})]
    check("A11", "decision audit: every EV-evaluated candidate records (p_hat, n_eff, CI95, mu_hat, L_hat, EV)",
          seen > 0 and not missing, evaluated=seen, missing=missing[:10])


V03_ARMS = {"R2": (False, False), "ND-only": (True, False), "EV-only": (False, True), "V0.3": (True, True)}


def main():
    t0 = time.time()
    a0(); a1(); a2(); a3(); a4(); a5(); a6(); a7(); a8(); a9(); a10(); a11()
    n = sum(t["ok"] for t in RES["tests"])
    RES["summary"] = dict(passed=n, failed=len(RES["tests"]) - n, executions=len(RES["runs"]),
                          wall_s=round(time.time() - t0, 1), manifest_sha256=VR.sha_file(VR.MANIFEST))
    (HERE / "PILOT_ACCEPTANCE_RESULTS.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), "utf-8")
    print(f"\nRESULT: {n} passed, {len(RES['tests']) - n} failed ({len(RES['runs'])} replay executions)")
    return 0 if n == len(RES["tests"]) else 1


if __name__ == "__main__":
    sys.exit(main())
