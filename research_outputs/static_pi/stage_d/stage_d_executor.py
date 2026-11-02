#!/usr/bin/env python3
"""Stage D 终局执行器（S0–S5，192 执行；零调用 dry-run 优先）。

复用：d2_executor.Exec 的状态机/六臂策略/检测器/修复库/提示词（stage_a）。
新增：
  - 终局矩阵 S0×2+S1×3+S2×3+S3×8+S4×8+S5×8（6 臂 × 32 = 192）
  - S5：SLO=9.5s、GLM 初始 J2、π/Fixed/Proposed 触发 GLM→DS 竞速、首个可解析胜出、
    迟到成本全额计账、双槽重叠（K_glm=2/K_ds=1）
  - 全局预算（2,688 调用 / ¥34.56 核算 / 可选 token 上限），每执行 14 调用 / ¥0.18
  - 虚拟时钟（缩放实时）+ Mock Provider（零网络）
  - 断点状态仓库：已完成块跳过、已计成本不重复
  - 显式 exec_id、原始输出/评分分层、FINAL_RUNS.json 适配器

安全：--real 需要环境变量 STAGE_D_REAL_CALLS_AUTHORIZED=1 且批次匹配；默认 dry-run。
本文件不修改任何冻结预注册/统计文件。
"""
import argparse
import hashlib
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

import d2_executor as D2  # 只读复用；不修改

CONFIG_PATH = HERE / "stage_d_executor_config.json"


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text("utf-8"))


class BudgetExceeded(Exception):
    pass


def make_clock(real: bool, mock_scale: float) -> "VirtualClock":
    """时钟选择单点（操作者 2026-11-02 裁定）。

    --real：scale=1.0（1 真实秒 = 1 虚拟秒）——截止期/timeout/时延语义有效。
    mock  ：保持配置缩放（默认 1000），dry-run 行为不变。
    """
    return VirtualClock(1.0 if real else float(mock_scale))


class VirtualClock:
    """缩放实时：1 虚拟秒 = 1/scale 实秒。所有截止/时延以虚拟秒计。"""

    def __init__(self, scale=1000.0):
        self.scale = float(scale)
        self.t0 = time.monotonic()
        self.lock = threading.Lock()

    def now(self):
        with self.lock:
            return (time.monotonic() - self.t0) * self.scale

    def sleep(self, virtual_s):
        if virtual_s <= 0:
            return
        time.sleep(virtual_s / self.scale)

    def reset(self):
        with self.lock:
            self.t0 = time.monotonic()


class GlobalBudget:
    """跨执行全局硬预算；每次结算原子持久化，恢复时不重复计账。"""

    def __init__(self, calls, yuan, tokens=None, state_dir=None):
        self.max_calls, self.max_yuan, self.max_tokens = calls, yuan, tokens
        self.calls, self.yuan, self.tokens = 0, 0.0, 0
        self.reserved_tokens = 0            # 在途预留（P0-3：并发防超支）
        self.peak_used_plus_reserved = 0    # 不变量证明：used+reserved 峰值
        self.lock = threading.Lock()
        self.state_dir = Path(state_dir) if state_dir else None
        self.denied = 0
        if self.state_dir:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            p = self.state_dir / "GLOBAL_BUDGET.json"
            if p.exists():
                d = json.loads(p.read_text("utf-8"))
                self.calls = d.get("calls", 0)
                self.yuan = d.get("yuan", 0.0)
                self.tokens = d.get("tokens", 0)

    def _persist(self):
        if not self.state_dir:
            return
        p = self.state_dir / "GLOBAL_BUDGET.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"calls": self.calls, "yuan": round(self.yuan, 6),
                                   "tokens": self.tokens}, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)

    def reserve_call(self, est_yuan=0.0):
        with self.lock:
            if self.calls + 1 > self.max_calls:
                self.denied += 1
                raise BudgetExceeded(f"GLOBAL_CALL_CAP {self.max_calls}")
            if self.yuan + est_yuan > self.max_yuan + 1e-12:
                self.denied += 1
                raise BudgetExceeded(f"GLOBAL_YUAN_CAP {self.max_yuan}")
            self.calls += 1
            self._persist()

    def reserve_tokens(self, est_in, max_out):
        """P0-3 预留制：调用开始前预留 est_in+max_out；在途并发请求的预留互斥累加。"""
        if self.max_tokens is None:
            return 0
        with self.lock:
            need = int(est_in) + int(max_out)
            if self.tokens + self.reserved_tokens + need > self.max_tokens:
                self.denied += 1
                raise BudgetExceeded(
                    f"GLOBAL_TOKEN_CAP {self.max_tokens} "
                    f"(used={self.tokens}, reserved={self.reserved_tokens}, need={need})")
            self.reserved_tokens += need
            self.peak_used_plus_reserved = max(
                self.peak_used_plus_reserved,
                self.tokens + self.reserved_tokens)
            return need

    def release_reservation(self, need, actual_in, actual_out):
        """结算：释放预留、按实际值入账。actual ≤ est 时立即归还差额。"""
        with self.lock:
            self.reserved_tokens -= need
            self.yuan_delta = 0
            self.tokens += int(actual_in) + int(actual_out)
            self._persist()

    def settle(self, accounting_yuan, tokens_in, tokens_out):
        with self.lock:
            self.yuan += accounting_yuan
            self.tokens += tokens_in + tokens_out
            self._persist()

    def left(self):
        with self.lock:
            return {"calls_left": self.max_calls - self.calls,
                    "yuan_left": round(self.max_yuan - self.yuan, 6),
                    "tokens_left": (None if self.max_tokens is None
                                    else self.max_tokens - self.tokens),
                    "reserved_tokens": self.reserved_tokens,
                    "peak_used_plus_reserved": self.peak_used_plus_reserved}


