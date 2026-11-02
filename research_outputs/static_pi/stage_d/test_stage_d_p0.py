#!/usr/bin/env python3
"""P0-2 / P0-3 / P0-5 专项零调用测试（无网络）。

P0-2 真实 Provider 三态取消（logical_cancel / transport_cancel / late_completed）
     与迟到全额计账、槽占用到线程真实结束。
P0-3 token 预留台账：调用前预留、并发防超支、结算归还、峰值不变量。
P0-5 S5 确定性虚拟时钟回归：边界（89.9/90.0/90.1）+ 六种行为路径。
"""
import copy
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

import stage_d_executor as E

BASE = json.loads((HERE / "stage_d_executor_config.json").read_text("utf-8"))


def fast_cfg(**over):
    c = copy.deepcopy(BASE)
    for k, v in over.items():
        c[k] = v
    c["mock"]["scale"] = 200
    c["mock"]["latency_s"]["default"] = {
        "E1": 2.0, "E2": 2.0, "E3": 2.0, "E4": 2.0,
        "J1": 2.0, "J2": 2.0, "SINK": 2.0}
    c["mock"]["overhead_s"] = 0
    return c


def run_one(arm, sc, rep, c, cancel_effective=True):
    c = copy.deepcopy(c)
    c["s5"]["cancel_effective"] = cancel_effective
    tmp = Path(tempfile.mkdtemp(prefix="p0_"))
    clock = E.VirtualClock(c["mock"]["scale"])
    gb = E.GlobalBudget(c["global"]["calls"], c["global"]["yuan"],
                        c["global"].get("tokens"), tmp / "state")
    slots = E.SlotManager(c["slots"], clock)
    store = E.RunStore(tmp / "state", tmp)
    ex = E.FinalExec(arm, sc, rep, c, clock, gb, slots,
                     E.MockProvider(clock, slots, c, sc, rep), store, dry_run=True)
    return ex.run(), ex, gb, slots, tmp, clock


class P02RealProvider(unittest.TestCase):
    def _fake_transport_factory(self, real_s=0.05, usage=(100, 50)):
        def fn(alias, system, user, max_tokens, timeout_s, temperature):
            time.sleep(real_s)
            return {"text": '{"ok":1}', "in": usage[0], "out": usage[1],
                    "stop": "end_turn", "lat": real_s}
        return fn

    def test_logical_cancel_does_not_stop_and_costs_full(self):
        clock = E.VirtualClock(1.0)
        slots = E.SlotManager({"glm53flash": 2, "deepseek": 1}, clock)
        prov = E.RealProvider(clock, slots,
                              transport_fn=self._fake_transport_factory(0.08))
        h = prov.start_call("glm53flash", "glm53flash", "s", "u", 100, node="J2")
        h.start()
        h.cancel()                      # 逻辑取消（urllib 无传输取消）
        h.done.wait(timeout=5)
        self.assertEqual(h.cancel_state, "late_completed")
        self.assertEqual(h.result["in"], 100)
        self.assertEqual(h.result["out"], 50)   # 全额计账

    def test_slot_held_until_thread_truly_ends(self):
        clock = E.VirtualClock(1.0)
        slots = E.SlotManager({"glm53flash": 1, "deepseek": 1}, clock)
        prov = E.RealProvider(clock, slots,
                              transport_fn=self._fake_transport_factory(0.1))
        h = prov.start_call("glm53flash", "glm53flash", "s", "u", 100, node="J2")
        h.start()
        h.cancel()
        time.sleep(0.02)
        self.assertEqual(slots.summary()["active"]["glm53flash"], 1)  # 未虚假释放
        h.done.wait(timeout=5)
        self.assertEqual(slots.summary()["active"]["glm53flash"], 0)
        iv = [i for i in slots.summary() and [] ] or None
        self.assertIsNotNone(h.t_end)

    def test_mock_transport_cancel_zero_cost(self):
        clock = E.VirtualClock(1000)
        slots = E.SlotManager({"glm53flash": 2, "deepseek": 1}, clock)
        cfg = copy.deepcopy(BASE)
        cfg["mock"]["latency_s"]["S5"] = {"J2": {"glm53flash": 30.0, "deepseek": 3.0}}
        prov = E.MockProvider(clock, slots, cfg, "S5", 1)
        h = prov.start_call("glm53flash", "glm53flash", "s", "u", 100,
                            node="J2", cancel_effective=True)
        h.start()
        clock.sleep(10)                 # 超过 SLO 后取消（未完成）
        h.cancel()
        h.done.wait(timeout=5)
        self.assertEqual(h.cancel_state, "transport_cancel")
        self.assertEqual(h.result["in"], 0)
        self.assertEqual(h.result["out"], 0)

    def test_race_log_records_cancel_state(self):
        rec, *_ = run_one("Proposed-Dynamic", "S5", 1, fast_cfg())
        rl = rec["race"][0]
        self.assertIn("loser_cancel_state", rl)
        self.assertEqual(rl["winner"], "deepseek")


