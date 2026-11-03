#!/usr/bin/env python3
"""Stage B V3 候选零调用测试：B-1 契约守卫 + B-2 真实换模路由。"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

import stage_d_v3_executor as E

BASE = json.loads((HERE / "stage_d_v3_executor_config.json").read_text("utf-8"))


def cfg(**over):
    c = copy.deepcopy(BASE)
    for k, v in over.items():
        c[k] = v
    return c


def fast_cfg(**over):
    c = cfg(**over)
    c["mock"]["scale"] = 1000
    c["mock"]["latency_s"]["default"] = {n: 0.5 for n in
                                         ("E1", "E2", "E3", "E4", "J1", "J2", "SINK")}
    c["mock"]["overhead_s"] = 0
    return c


def run_one(arm, sc, rep, c=None, provider_cls=None, settle=True):
    c = copy.deepcopy(c or fast_cfg())
    tmp = Path(tempfile.mkdtemp(prefix="sdv3_"))
    clock = E.VirtualClock(c["mock"]["scale"])
    gb = E.GlobalBudget(c["global"]["calls"], c["global"]["yuan"],
                        c["global"].get("tokens"), tmp / "state")
    slots = E.SlotManager(c["slots"], clock)
    store = E.RunStore(tmp / "state", tmp)
    P = provider_cls or E.MockProvider
    prov = P(clock, slots, c, sc, rep)
    ex = E.FinalExec(arm, sc, rep, c, clock, gb, slots, prov, store, dry_run=True)
    rec = ex.run()
    if settle:
        ex.settle()
        rec = ex.recommit_with_settlement() or rec
    return rec, ex, gb, slots, tmp, prov


class G01ContractCheck(unittest.TestCase):
    def test_healthy_output_passes(self):
        self.assertIsNone(E.output_contract_check(
            "J1", {"text": '{"judgments":[]}', "in": 10, "out": 5}, {"judgments": []}))
        self.assertIsNone(E.output_contract_check(
            "SINK", {"text": '{"answers":[]}', "in": 10, "out": 5}, {"answers": []}))

    def test_empty_text_fails(self):
        self.assertEqual(E.output_contract_check(
            "J1", {"text": "", "in": 5, "out": 0}, None), "empty_text")

    def test_transport_error_fails(self):
        self.assertEqual(E.output_contract_check(
            "J1", {"text": "", "in": 0, "out": 0, "error": "x"}, None), "transport_error")

    def test_json_invalid_fails(self):
        self.assertEqual(E.output_contract_check(
            "J1", {"text": "not json", "in": 5, "out": 3}, None), "json_invalid")

    def test_schema_invalid_fails(self):
        self.assertEqual(E.output_contract_check(
            "J1", {"text": '{"other":1}', "in": 5, "out": 3}, {"other": 1}),
            "schema_invalid_missing_judgments")


class G02GuardBehavior(unittest.TestCase):
    def _bad(self, node, kind="empty"):
        class Bad(E.MockProvider):
            def _response(self, n, alias, system):
                if n == node and alias == "glm53flash":
                    return {"text": ""} if kind == "empty" else {"text": "not json"}
                return super()._response(n, alias, system)
        return Bad

    def test_guard_empty_j1_fails_node_not_completed_empty(self):
        rec, ex, gb, slots, tmp, prov = run_one("Static", "S3", 1,
                                                provider_cls=self._bad("J1"))
        # Static 无恢复动作：J1 两次尝试均空 → Failed，且 outputs 不含空文本下游
        self.assertEqual(rec["final_states"]["J1"], "Failed")
        reasons = [g["reason"] for g in rec["guard_log"]]
        self.assertTrue(all(r == "empty_text" for r in reasons), reasons)
        self.assertEqual(len(reasons), 2)            # attempt1+2
        self.assertNotEqual(rec["status"], "COMPLETE")
        # 关键：J2 不应消费空 J1（B-1 前 J1 曾以空文本 Completed 并流向下游）
        j2_calls = [c for c in rec["raw"]["calls"] if c["node"] == "J2"]
        self.assertEqual(len(j2_calls), 0)

    def test_guard_recovery_via_retry_arm(self):
        # Simple 臂在 attempt 失败后由 policy 触发 retry；mock 中 GLM 恒坏 → 最终 Failed
        rec, *_ = run_one("Simple-Dynamic", "S3", 1, provider_cls=self._bad("J1"))
        self.assertEqual(rec["final_states"]["J1"], "Failed")
        self.assertTrue(rec["guard_log"])

    def test_guard_schema_invalid(self):
        class BadSchema(E.MockProvider):
            def _response(self, n, alias, system):
                if n == "SINK":
                    return {"text": '{"something": 1}'}
                return super()._response(n, alias, system)
        rec, *_ = run_one("Static", "S0", 1, provider_cls=BadSchema)
        self.assertEqual(rec["final_states"]["SINK"], "Failed")
        self.assertIn("schema_invalid", rec["guard_log"][0]["reason"])

    def test_healthy_execution_unchanged(self):
        rec, ex, gb, slots, tmp, prov = run_one("Proposed-Dynamic", "S3", 1)
        self.assertEqual(rec["status"], "COMPLETE")
        self.assertEqual(rec["guard_log"], [])


class G03SwapRouting(unittest.TestCase):
    def test_j1_swap_actually_routes_to_deepseek(self):
        # S3 下 π 臂对 J1 结构异常触发 swap → 重跑必须发生在 deepseek（真实换模）
        rec, ex, gb, slots, tmp, prov = run_one("π-only", "S3", 1)
        j1_aliases = [c["alias"] for c in prov.calls if c["node"] == "J1"]
        swapped = ("swap", "J1") in [(a["kind"], a["node"]) for a in rec["actions"]]
        if swapped:
            self.assertIn("deepseek", j1_aliases, j1_aliases)
            self.assertEqual(rec["model_override"].get("J1"), "deepseek")

    def test_illegal_swap_denied_no_call(self):
        # E/J2/SINK 的 swap 被拒绝：不重跑、记录拒绝原因
        rec, ex, gb, slots, tmp, prov = run_one("Proposed-Dynamic", "S3", 1)
        denies = [a for a in rec["actions"]
                  if a["kind"] == "swap_denied_no_legal_alternative"]
        for d in denies:
            self.assertNotIn(d["node"], ("J1",))
        # 拒绝不产生额外调用：被拒节点在该执行内的调用别名不因 swap 改变
        for n in ("E2", "J2", "SINK"):
            aliases = {c["alias"] for c in prov.calls if c["node"] == n}
            self.assertTrue(aliases <= {"deepseek"}, (n, aliases))


class G04Regression(unittest.TestCase):
    def test_matrix_192(self):
        m = E.verify_matrix(BASE)
        self.assertTrue(m["ok"])
        self.assertEqual(m["n_total"], 192)

    def test_arout_unchanged(self):
        self.assertEqual(E.AROUT["J1"], "glm53flash")
        self.assertEqual(E.AROUT["J2"], "deepseek")


if __name__ == "__main__":
    unittest.main(verbosity=1)