class SlotManager:
    """全局 K_glm=2 / K_ds=1；记录每模型最大并发与占用区间。"""

    def __init__(self, slots, clock):
        self.slots = {k: threading.Semaphore(v) for k, v in slots.items()}
        self.clock = clock
        self.lock = threading.Lock()
        self.active = {k: 0 for k in slots}
        self.max_seen = {k: 0 for k in slots}
        self.intervals = []

    def acquire(self, model):
        self.slots[model].acquire()
        with self.lock:
            self.active[model] += 1
            self.max_seen[model] = max(self.max_seen[model], self.active[model])
            rec = {"model": model, "t_in": round(self.clock.now(), 2), "t_out": None}
            self.intervals.append(rec)
        return rec

    def release(self, model, rec):
        with self.lock:
            self.active[model] -= 1
            rec["t_out"] = round(self.clock.now(), 2)
        self.slots[model].release()

    def summary(self):
        with self.lock:
            return {"max_seen": dict(self.max_seen), "active": dict(self.active),
                    "n_intervals": len(self.intervals)}


class CallHandle:
    def __init__(self, provider, alias, model, system, user, max_tokens, latency,
                 cancel_effective, response, clock, slots, node):
        self.provider, self.alias, self.model = provider, alias, model
        self.system, self.user, self.max_tokens = system, user, max_tokens
        self.latency, self.cancel_effective = latency, cancel_effective
        self.response, self.clock, self.slots, self.node = response, clock, slots, node
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.result = None
        self.late = False
        self.cancel_state = "none"   # none | transport_cancel | late_completed | logical_only
        self.token_reservation = 0
        self.t_start = None
        self.t_end = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def cancel(self):
        self.cancel_event.set()

    def _run(self):
        self.t_start = self.clock.now()
        rec = self.slots.acquire(self.model)
        try:
            remain = self.latency
            while remain > 0:
                step = min(remain, 0.5)
                self.clock.sleep(step)
                remain -= step
                if self.cancel_event.is_set():
                    break
            cancelled = self.cancel_event.is_set()
            self.t_end = self.clock.now()
            if cancelled and self.cancel_effective:
                # 传输级取消生效（Mock 可模拟）：无响应、无成本
                self.cancel_state = "transport_cancel"
                self.result = {"text": "", "in": 0, "out": 0, "lat": round(self.latency, 2),
                               "stop": "cancelled", "cancelled": True}
            else:
                cancelled = self.cancel_event.is_set()
                self.late = cancelled
                self.cancel_state = "late_completed" if cancelled else "none"
                r = dict(self.response)
                r["lat"] = round(self.latency, 2)
                r["cancelled"] = False if not cancelled else cancelled
                r["late_completed"] = cancelled
                self.result = r
        except Exception as e:  # pragma: no cover
            self.result = {"text": "", "in": 0, "out": 0, "lat": 0.0,
                           "stop": "error", "error": repr(e)}
        finally:
            self.slots.release(self.model, rec)
            self.done.set()


class MockProvider:
    """零网络：确定性响应 + 虚拟时延；用于 dry-run 与控制流测试。"""

    def __init__(self, clock, slots, cfg, scenario, rep):
        self.clock, self.slots, self.cfg = clock, slots, cfg
        self.scenario, self.rep = scenario, rep
        self.calls = []
        self.lock = threading.Lock()

    def _latency(self, node, alias):
        table = self.cfg["mock"]["latency_s"]
        return float(table.get(self.scenario, {}).get(node, {}).get(
            alias, table.get("default", {}).get(node, 8.0)))

    def _response(self, node, alias, system):
        if node in ("E1", "E2", "E3", "E4"):
            return {"text": json.dumps({
                "subjects": [{"name": "测试主体", "role": "公司"}],
                "notice_numbers": ["2026-001"],
                "dates": {"D1": {"公告落款日": "2026-04-28"}},
                "positions": [{"field": "任职状况", "value": "董事长"}],
            }, ensure_ascii=False)}
        if node == "J1":
            has_relay = "dates_relay" in (system or "")
            d = {"positions_relay": [{"field": "任职状况", "value": "董事长"}]}
            if has_relay:
                d["dates_relay"] = {"D1": {"公告落款日": "2026-04-28"}}
            return {"text": json.dumps(d, ensure_ascii=False)}
        if node == "J2":
            return {"text": json.dumps({"counts": {"personal": 1, "announcing": 1},
                                        "items": []}, ensure_ascii=False)}
        if node == "SINK":
            return {"text": json.dumps({
                "answers": [
                    {"fact_id": "D_1", "value": "同一自然人", "doc": "D1", "page": 1,
                     "quote": "测试引用"},
                    {"fact_id": "D_2", "value": "同一份文书实例", "doc": "D2", "page": 1,
                     "quote": "测试引用"},
                ],
                "abstentions": [{"item_id": "U2", "text": "原文不可判定"}],
            }, ensure_ascii=False)}
        return {"text": json.dumps({"ok": True}, ensure_ascii=False)}

    def start_call(self, alias, model, system, user, max_tokens, timeout_s=120,
                   temperature=0, node="?", cancel_effective=True):
        latency = self._latency(node, alias)
        r = self._response(node, alias, system)
        text = r["text"]
        r["in"] = len(system or "") + len(user or "")  # 保守字符计（token 报告见 §token）
        r["out"] = len(text)
        r["stop"] = "end_turn"
        h = CallHandle(self, alias, model, system, user, max_tokens, latency,
                       cancel_effective, r, self.clock, self.slots, node)
        with self.lock:
            self.calls.append({"node": node, "alias": alias, "model": model,
                               "latency": latency, "scenario": self.scenario,
                               "rep": self.rep})
        return h


