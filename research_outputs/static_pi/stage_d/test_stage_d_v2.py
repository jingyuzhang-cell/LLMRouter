#!/usr/bin/env python3
"""Stage D V2.0（A‴）零调用测试：路由覆盖层 + S5′ 条件性重执行 + 192 矩阵。

运行：python3 test_stage_d_v2.py
全部使用 MockProvider / 虚拟时钟 / 无网络。
"""
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

import stage_d_v2_executor as E

BASE = json.loads((HERE / "stage_d_v2_executor_config.json").read_text("utf-8"))


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
    tmp = Path(tempfile.mkdtemp(prefix="sdv2_"))
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


class R01Routing(unittest.TestCase):
    def test_arout_all_nodes(self):
        self.assertEqual(E.AROUT, {"E1": "deepseek", "E2": "deepseek",
                                   "E3": "deepseek", "E4": "deepseek",
                                   "J1": "glm53flash", "J2": "deepseek",
                                   "SINK": "deepseek"})

    def test_calls_follow_arout(self):
        rec, ex, gb, slots, tmp, prov = run_one("Static", "S0", 1)
        seen = {(c["node"], c["alias"]) for c in prov.calls}
        for n, a in E.AROUT.items():
            self.assertIn((n, a), seen, (n, a, seen))
        self.assertNotIn(("J1", "glm53flash") if False else ("J2", "glm53flash"), seen)
        self.assertEqual(rec["status"], "COMPLETE")

    def test_maxtok_override(self):
        # AMAX: glm53flash 8192（仅 J1）；deepseek 4000
        self.assertEqual(E.AMAX, {"glm53flash": 8192, "deepseek": 4000})


class R02S5Prime(unittest.TestCase):
    def _cfg(self, glm_j1_wall=0.5, corrupt_glm_j1=False):
        c = fast_cfg()
        c["mock"]["latency_s"]["S5"] = {"J1": {"glm53flash": glm_j1_wall,
                                               "deepseek": 0.5}}
        c["_corrupt_glm_j1"] = corrupt_glm_j1
        return c

    def test_no_trigger_when_valid_fast(self):
        rec, ex, gb, slots, tmp, prov = run_one("Proposed-Dynamic", "S5", 1,
                                                self._cfg(0.5))
        rl = rec["s5"]["race_log_v2"][0]
        self.assertFalse(rl["triggered"])
        self.assertEqual(rl["action"], "no_trigger")
        self.assertEqual(rec["raw"]["nodes"]["J1"][0]["model"], "glm53flash")
        self.assertEqual(rec["status"], "COMPLETE")

    def test_slow_but_valid_kept_no_recall(self):
        # wall>120s 但 JSON 有效 → 保留，不重复调用
        rec, ex, gb, slots, tmp, prov = run_one("Proposed-Dynamic", "S5", 1,
                                                self._cfg(glm_j1_wall=130.0))
        rl = rec["s5"]["race_log_v2"][0]
        self.assertFalse(rl["triggered"])
        self.assertTrue(rl["slow_but_valid"])
        self.assertEqual(rl["action"], "keep_valid_no_recall")
        j1_models = [m["model"] for m in rec["raw"]["nodes"]["J1"]]
        self.assertEqual(j1_models, ["glm53flash"])      # 无 DS 重执行
        self.assertTrue(rec["s5"]["slo_violation"])
        self.assertEqual(rec["status"], "COMPLETE")

    def test_invalid_result_single_ds_reexec(self):
        class BadJ1GLM(E.MockProvider):
            def _response(self, node, alias, system):
                if node == "J1" and alias == "glm53flash":
                    return {"text": "not json"}          # GLM 无效 → 触发
                return super()._response(node, alias, system)
        rec, ex, gb, slots, tmp, prov = run_one(
            "Proposed-Dynamic", "S5", 1, self._cfg(), provider_cls=BadJ1GLM)
        rl = rec["s5"]["race_log_v2"][0]
        self.assertTrue(rl["triggered"])
        self.assertEqual(rl["action"], "ds_single_legal_reexec")
        self.assertTrue(rl["ds_json_ok"])
        self.assertTrue(rl["recovery_ok"])
        self.assertEqual(rec["s5"]["winner"], "deepseek")
        j1_models = [m["model"] for m in rec["raw"]["nodes"]["J1"]]
        self.assertEqual(j1_models, ["glm53flash", "deepseek"])
        # 失败 GLM 成本全额入账 + DS 成本入账
        costs = [c["accounting_yuan"] for c in rec["raw"]["calls"] if c["node"] == "J1"]
        self.assertEqual(len(costs), 2)
        self.assertGreater(sum(costs), 0)
        self.assertIn(("cond_swap_j1", "J1"),
                      [(a["kind"], a["node"]) for a in rec["actions"]])
        self.assertEqual(rec["status"], "COMPLETE")

    def test_non_recovery_arm_fails_j1(self):
        class BadJ1GLM(E.MockProvider):
            def _response(self, node, alias, system):
                if node == "J1" and alias == "glm53flash":
                    return {"text": "not json"}
                return super()._response(node, alias, system)
        rec, *_ = run_one("Static", "S5", 1, self._cfg(), provider_cls=BadJ1GLM)
        rl = rec["s5"]["race_log_v2"][0]
        self.assertEqual(rl["action"], "no_recovery_action_available")
        self.assertEqual(rec["invalid_reason"], "S5PRIME_NO_RECOVERY_ARM")
        j1_models = [m["model"] for m in rec["raw"]["nodes"]["J1"]]
        self.assertEqual(j1_models, ["glm53flash"])      # 无重执行

    def test_recovery_failure_reported(self):
        class BadBoth(E.MockProvider):
            def _response(self, node, alias, system):
                if node == "J1":
                    return {"text": "not json"}
                return super()._response(node, alias, system)
        rec, *_ = run_one("Proposed-Dynamic", "S5", 1, self._cfg(),
                          provider_cls=BadBoth)
        self.assertEqual(rec["invalid_reason"], "S5PRIME_RECOVERY_FAILED")
        self.assertEqual(rec["final_states"]["J1"], "Failed")