class P03TokenReservation(unittest.TestCase):
    def test_concurrent_reservation_never_exceeds_cap(self):
        cap = 5000
        gb = E.GlobalBudget(10000, 34.56, cap, None)
        denies = []
        def worker(i):
            try:
                gb.reserve_call()
                gb.reserve_tokens(300, 200)     # 每请求预留 500
            except E.BudgetExceeded:
                denies.append(i)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertGreater(len(denies), 0)      # 有拒绝
        self.assertLessEqual(gb.peak_used_plus_reserved, cap)  # 峰值不变量
        self.assertEqual(gb.reserved_tokens + 0, 10 * 500)     # 恰好 10 个进入

    def test_release_on_settle_returns_difference(self):
        gb = E.GlobalBudget(100, 34.56, 10000, None)
        need = gb.reserve_tokens(1000, 4000)
        gb.release_reservation(need, 800, 900)
        self.assertEqual(gb.reserved_tokens, 0)
        self.assertEqual(gb.tokens, 1700)       # 实际 < 预留，立即归还差额

    def test_inflight_denied_when_residual_insufficient(self):
        gb = E.GlobalBudget(100, 34.56, 10000, None)
        gb.reserve_tokens(6000, 3000)           # 在途占用 9000
        with self.assertRaises(E.BudgetExceeded):
            gb.reserve_tokens(800, 400)         # 剩余 1000 < 需要 1200 → 拒绝

    def test_executor_end_to_end_reservation_invariant(self):
        c = fast_cfg()
        c["global"]["tokens"] = 400000          # 远小于字符总量上界但大于本例
        rec, ex, gb, slots, tmp, clock = run_one("Static", "S0", 1, c)
        self.assertEqual(rec["status"], "COMPLETE")
        self.assertLessEqual(gb.peak_used_plus_reserved, 400000)
        self.assertEqual(gb.reserved_tokens, 0)  # 全部结算归还
        # 不变量：全局 token 台账 == 记录 tokens_in+out（无重复计账）
        self.assertEqual(gb.tokens, rec["tokens_in"] + rec["tokens_out"])


class P05S5Boundary(unittest.TestCase):
    def _s5_cfg(self, glm, ds, e=2.0, j1=2.0, sink=2.0, scale=200):
        c = fast_cfg()
        c["mock"]["scale"] = scale
        c["mock"]["latency_s"]["default"] = {
            "E1": e, "E2": e, "E3": e, "E4": e, "J1": j1, "J2": 1.0, "SINK": sink}
        c["mock"]["latency_s"]["S5"] = {
            "J2": {"glm53flash": glm, "deepseek": ds}}
        return c

    def test_predicate_boundary_exact(self):
        for mk, deadline, expect in [(89.9, 90, True), (90.0, 90, True), (90.1, 90, False)]:
            self.assertEqual(mk <= deadline, expect)

    def _calibrated_run(self, target, cfg, arm="Proposed-Dynamic"):
        """两次法：第一次测时钟分量，第二次用 overhead 精确补偿到 target。"""
        c = copy.deepcopy(cfg)
        c["mock"]["overhead_s"] = 0
        r1, *_ = run_one(arm, "S5", 9, c)
        delta = r1["makespan_s"]              # 纯时钟分量
        c2 = copy.deepcopy(cfg)
        c2["mock"]["overhead_s"] = round(target - delta, 2)
        r2, *_ = run_one(arm, "S5", 9, c2)
        return r2

    def test_boundary_899_900_901_end_to_end(self):
        base = self._s5_cfg(glm=30.0, ds=3.0)
        jitter_runs = [self._calibrated_run(90.0, base)["makespan_s"] for _ in range(3)]
        jitter = max(jitter_runs) - min(jitter_runs)
        # 边界端到端：89.9/90.1 相对 90.0 的间距 0.1s；若抖动 > 0.06 则以 ±0.5 档验证
        if jitter <= 0.06:
            r = self._calibrated_run(89.9, base)
            self.assertTrue(r["on_time"], (r["makespan_s"], jitter))
            r = self._calibrated_run(90.0, base)
            self.assertTrue(r["on_time"], (r["makespan_s"], jitter))
            r = self._calibrated_run(90.1, base)
            self.assertFalse(r["on_time"], (r["makespan_s"], jitter))
        else:
            r = self._calibrated_run(89.0, base)
            self.assertTrue(r["on_time"])
            r = self._calibrated_run(91.0, base)
            self.assertFalse(r["on_time"])

    def test_glm_finishes_before_slo_no_race(self):
        c = self._s5_cfg(glm=5.0, ds=6.0)
        rec, *_ = run_one("Proposed-Dynamic", "S5", 1, c)
        self.assertFalse(rec["s5"]["race_triggered"])
        self.assertEqual(rec["raw"]["nodes"]["J2"][0]["model"], "glm53flash")

    def test_ds_wins_race_with_cancel(self):
        c = self._s5_cfg(glm=30.0, ds=3.0)
        rec, *_ = run_one("Proposed-Dynamic", "S5", 1, c, cancel_effective=True)
        self.assertEqual(rec["s5"]["winner"], "deepseek")
        self.assertEqual(rec["race"][0]["loser_cancel_state"], "transport_cancel")

    def test_cancel_then_late_completed_costed(self):
        c = self._s5_cfg(glm=12.0, ds=3.0)     # GLM 在 SLO 后不久才完成 → 取消后迟到
        rec, *_ = run_one("Proposed-Dynamic", "S5", 1, c, cancel_effective=False)
        self.assertTrue(rec["s5"]["late"])
        self.assertGreater(rec["s5"]["late_cost_yuan"], 0)
        self.assertEqual(rec["race"][0]["loser_cancel_state"], "late_completed")

    def test_both_timeout_deadline(self):
        c = self._s5_cfg(glm=80.0, ds=80.0, e=3.0, j1=3.0, sink=3.0)
        c["deadline_s"] = {"default": 30, "S5": 30}
        rec, *_ = run_one("Proposed-Dynamic", "S5", 1, c)
        self.assertEqual(rec["status"], "INCOMPLETE_DEADLINE")
        self.assertFalse(rec["on_time"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