class _RealHandle:
    """真实 urllib 调用句柄：同步传输不可传输级取消（P0-2 三态语义）。"""

    def __init__(self, transport_fn, alias, model, system, user, max_tokens,
                 timeout_s, temperature, clock, slots, node):
        self.alias, self.model = alias, model
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.result = None
        self.late = False
        self.cancel_state = "none"
        self.token_reservation = 0
        self.t_start = None
        self.t_end = None
        self._fn = transport_fn
        self._args = (alias, system, user, max_tokens, timeout_s, temperature)
        self.clock, self.slots, self.node = clock, slots, node
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def cancel(self):
        """仅逻辑取消：结果不再作为胜出者；传输继续、槽保持、成本照计。"""
        self.cancel_event.set()

    def _run(self):
        self.t_start = self.clock.now()
        rec = self.slots.acquire(self.model)
        try:
            resp = self._fn(*self._args)
            self.t_end = self.clock.now()
            r = dict(resp)
            if self.cancel_event.is_set():
                self.late = True
                self.cancel_state = "late_completed"
                r["late_completed"] = True
            r["cancelled"] = False
            self.result = r
        except Exception as e:
            self.t_end = self.clock.now()
            self.cancel_state = ("logical_only" if self.cancel_event.is_set()
                                 else "error")
            self.result = {"text": "", "in": 0, "out": 0, "lat": 0.0,
                           "stop": "error", "error": repr(e),
                           "cancelled": self.cancel_event.is_set()}
        finally:
            self.slots.release(self.model, rec)
            self.done.set()


class RealProvider:
    """真实 transport 包装（默认禁用；--real 需显式授权环境变量）。不用于 dry-run。

    P0-2：异步线程化；cancel 为逻辑取消（urllib 无传输级取消）；
    迟到响应完整结算（成本/槽占用到线程真实结束）。
    """

    def __init__(self, clock, slots, transport_fn=None):
        self.clock, self.slots = clock, slots
        self.calls = []
        self._fn = transport_fn
        if self._fn is None:
            import transport
            self._fn = transport.call_model

    def start_call(self, alias, model, system, user, max_tokens, timeout_s=120,
                   temperature=0, node="?", cancel_effective=False):
        self.calls.append({"node": node, "alias": alias, "model": model})
        return _RealHandle(self._fn, alias, model, system, user, max_tokens,
                           timeout_s, temperature, self.clock, self.slots, node)


