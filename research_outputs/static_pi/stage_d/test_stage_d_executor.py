#!/usr/bin/env python3
"""Stage D 终局执行器零调用测试（20 项；Mock Provider / 虚拟时钟 / 无网络）。

运行：python3 test_stage_d_executor.py
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

import stage_d_executor as E

BASE = json.loads((HERE / "stage_d_executor_config.json").read_text("utf-8"))


def cfg(**over):
    c = copy.deepcopy(BASE)
    for k, v in over.items():
        c[k] = v
    return c


def fast_cfg(**over):
    c = cfg(**over)
    c["mock"]["scale"] = 1000
    c["mock"]["latency_s"]["default"] = {
        "E1": 1.0, "E2": 1.0, "E3": 1.0, "E4": 1.0,
        "J1": 1.0, "J2": 1.0, "SINK": 1.0}
    c["mock"]["overhead_s"] = 0
    return c


def run_one(arm, sc, rep, c=None, cancel_effective=True, provider_cls=None):
    c = copy.deepcopy(c or fast_cfg())
    c["s5"]["cancel_effective"] = cancel_effective
    tmp = Path(tempfile.mkdtemp(prefix="sd_exec_"))
    clock = E.VirtualClock(c["mock"]["scale"])
    gb = E.GlobalBudget(c["global"]["calls"], c["global"]["yuan"],
                        c["global"].get("tokens"), tmp / "state")
    slots = E.SlotManager(c["slots"], clock)
    store = E.RunStore(tmp / "state", tmp)
    P = provider_cls or E.MockProvider
    prov = P(clock, slots, c, sc, rep)
    ex = E.FinalExec(arm, sc, rep, c, clock, gb, slots, prov, store, dry_run=True)
    rec = ex.run()
    return rec, ex, gb, slots, tmp


class T01Matrix(unittest.TestCase):
    def test_192_blocks_six_arms_scenarios(self):
        m = E.verify_matrix(BASE)
        self.assertTrue(m["ok"], m)
        self.assertEqual(m["n_total"], 192)
        self.assertEqual(m["n_unique"], 192)
        self.assertTrue(all(v == 32 for v in m["per_arm"].values()))
        self.assertEqual(m["per_scenario_total"]["S5"], 48)
        self.assertEqual(m["per_scenario_total"]["S0"], 12)


class T02S5Race(unittest.TestCase):
    def test_glm_first_ds_wins_and_slo_wait(self):
        rec, ex, gb, slots, tmp = run_one("Proposed-Dynamic", "S5", 1)
        self.assertTrue(rec["s5"]["slo_violation"])
        self.assertTrue(rec["s5"]["race_triggered"])
        self.assertEqual(rec["s5"]["winner"], "deepseek")
        r = rec["race"][0]
        self.assertGreaterEqual(r["in_flight_at_trigger"], 9.4)
        self.assertTrue(r["loser_cancelled"])
        self.assertIn(("race_swap", "J2"), [(a["kind"], a["node"]) for a in rec["actions"]])

    def test_glm_finishes_before_slo_no_race(self):
        c = fast_cfg()
        c["mock"]["latency_s"]["S5"] = {"J2": {"glm53flash": 5.0, "deepseek": 6.3}}
        rec, ex, gb, slots, tmp = run_one("Proposed-Dynamic", "S5", 3, c)
        self.assertFalse(rec["s5"]["race_triggered"])
        self.assertIsNone(rec["s5"]["winner"])
        self.assertEqual(rec["raw"]["nodes"]["J2"][0]["model"], "glm53flash")

    def test_non_race_arm_simple(self):
        rec, ex, gb, slots, tmp = run_one("Simple-Dynamic", "S5", 1)
        self.assertFalse(rec["s5"]["race_triggered"])
        self.assertIsNone(rec["s5"]["winner"])
        self.assertNotIn("race_swap", [a["kind"] for a in rec["actions"]])


class T03S5Late(unittest.TestCase):
    def test_late_response_cost_counted(self):
        rec, ex, gb, slots, tmp = run_one("Proposed-Dynamic", "S5", 2,
                                          cancel_effective=False)
        self.assertTrue(rec["s5"]["late"])
        self.assertEqual(rec["s5"]["late_calls"], 1)
        self.assertGreater(rec["s5"]["late_cost_yuan"], 0)
        self.assertTrue(rec["race"][0]["loser_late"])


class T04Slots(unittest.TestCase):
    def test_no_overcommit(self):
        rec, ex, gb, slots, tmp = run_one("Proposed-Dynamic", "S5", 1)
        self.assertLessEqual(rec["slots"]["max_seen"]["glm53flash"], 2)
        self.assertLessEqual(rec["slots"]["max_seen"]["deepseek"], 1)


class T05Budget(unittest.TestCase):
    def test_per_exec_call_cap(self):
        c = fast_cfg(per_exec={"calls": 1, "yuan": 0.18})
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_BUDGET")
        self.assertLessEqual(rec["calls"], 1)

    def test_global_call_cap(self):
        c = fast_cfg(**{"global": {"calls": 1, "yuan": 34.56, "tokens": None}})
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_BUDGET")
        self.assertLessEqual(gb.calls, 1)

    def test_per_exec_cash_cap(self):
        c = fast_cfg(per_exec={"calls": 14, "yuan": 1e-12})
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_BUDGET")

    def test_global_cash_cap(self):
        c = fast_cfg(**{"global": {"calls": 2688, "yuan": 1e-12, "tokens": None}})
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_BUDGET")

    def test_token_cap(self):
        c = fast_cfg(**{"global": {"calls": 2688, "yuan": 34.56, "tokens": 10}})
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_BUDGET")
        self.assertGreater(gb.denied, 0)


class T06Deadline(unittest.TestCase):
    def test_deadline_hard_stop(self):
        c = fast_cfg(deadline_s={"default": 0.1, "S5": 90})
        c["mock"]["latency_s"]["default"] = {
            "E1": 100, "E2": 100, "E3": 100, "E4": 100,
            "J1": 100, "J2": 100, "SINK": 100}
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_DEADLINE")
        self.assertFalse(rec["on_time"])


class T07Resume(unittest.TestCase):
    def test_store_skips_completed(self):
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1)
        store = E.RunStore(tmp / "state", tmp)
        self.assertIsNotNone(store.completed(rec["exec_id"]))
        self.assertEqual(store.completed(rec["exec_id"])["exec_id"], rec["exec_id"])

    def test_no_double_cost_on_resume(self):
        out = Path(tempfile.mkdtemp(prefix="sd_resume_"))
        cpath = out / "cfg.json"
        cpath.write_text(json.dumps(fast_cfg()), "utf-8")
        r1 = subprocess.run([sys.executable, str(HERE / "stage_d_executor.py"),
                             "run", "--config", str(cpath), "--out", str(out), "--limit", "1"],
                            capture_output=True, text=True, timeout=120)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        b1 = json.loads((out / "state" / "GLOBAL_BUDGET.json").read_text())
        r2 = subprocess.run([sys.executable, str(HERE / "stage_d_executor.py"),
                             "run", "--config", str(cpath), "--out", str(out), "--limit", "2"],
                            capture_output=True, text=True, timeout=120)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("skipped=1", r2.stdout)
        b2 = json.loads((out / "state" / "GLOBAL_BUDGET.json").read_text())
        recs = [json.loads(p.read_text()) for p in out.glob("*.json") if p.name != "FINAL_RUNS.json"]
        recs = [r for r in recs if "exec_id" in r]
        self.assertEqual(b2["calls"], sum(r["calls"] for r in recs))


class T08AnomalyRawScore(unittest.TestCase):
    class FailingProvider(E.MockProvider):
        def start_call(self, *a, **k):
            raise RuntimeError("MOCK_PROVIDER_FAIL")

    def test_anomaly_recorded(self):
        rec, ex, gb, slots, tmp = run_one("Static", "S0", 1,
                                          provider_cls=self.FailingProvider)
        self.assertTrue(rec["anomalies"])
        self.assertIn(rec["status"], ("INCOMPLETE_NO_RECOVERY", "INCOMPLETE_DEADLINE"))

    def test_raw_and_score_separated(self):
        rec, ex, gb, slots, tmp = run_one("Proposed-Dynamic", "S4", 1)
        self.assertIn("raw", rec)
        self.assertIn("nodes", rec["raw"])
        self.assertIn("score", rec)
        self.assertIn("tp", rec["score"])


class T09AnalysisInput(unittest.TestCase):
    def test_build_and_run_analysis(self):
        out = Path(tempfile.mkdtemp(prefix="sd_analysis_"))
        for sc in ("S3", "S4"):
            for rep in range(1, 9):
                for arm, tp in (("Proposed-Dynamic", 12), ("Simple-Dynamic", 10)):
                    rec = {"exec_id": f"{arm}|{sc}|r{rep}", "arm": arm,
                           "scenario": sc, "rep": rep, "tp": tp,
                           "status": "COMPLETE", "score": {"tp": tp}}
                    (out / f"{arm}__{sc}__r{rep}.json").write_text(
                        json.dumps(rec, ensure_ascii=False), "utf-8")
        p = E.build_analysis_input(out)
        self.assertTrue(p.exists())
        r = subprocess.run([sys.executable, str(HERE / "stage_d_final_analysis.py"), str(p)],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("main_test", r.stdout)


class T10NoNetwork(unittest.TestCase):
    def test_mock_never_calls_transport(self):
        import transport
        with mock.patch.object(transport, "call_model",
                               side_effect=AssertionError("network call attempted")):
            rec, ex, gb, slots, tmp = run_one("Static", "S0", 1)
        self.assertEqual(rec["status"], "COMPLETE")


class T11FullDryRun(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("STAGE_D_FULL_DRYRUN") == "1",
                         "set STAGE_D_FULL_DRYRUN=1 for the 192-block run")
    def test_full_192(self):
        out = Path(tempfile.mkdtemp(prefix="sd_full_"))
        cpath = out / "cfg.json"
        cpath.write_text(json.dumps(fast_cfg()), "utf-8")
        r = subprocess.run([sys.executable, str(HERE / "stage_d_executor.py"),
                            "run", "--config", str(cpath), "--out", str(out)],
                           capture_output=True, text=True, timeout=900)
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = [json.loads(p.read_text()) for p in out.glob("*.json")
                if p.name != "FINAL_RUNS.json"]
        recs = [x for x in recs if "exec_id" in x]
        self.assertEqual(len(recs), 192)
        self.assertEqual(len({x["exec_id"] for x in recs}), 192)


if __name__ == "__main__":
    unittest.main(verbosity=2)