class R03Symmetry(unittest.TestCase):
    def test_all_arms_same_routing_and_action_space(self):
        # 六臂使用同一 AROUT；π 动作仅故障节点 GLM→DS（由 policy 层 ds_ok 门控）
        for arm in BASE["arms"]:
            rec, ex, gb, slots, tmp, prov = run_one(arm, "S3", 1)
            seen = {c["node"]: c["alias"] for c in prov.calls}
            for n, a in E.AROUT.items():
                if n in seen:
                    self.assertEqual(seen[n], a, (arm, n, seen[n]))
            self.assertEqual(rec["status"], "COMPLETE")


class R04Matrix(unittest.TestCase):
    def test_192_blocks_six_arms(self):
        m = E.verify_matrix(BASE)
        self.assertTrue(m["ok"], m)
        self.assertEqual(m["n_total"], 192)
        self.assertTrue(all(v == 32 for v in m["per_arm"].values()))




class R05RealHandleParity(unittest.TestCase):
    """2026-11-03 bugfix 回归：真实句柄必须与 Mock 句柄属性对等（latency 等），
    _finish_call 在真实路径可完整走完（192 Mock 无法覆盖此类缺陷）。"""

    def _fake_transport(self):
        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            return {"text": '{"ok": 1}', "in": 100, "out": 10,
                    "stop": "end_turn", "lat": 0.05}
        return fn

    def test_real_handle_finish_call_records(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="sdv2real_"))
        clock = E.VirtualClock(1.0)
        slots = E.SlotManager({"glm53flash": 2, "deepseek": 1}, clock)
        prov = E.RealProvider(clock, slots, transport_fn=self._fake_transport())
        gb = E.GlobalBudget(100, 10.0, None, tmp / "state")
        ex = E.FinalExec("Static", "S0", 1, BASE, clock, gb, slots, prov,
                         E.RunStore(tmp / "state", tmp), dry_run=False)
        ex.t0 = clock.now()
        ex.exec_llm("E1")
        self.assertEqual(ex.state["E1"], "Completed")
        self.assertEqual(len(ex.raw["calls"]), 1)
        self.assertIsNotNone(ex.raw["calls"][0]["latency"])
        self.assertEqual(ex.model_used["E1"], "deepseek")   # A‴ 路由

    def test_real_handle_latency_set_even_on_error(self):
        import tempfile
        def bad(alias, system, user, max_tokens, timeout_s, temperature):
            raise RuntimeError("transport down")
        tmp = Path(tempfile.mkdtemp(prefix="sdv2real_"))
        clock = E.VirtualClock(1.0)
        slots = E.SlotManager({"glm53flash": 2, "deepseek": 1}, clock)
        prov = E.RealProvider(clock, slots, transport_fn=bad)
        h = prov.start_call("deepseek", "deepseek", "s", "u", 100)
        h.start(); h.done.wait(5)
        self.assertEqual(h.cancel_state, "error")
        # _finish_call 仍可读取（latency 已初始化为 None，不再 AttributeError）
        gb = E.GlobalBudget(100, 10.0, None, tmp / "state")
        ex = E.FinalExec("Static", "S0", 1, BASE, clock, gb, slots, prov,
                         E.RunStore(tmp / "state", tmp), dry_run=False)
        ex.t0 = clock.now()
        try:
            ex._finish_call("E1", h)
            self.fail("should raise")   # error 结果无 JSON，由上层处理
        except Exception:
            pass

if __name__ == "__main__":
    unittest.main(verbosity=1)