class RunStore:
    """断点状态仓库：completed 跳过；已计成本由 GlobalBudget 持久化。"""

    def __init__(self, state_dir, out_dir):
        self.state_dir = Path(state_dir)
        self.out_dir = Path(out_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def _p(self, exec_id):
        safe = exec_id.replace("|", "__").replace("/", "_")
        return self.state_dir / f"{safe}.json"

    def record_path(self, exec_id):
        safe = exec_id.replace("|", "__").replace("/", "_")
        return self.out_dir / f"{safe}.json"

    def completed(self, exec_id):
        # 记录本身是原子写的最终产物；只要存在即视为已完成（状态文件仅作辅助），
        # 避免崩溃后重复执行/重复计费。
        rp = self.record_path(exec_id)
        if rp.exists():
            try:
                d = json.loads(rp.read_text("utf-8"))
                if d.get("exec_id") == exec_id:
                    return d
            except Exception:
                return None
        return None

    def begin(self, exec_id):
        with self.lock:
            self._p(exec_id).write_text(json.dumps(
                {"exec_id": exec_id, "status": "running",
                 "started": time.time()}, ensure_ascii=False), "utf-8")

    def commit(self, record):
        exec_id = record["exec_id"]
        with self.lock:
            tmp = self.record_path(exec_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, self.record_path(exec_id))
            self._p(exec_id).write_text(json.dumps(
                {"exec_id": exec_id, "status": "completed",
                 "committed": time.time()}, ensure_ascii=False), "utf-8")


class FinalExec(D2.Exec):
    """复用 D2 状态机/策略/检测/修复；新增 S5、全局预算、虚拟时钟、Mock、断点。"""

    def __init__(self, arm, scenario, rep, cfg, clock, global_budget, slots,
                 provider, store, dry_run=True):
        super().__init__(arm, scenario, rep)
        self.cfg = cfg
        self.clock = clock
        self.gb = global_budget
        self.slots = slots
        self.provider = provider
        self.store = store
        self.dry_run = dry_run
        self.exec_id = f"{arm}|{scenario}|r{rep}"
        self.deadline_s = float(cfg["deadline_s"].get(scenario, cfg["deadline_s"]["default"]))
        self.slo_s = float(cfg["s5"]["slo_s"])
        self.overhead_s = float(cfg["mock"].get("overhead_s", 0.0))
        self.local_calls = 0
        self.local_yuan = 0.0
        self.budget_lock = threading.Lock()
        self.tokens_in = 0
        self.tokens_out = 0
        self.budget_exhausted = False
        self.deadline_hit = False
        self.raw = {"nodes": {}, "calls": []}
        self.race_log = []
        self.s5 = {"slo_violation": False, "race_triggered": False,
                   "winner": None, "late": False, "late_calls": 0,
                   "late_cost_yuan": 0.0, "j2_start_at": None,
                   "ds_started_at": None}
        self.cancel_effective = bool(cfg["s5"].get("cancel_effective", True))
        self.model_used = {}
        self.t0 = None

    # ---------- 虚拟时钟版 detect/policy/apply_action（覆盖 D2 的 time.time 版本） ----------
    def detect(self, node, parsed, events):
        sig = {}
        if "timeout" in events or "parse_fail" in events:
            sig["D1"] = "model_suspect"
        if node in ("E1", "E2") and not (parsed or {}).get("positions"):
            sig["D2"] = "structure"
        if node == "J1" and not ((parsed or {}).get("dates_relay")
                                 and (parsed or {}).get("positions_relay")):
            sig["D2"] = "structure"
        if node == "FMT":
            ans = (parsed or {}).get("answers") or []
            bad = [a.get("fact_id") for a in ans
                   if a.get("fact_id") in D2.PURE
                   and not D2.PURE[a["fact_id"]](str(a.get("value") or ""))]
            if bad:
                sig["D3"] = "format"
        if node == "J2":
            c = (parsed.get("counts") or {}) if parsed else {}
            if (c.get("personal") is not None and c.get("announcing") is not None
                    and c["personal"] > c["announcing"]):
                sig["D6"] = "caliber_suspect"
        if sig:
            self.anomalies.append({"node": node, "sig": sig,
                                   "t": round(self.clock.now() - self.t0, 1)})
        return sig

    def policy(self, node, sig):
        arm = self.arm
        t_rem = self.deadline_s - (self.clock.now() - self.t0)
        ds_ok = ((self.cfg["per_exec"]["calls"] - self.local_calls) >= 2
                 and t_rem > 72)
        acts = []
        if arm == "Static" or not sig:
            pass
        elif arm == "R-only":
            acts = [("structure_repair", node)] if node in D2.REPAIR_LIB else [("rerun_asis", node)]
        elif arm == "π-only":
            acts = [("swap", node)] if ds_ok else []
        elif arm == "Simple-Dynamic":
            acts = [("retry", node)]
        elif arm == "Fixed-Composite":
            acts = (([("structure_repair", node)] if node in D2.REPAIR_LIB else [])
                    + [("format_repair", "FMT")]
                    + ([("swap", node)] if ds_ok else []))
        elif arm == "Proposed-Dynamic":
            fam = next(iter(sig.values()))
            if fam == "structure":
                acts = [("structure_repair", node)] if node in D2.REPAIR_LIB else []
            elif fam == "format":
                acts = [("format_repair", "FMT")]
            elif fam == "model_suspect":
                acts = [("swap", node)] if ds_ok else [("retry", node)]
            elif fam == "caliber_suspect":
                acts = [("structure_repair", node)] if node in D2.REPAIR_LIB else []
        if t_rem < 60 and arm != "Static":
            acts = []
        self.decisions.append({"node": node, "sig": sig, "acts": acts,
                               "t_rem": round(t_rem)})
        return acts

    def apply_action(self, node, kind):
        self.actions.append({"kind": kind, "node": node,
                             "t": round(self.clock.now() - self.t0, 1)})
        if kind == "structure_repair":
            fam_spec = D2.REPAIR_LIB[node][1]
            self.spec[node]["sys"] = fam_spec
            self.deployed_spec = lambda n, _s=fam_spec, _n=node: (
                _s if n == _n else None) if (n == _n and self.scenario == "S3" and n == "J1") else self._orig_deployed(n)
        elif kind == "format_repair":
            self.fmt_bypassed = False
            self._fmtrep = getattr(self, "_fmtrep", 0) + 1
            if self._fmtrep <= 1:
                self.versions["FMT"] = self.versions.get("FMT", 0) + 1
                self.state["FMT"] = "Ready"
        if kind in ("structure_repair", "swap", "retry", "rerun_asis"):
            st = self.spec[node]
            if kind == "swap":
                st["model"] = "deepseek"
            elif kind == "retry":
                st["model"] = st["model"] if st["model"] == "deepseek" else "glm53flash"
            self._reruncount = getattr(self, "_reruncount", {})
            self._reruncount[node] = self._reruncount.get(node, 0) + 1
            if self._reruncount[node] > 2:
                return
            self.versions[node] = self.versions.get(node, 0) + 1
            self.state[node] = "Ready"

            def inval(n):
                for d in self.spec[n]["downs"]:
                    if self.state.get(d) in ("Completed", "Ready"):
                        self.state[d] = "Ready"
                    inval(d)
            inval(node)

    # ---------- 预算/调用 ----------
    def _reserve_call(self, est_yuan=0.0):
        with self.budget_lock:
            if self.local_calls + 1 > self.cfg["per_exec"]["calls"]:
                self.budget_exhausted = True
                raise BudgetExceeded("LOCAL_CALL_CAP")
            if self.local_yuan + est_yuan > self.cfg["per_exec"]["yuan"] + 1e-12:
                self.budget_exhausted = True
                raise BudgetExceeded("LOCAL_YUAN_CAP")
            self.gb.reserve_call(est_yuan)
            self.local_calls += 1
            self.calls += 1

    def _settle(self, r):
        accounting = r.get("in", 0) * 0.8e-6 + r.get("out", 0) * 2.8e-6
        actual = 0.0 if r.get("alias", "") in ("glm53flash", "glm53") else accounting
        with self.budget_lock:
            self.local_yuan += accounting
            self.tokens_in += int(r.get("in", 0))
            self.tokens_out += int(r.get("out", 0))
        # tokens 已由 release_reservation 按实际入账；此处只结算现金，避免双计
        self.gb.settle(accounting, 0, 0)
        return accounting, actual

    def _call(self, node, alias, model, system, user, max_tokens, cancel_effective=True):
        est = (len(system or "") + len(user or "")) * 0.8e-6 + max_tokens * 2.8e-6
        self._reserve_call(est)
        chars = len(system or "") + len(user or "")
        est_in_tokens = chars + 64          # 保守：1 字符 ≥ 1 token + 结构开销
        need = self.gb.reserve_tokens(est_in_tokens, max_tokens)
        h = self.provider.start_call(alias, model, system, user, max_tokens,
                                     node=node, cancel_effective=cancel_effective)
        h.token_reservation = need
        h.start()
        return h

    def _finish_call(self, node, h, attempt=1):
        h.done.wait()
        r = h.result or {}
        r = dict(r)
        r["alias"] = h.alias
        # P0-3：释放预留并按实际入账（迟到响应同样在此全额结算）；
        # 即使 need=0（未启用 token 上限）也记录实际 token，保证台账与记录一致。
        self.gb.release_reservation(getattr(h, "token_reservation", 0),
                                    int(r.get("in", 0)), int(r.get("out", 0)))
        r["model_used"] = h.model
        r["t_start"] = h.t_start
        r["t_end"] = h.t_end
        r["late"] = h.late
        cost, actual = self._settle(r)
        r["accounting_yuan"] = round(cost, 8)
        r["actual_cash_yuan"] = round(actual, 8)
        self.model_used[node] = h.model
        self.raw["calls"].append({"node": node, "attempt": attempt,
                                  "alias": h.alias, "model": h.model,
                                  "latency": h.latency, "in": r.get("in", 0),
                                  "out": r.get("out", 0),
                                  "cancelled": r.get("cancelled", False),
                                  "late": h.late, "accounting_yuan": round(cost, 8)})
        self.raw["nodes"].setdefault(node, []).append({
            "model": h.model, "text": r.get("text", ""),
            "in": r.get("in", 0), "out": r.get("out", 0),
            "latency": h.latency, "cancelled": r.get("cancelled", False),
            "late": h.late, "attempt": attempt})
        return r

    # ---------- S5 ----------
    def _parseable(self, text):
        p = D2.extract_json(text)
        return p if isinstance(p, dict) else None

    def _exec_s5_j2(self):
        st = self.spec["J2"]
        system = self.inject_prompt("J2") or st["sys"]
        user = st["user"]({u: self.outputs[u] for u in st["ups"]})
        race = self.arm in self.cfg["s5"]["race_arms"]
        if not race:
            h = self._call("J2", "glm53flash", "glm53flash", system, user,
                           D2.MAXTOK["J2"])
            r = self._finish_call("J2", h)
            self._after_j2(r)
            return
        # GLM 先行；SLO 从 J2 在途开始计（不是 DAG 全局时间）
        j2_start = self.clock.now()
        self.s5["j2_start_at"] = round(j2_start - self.t0, 1)
        glm = self._call("J2", "glm53flash", "glm53flash", system, user,
                         D2.MAXTOK["J2"], cancel_effective=self.cancel_effective)
        while not glm.done.is_set() and (self.clock.now() - j2_start) < self.slo_s:
            self.clock.sleep(0.2)
        if glm.done.is_set():
            r = self._finish_call("J2", glm)
            self._after_j2(r)
            return
        self.s5["slo_violation"] = True
        self.s5["race_triggered"] = True
        self.s5["ds_started_at"] = round(self.clock.now() - self.t0, 1)
        self.actions.append({"kind": "race_swap", "node": "J2",
                             "t": round(self.clock.now() - self.t0, 1)})
        ds = self._call("J2", "deepseek", "deepseek", system, user,
                        D2.MAXTOK["J2"], cancel_effective=self.cancel_effective)
        winner = None
        while True:
            if ds.done.is_set():
                cand = self._parseable((ds.result or {}).get("text", ""))
                if cand is not None:
                    winner = "deepseek"; glm.cancel(); break
            if glm.done.is_set():
                cand = self._parseable((glm.result or {}).get("text", ""))
                if cand is not None:
                    winner = "glm53flash"; ds.cancel(); break
            if glm.done.is_set() and ds.done.is_set():
                break
            self.clock.sleep(0.2)
        if winner is None:
            self.state["J2"] = "Failed"
            self.invalid_reason = "S5_BOTH_UNPARSEABLE"
            return
        # 结算胜者与败者（败者若迟到，成本照计）
        rh = ds if winner == "deepseek" else glm
        lh = glm if winner == "deepseek" else ds
        r = self._finish_call("J2", rh)
        rl = self._finish_call("J2", lh)
        self.s5["winner"] = winner
        if lh.late:
            self.s5["late"] = True
            self.s5["late_calls"] += 1
            self.s5["late_cost_yuan"] = round(rl.get("accounting_yuan", 0.0), 8)
        self.race_log.append({
            "slo_s": self.slo_s, "j2_start_at": self.s5["j2_start_at"],
            "trigger_at": self.s5["ds_started_at"],
            "in_flight_at_trigger": (round(self.s5["ds_started_at"] - self.s5["j2_start_at"], 1)
                                     if self.s5["j2_start_at"] is not None else None),
            "winner": winner, "loser": ("glm53flash" if winner == "deepseek" else "deepseek"),
            "loser_late": bool(lh.late), "loser_cancelled": bool((lh.result or {}).get("cancelled")),
            "loser_cancel_state": getattr(lh, "cancel_state", "none"),
            "loser_cost_yuan": round(rl.get("accounting_yuan", 0.0), 8),
            "glm_done": glm.done.is_set(), "ds_done": ds.done.is_set(),
        })
        self._after_j2(r)

    def _after_j2(self, r):
        text = r.get("text", "")
        self.outputs["J2"] = text
        parsed = D2.extract_json(text)
        if parsed is None:
            self.state["J2"] = "Failed"
            self.anomalies.append({"node": "J2", "sig": {"D1": "model_suspect"},
                                   "t": round(self.clock.now() - self.t0, 1)})
            for kind, tgt in self.policy("J2", {"D1": "model_suspect"}):
                self.apply_action(tgt, kind)
            return
        self.state["J2"] = "Completed"
        self.exec_log.append({"node": "J2", "model": self.model_used.get("J2", "?"),
                              "prompt_sha": hashlib.sha256(
                                  (self.spec["J2"]["sys"] or "").encode()).hexdigest()[:12],
                              "wall": r.get("lat", 0.0)})
        sig = self.detect("J2", parsed, [])
        self.fault_persistence_check("J2")
        for kind, tgt in self.policy("J2", sig):
            self.apply_action(tgt, kind)

    # ---------- 通用 LLM 节点 ----------
    def exec_llm(self, node):
        if node == "J2" and self.scenario == "S5":
            try:
                return self._exec_s5_j2()
            except BudgetExceeded:
                self.budget_exhausted = True
                self.invalid_reason = "INCOMPLETE_BUDGET"
                self.state["J2"] = "Failed"
                return
        st = self.spec[node]
        alias = st["model"]
        system = self.inject_prompt(node) or st["sys"]
        user = st["user"]({u: self.outputs[u] for u in st["ups"]})
        sha_before = hashlib.sha256(system.encode()).hexdigest()[:12]
        for attempt in (1, 2):
            try:
                if attempt == 1 and self.inject_exc_first(node):
                    raise TimeoutError("injected")
                h = self._call(node, alias, alias, system, user, D2.MAXTOK[st["layer"]])
                r = self._finish_call(node, h, attempt)
                text = r.get("text", "")
                text = self.corrupt_once(node, text)
                parsed = D2.extract_json(text)
                sig = self.detect(node, parsed, ["timeout"] if attempt == 2 else [])
                self.outputs[node] = text
                self.exec_log.append({"node": node, "model": alias,
                                      "prompt_sha": sha_before, "wall": r.get("lat", 0.0)})
                self.state[node] = "Completed"
                self.fault_persistence_check(node)
                for kind, tgt in self.policy(node, sig):
                    self.apply_action(tgt, kind)
                return
            except BudgetExceeded:
                self.state[node] = "Failed"
                self.invalid_reason = "INCOMPLETE_BUDGET"
                return
            except Exception:
                if attempt == 2:
                    self.state[node] = "Failed"
                    self.anomalies.append({"node": node, "sig": {"D1": "model_suspect"},
                                           "t": round(self.clock.now() - self.t0, 1)})
                    for kind, tgt in self.policy(node, {"D1": "model_suspect"}):
                        self.apply_action(tgt, kind)
                    return
                self.clock.sleep(2)

    # ---------- 运行循环 ----------
    def run(self):
        self.t0 = self.clock.now()
        pool = ThreadPoolExecutor(max_workers=3)
        futs = {}
        while True:
            elapsed = self.clock.now() - self.t0
            if elapsed > self.deadline_s + 30:
                self.deadline_hit = True
                for n, s in self.state.items():
                    if s != "Completed":
                        self.state[n] = "Failed"
                break
            for n, s in self.state.items():
                if s == "Ready" and all(self.state.get(u) == "Completed" for u in self.spec[n]["ups"]):
                    futs[n] = pool.submit(self.call, n)
                    self.state[n] = "Running"
            if all(s == "Completed" for s in self.state.values()):
                break
            if not futs:
                break
            for n, f in list(futs.items()):
                if f.done() and f.exception() is not None:
                    self.invalid_reason = f"fut-exc:{n}:{repr(f.exception())[:60]}"
            done = [n for n, f in futs.items() if f.done()]
            if not done:
                self.clock.sleep(0.3)
            for n in done:
                futs.pop(n)
            self.clock.sleep(0.15)
        pool.shutdown(wait=True)
        self.makespan = round((self.clock.now() - self.t0) + self.overhead_s, 1)
        return self.finish()

    # ---------- 完成/记录 ----------
    def finish(self):
        parsed = D2.extract_json(self.outputs.get("FMT") or "")
        rec = {"exec_id": self.exec_id, "arm": self.arm, "scenario": self.scenario,
               "rep": self.rep, "dry_run": self.dry_run, "mock": self.dry_run,
               "deadline_s": self.deadline_s,
               "makespan_s": self.makespan, "on_time": self.makespan <= self.deadline_s,
               "status": None, "calls": self.local_calls,
               "accounting_yuan": round(self.local_yuan, 8),
               "actual_cash_yuan": 0.0,
               "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
               "actions": self.actions, "decisions": self.decisions,
               "anomalies": self.anomalies, "final_states": dict(self.state),
               "exec_log": self.exec_log, "fault_checks": self.fault_checks,
               "invalid_reason": self.invalid_reason,
               "raw": self.raw, "race": self.race_log, "s5": self.s5,
               "global_budget": self.gb.left(),
               "slots": self.slots.summary()}
        rec["actual_cash_yuan"] = round(sum(
            c["accounting_yuan"] for c in self.raw["calls"]
            if c["alias"] == "deepseek"), 8)
        if parsed:
            term = D2.SA_EX.build_terminal_output(json.loads(json.dumps(parsed)))
            from terminal_quality import evaluate_terminal_quality
            q = evaluate_terminal_quality(D2.SA_EX.CONTRACT, term, D2.SRC())
            tp = sum(1 for c in q["claim_results"] if c["status"].startswith("CORRECT"))
            rec["score"] = {"tp": tp, "slot_success": round(tp / 23, 4),
                            "quality_status": q.get("quality_status"),
                            "claim_results": q.get("claim_results", [])}
            def val(fid):
                a = next((x for x in parsed.get("answers", [])
                          if x.get("fact_id") == fid), None)
                return str(a.get("value")) if a else None
            rec["score"]["F1_ok"] = "2026-10-09" in str(val("F1"))
            rec["score"]["F2_ok"] = "2026-10-10" in str(val("F2"))
            rec["score"]["E2"] = val("E2")
        else:
            rec["score"] = {"tp": 0, "slot_success": 0.0,
                            "F1_ok": False, "F2_ok": False, "E2": None}
        rec["tp"] = rec["score"]["tp"]
        if self.budget_exhausted or self.invalid_reason == "INCOMPLETE_BUDGET":
            rec["status"] = "INCOMPLETE_BUDGET"
        elif self.deadline_hit:
            rec["status"] = "INCOMPLETE_DEADLINE"
        elif any(s == "Failed" for s in self.state.values()):
            rec["status"] = "INCOMPLETE_NO_RECOVERY"
        elif any(s not in ("Completed",) for s in self.state.values()):
            rec["status"] = "INCOMPLETE_NO_RECOVERY"
        else:
            rec["status"] = "COMPLETE"
        self.store.commit(rec)
        print(f"[{self.exec_id}] {rec['makespan_s']}s on_time={rec['on_time']} "
              f"status={rec['status']} calls={rec['calls']} TP={rec['tp']} "
              f"race={self.s5.get('winner')}", flush=True)
        return rec


# ---------- 矩阵/顺序 ----------
def build_order(cfg):
    rng = random.Random(cfg["seed"])
    blocks = [(sc, r + 1) for sc, n in cfg["blocks"].items() for r in range(n)]
    rng.shuffle(blocks)
    order = []
    for sc, rep in blocks:
        arms = cfg["arms"][:]
        rng.shuffle(arms)
        for a in arms:
            order.append((a, sc, rep))
    return order


def verify_matrix(cfg):
    order = build_order(cfg)
    ids = [f"{a}|{s}|r{r}" for a, s, r in order]
    counts = {a: {s: 0 for s in cfg["blocks"]} for a in cfg["arms"]}
    for a, s, r in order:
        counts[a][s] += 1
    per_arm = {a: sum(counts[a].values()) for a in cfg["arms"]}
    per_scen_total = {s: sum(counts[a][s] for a in cfg["arms"]) for s in cfg["blocks"]}
    per_arm_scen_ok = all(counts[a][s] == cfg["blocks"][s]
                          for a in cfg["arms"] for s in cfg["blocks"])
    return {"n_total": len(order), "n_unique": len(set(ids)),
            "per_arm": per_arm, "per_scenario_total": per_scen_total,
            "expected": {"n_total": 192, "per_arm": 32,
                         "per_arm_scenario": cfg["blocks"],
                         "per_scenario_total": {s: cfg["blocks"][s] * len(cfg["arms"])
                                                for s in cfg["blocks"]}},
            "ok": (len(order) == 192 and len(set(ids)) == 192
                   and all(v == 32 for v in per_arm.values())
                   and per_arm_scen_ok)}


def build_analysis_input(out_dir):
    out = Path(out_dir)
    recs = {}
    for p in out.glob("*.json"):
        r = json.loads(p.read_text("utf-8"))
        if "exec_id" in r:
            recs[r["exec_id"]] = r
    pairs = []
    for sc in ("S3", "S4"):
        for rep in range(1, 9):
            p = recs.get(f"Proposed-Dynamic|{sc}|r{rep}")
            s = recs.get(f"Simple-Dynamic|{sc}|r{rep}")
            if not p or not s:
                raise SystemExit(f"missing pair {sc} r{rep}")
            pairs.append({"scenario": sc, "rep": rep,
                          "tp_proposed": int(p.get("tp", p.get("score", {}).get("tp", 0))),
                          "tp_simple": int(s.get("tp", s.get("score", {}).get("tp", 0)))})
    # R1（操作员 2026-11-02 裁定）：保护集计数必须由审计器从记录计算，禁止硬编码 0
    from protection_set_audit import audit as _prot_audit, default_baseline as _prot_base
    prot = _prot_audit(out, _prot_base())
    payload = {"experiment_id": "STAGE_D_CONFIRM_V1",
               "pairs": pairs,
               "protection_regressions": int(prot["n_regressions"]),
               "protection_audit": {
                   "mode": prot["mode"],
                   "slot_runs_enumerated": prot["slot_runs_enumerated"],
                   "by_scenario": prot["by_scenario"],
                   "verdict": prot["verdict"],
                   "note": "R1: S3/S4/S5 each 384, cumulative 1152; computed from records, not hardcoded"},
               "mock": True,
               "note": "MOCK dry-run: protection count comes from R1 auditor; not a scientific result"}
    p = out / "FINAL_RUNS.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["matrix", "run", "build-analysis-input"])
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--real", action="store_true")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.cmd == "matrix":
        print(json.dumps(verify_matrix(cfg), ensure_ascii=False, indent=1))
        return 0
    out_dir = Path(a.out or cfg["output_dir"])
    state_dir = out_dir / "state"
    if a.real:
        if os.environ.get("STAGE_D_REAL_CALLS_AUTHORIZED") != "1":
            raise SystemExit("REFUSED: --real requires STAGE_D_REAL_CALLS_AUTHORIZED=1; "
                             "no GO present")
    # 真实模式 1:1 时钟；mock 保持缩放（见 make_clock）。
    clock = make_clock(a.real, cfg["mock"]["scale"])
    gb = GlobalBudget(cfg["global"]["calls"], cfg["global"]["yuan"],
                      cfg["global"].get("tokens"), state_dir)
    slots = SlotManager(cfg["slots"], clock)
    store = RunStore(state_dir, out_dir)
    order = build_order(cfg)
    if a.cmd == "build-analysis-input":
        print(build_analysis_input(out_dir))
        return 0
    done = skipped = 0
    for i, (arm, sc, rep) in enumerate(order):
        if a.limit is not None and done >= a.limit:
            break
        exec_id = f"{arm}|{sc}|r{rep}"
        if store.completed(exec_id):
            skipped += 1
            continue
        store.begin(exec_id)
        provider = (RealProvider(clock, slots) if a.real
                    else MockProvider(clock, slots, cfg, sc, rep))
        ex = FinalExec(arm, sc, rep, cfg, clock, gb, slots, provider, store,
                       dry_run=not a.real)
        ex.run()
        done += 1
    print(f"BATCH DONE: executed={done} skipped={skipped} "
          f"global={gb.left()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
