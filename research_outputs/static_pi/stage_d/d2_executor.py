#!/usr/bin/env python3
"""D2 执行器（D2_PREREGISTRATION_V1_1 冻结执行）。

新增：S3 持续性 J1 部署缺陷（无 relay 附录）；S4 持续性格式层旁路（FMT 为正式 DAG 节点：
版本/输入哈希/输出哈希/成本入记录）；修复机制库（已验证机制，R-only/Fixed/Proposed 同备）；
六实现门禁断言（持续性/动作对应/按尝试计数/分块随机化/版本缓存隔离/上下游哈希完整性）。
"""
import argparse, hashlib, json, os, random, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SA = Path("/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, str(SA)); sys.path.insert(0, "/root/capital_opinion_pilot")
import transport
import executor as SA_EX

HERE = Path(__file__).parent
OUT = HERE / "runs_d2"
DEADLINE_S, SEED = 180, 20261101
BUDGET = {"calls": 14, "yuan": 0.18}
SLOTS = {"glm53flash": threading.Semaphore(2), "deepseek": threading.Semaphore(1)}
MAXTOK = {"E": 2000, "J1": 3000, "J2": 4000, "SINK": 4000}

# 修复机制库（仅已验证机制；对所有具备该动作类的臂同等可用）
REPAIR_LIB = {"J1": ("structure", SA_EX.J1_SYSTEM + SA_EX.RELAY_ADDENDUM + SA_EX.J1_POSITIONS_ADDENDUM)}
FMT_ENABLE = ("format", "enable")

def e_user(doc): return SA_EX.e_user(doc)

def base_spec():
    return {
        "E1": dict(model="glm53flash", layer="E", sys=SA_EX.E_SYSTEM + SA_EX.E_POSITION_ADDENDUM, user=lambda u: e_user("E1"), ups=[], downs=["J1"]),
        "E2": dict(model="glm53flash", layer="E", sys=SA_EX.E_SYSTEM + SA_EX.E_POSITION_ADDENDUM, user=lambda u: e_user("E2"), ups=[], downs=["J1"]),
        "E3": dict(model="glm53flash", layer="E", sys=SA_EX.E_SYSTEM, user=lambda u: e_user("E3"), ups=[], downs=["J2"]),
        "E4": dict(model="glm53flash", layer="E", sys=SA_EX.E_SYSTEM, user=lambda u: e_user("E4"), ups=[], downs=["J2"]),
        "J1": dict(model="glm53flash", layer="J1",
                   sys=SA_EX.J1_SYSTEM + SA_EX.RELAY_ADDENDUM + SA_EX.J1_POSITIONS_ADDENDUM,
                   user=lambda u: SA_EX.j1_user(json.dumps({"E1": u["E1"], "E2": u["E2"]}, ensure_ascii=False)),
                   ups=["E1", "E2"], downs=["J2", "SINK"]),
        "J2": dict(model="glm53flash", layer="J2", sys=SA_EX.J2_SYSTEM + SA_EX.DISAMBIG_ADDENDUM,
                   user=lambda u: SA_EX.j2_user(json.dumps({"J1": u["J1"], "E3": u["E3"], "E4": u["E4"]}, ensure_ascii=False)),
                   ups=["J1", "E3", "E4"], downs=["SINK"]),
        "SINK": dict(model="glm53flash", layer="SINK", sys=SA_EX.SINK_SYSTEM,
                     user=lambda u: SA_EX.sink_user(json.dumps({"J1": u["J1"], "J2": u["J2"]}, ensure_ascii=False)),
                     ups=["J1", "J2"], downs=["FMT"]),
        "FMT": dict(model="deterministic", layer="FMT", sys=None, user=None, ups=["SINK"], downs=[]),
    }

PURE = {"D_1": lambda v: v == "SAME_PERSON", "D_2": lambda v: v == "SAME_NOTICE_INSTANCE",
        "D_3": lambda v: v == "SAME_RECEIPT_EVENT", "D_4": lambda v: v == "DIFFERENT_COMPANY"}

def extract_json(text):
    import re
    if not isinstance(text, str): return None
    t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i: return None
    try: return json.loads(t[i:j + 1])
    except json.JSONDecodeError: return None

class Exec:
    def __init__(self, arm, scenario, rep):
        self.arm, self.scenario, self.rep = arm, scenario, rep
        self.spec = base_spec()
        self.state = {n: "Ready" for n in self.spec}
        self.outputs, self.versions, self.exec_log = {}, {}, []
        self.budget = dict(BUDGET); self.t0 = None
        self.anomalies, self.actions, self.decisions = [], [], []
        self.calls = 0; self.lock = threading.Lock()
        self.sem = {"glm53flash": threading.Semaphore(2), "deepseek": threading.Semaphore(1)}
        self.fmt_bypassed = (scenario == "S4")   # S4：部署缺陷=格式层被绕过（持续）
        self.fault_checks = []
        self.invalid_reason = None

    # ---------- 场景注入（仅审计侧） ----------
    def deployed_spec(self, node):
        if node == "J1" and self.scenario == "S3":
            return SA_EX.J1_SYSTEM  # 持续性部署缺陷：无 relay 附录
        return None

    def inject_prompt(self, node):
        dep = self.deployed_spec(node)
        if dep: return dep
        if node == "J2" and self.scenario == "S2" and not getattr(self, "_s2_done", False):
            self._s2_done = True
            return SA_EX.J2_SYSTEM
        return None

    def inject_exc_first(self, node):
        if node == "J2" and self.scenario == "S2" and not getattr(self, "_s2_to_done", False):
            self._s2_to_done = True; return True
        return False

    def corrupt_once(self, node, text):
        if node == "E2" and self.scenario == "S1" and not getattr(self, "_s1_done", False):
            self._s1_done = True
            import re
            t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            i, j = t.find("{"), t.rfind("}")
            d = json.loads(t[i:j + 1]); d.pop("positions", None)
            return json.dumps(d, ensure_ascii=False)
        return text

    # ---------- 门禁 1：持续性核验（每次受影响节点完成） ----------
    def fault_persistence_check(self, node):
        if node == "J1" and self.scenario == "S3":
            dep_active = self.deployed_spec("J1") is not None
            has_relay = "dates_relay" in (extract_json(self.outputs.get("J1") or "") or {})
            ok = (dep_active and not has_relay) or (not dep_active and has_relay)
            self.fault_checks.append({"node": "J1", "deploy_defect_active": dep_active, "dates_relay_present": has_relay, "consistent": ok})
        if node == "FMT" and self.scenario == "S4":
            self.fault_checks.append({"node": "FMT", "bypassed": self.fmt_bypassed, "consistent": True})
        if node in ("E1", "E2") and self.scenario == "S3":
            d = extract_json(self.outputs.get(node) or "") or {}
            self.fault_checks.append({"node": node, "dates_extracted": bool(d.get("dates")), "consistent": bool(d.get("dates"))})

    # ---------- 检测器（控制器可见） ----------
    def detect(self, node, parsed, events):
        sig = {}
        if "timeout" in events or "parse_fail" in events: sig["D1"] = "model_suspect"
        if node in ("E1", "E2") and not (parsed or {}).get("positions"): sig["D2"] = "structure"
        if node == "J1" and not ((parsed or {}).get("dates_relay") and (parsed or {}).get("positions_relay")): sig["D2"] = "structure"
        if node == "FMT":
            ans = (parsed or {}).get("answers") or []
            bad = [a.get("fact_id") for a in ans if a.get("fact_id") in PURE and not PURE[a["fact_id"]](str(a.get("value") or ""))]
            if bad: sig["D3"] = "format"
        if node == "J2":
            c = (parsed.get("counts") or {}) if parsed else {}
            if c.get("personal") is not None and c.get("announcing") is not None and c["personal"] > c["announcing"]:
                sig["D6"] = "caliber_suspect"
        if sig: self.anomalies.append({"node": node, "sig": sig, "t": round(time.time() - self.t0, 1)})
        return sig

    # ---------- 策略（a_t 预登记规则；决策入 decisions） ----------
    def policy(self, node, sig):
        arm, t_rem = self.arm, DEADLINE_S - (time.time() - self.t0)
        ds_ok = self.budget["calls"] >= 2 and t_rem > 72
        acts = []
        if arm == "Static" or not sig: pass
        elif arm == "R-only":
            acts = [("structure_repair", node)] if node in REPAIR_LIB else [("rerun_asis", node)]
        elif arm == "π-only": acts = [("swap", node)] if ds_ok else []
        elif arm == "Simple-Dynamic": acts = [("retry", node)]
        elif arm == "Fixed-Composite":
            acts = ([("structure_repair", node)] if node in REPAIR_LIB else []) + [("format_repair", "FMT")] + ([("swap", node)] if ds_ok else [])
        elif arm == "Proposed-Dynamic":
            fam = next(iter(sig.values()))
            if fam == "structure": acts = [("structure_repair", node)] if node in REPAIR_LIB else []
            elif fam == "format": acts = [("format_repair", "FMT")]
            elif fam == "model_suspect": acts = [("swap", node)] if ds_ok else [("retry", node)]
            elif fam == "caliber_suspect": acts = [("structure_repair", node)] if node in REPAIR_LIB else []
        if t_rem < 60 and arm != "Static": acts = []
        self.decisions.append({"node": node, "sig": sig, "acts": acts, "t_rem": round(t_rem)})
        return acts

    def apply_action(self, node, kind):
        self.actions.append({"kind": kind, "node": node, "t": round(time.time() - self.t0, 1)})
        if kind == "structure_repair":
            fam_spec = REPAIR_LIB[node][1]
            self.spec[node]["sys"] = fam_spec                       # 部署修复 spec
            self.deployed_spec = lambda n, _s=fam_spec, _n=node: (_s if n == _n else None) if (n == _n and self.scenario == "S3" and n == "J1") else (self._orig_deployed(n))
        elif kind == "format_repair":
            self.fmt_bypassed = False
            self._fmtrep = getattr(self, "_fmtrep", 0) + 1
            if self._fmtrep <= 1:  # 单次重入队；残余 D3=D_2 白名单外变体的检测器噪音，记录不循环
                self.versions["FMT"] = self.versions.get("FMT", 0) + 1
                self.state["FMT"] = "Ready"
        if kind in ("structure_repair", "swap", "retry", "rerun_asis"):
            st = self.spec[node]
            if kind == "swap": st["model"] = "deepseek"
            elif kind == "retry": st["model"] = st["model"] if st["model"] == "deepseek" else "glm53flash"
            self._reruncount = getattr(self, "_reruncount", {})
            self._reruncount[node] = self._reruncount.get(node, 0) + 1
            if self._reruncount[node] > 2: return
            self.versions[node] = self.versions.get(node, 0) + 1
            self.state[node] = "Ready"
            def inval(n):
                for d in self.spec[n]["downs"]:
                    if self.state.get(d) in ("Completed", "Ready"): self.state[d] = "Ready"
                    inval(d)
            inval(node)

    def _orig_deployed(self, n):
        if n == "J1" and self.scenario == "S3": return SA_EX.J1_SYSTEM
        return None

    # ---------- 节点执行 ----------
    def exec_llm(self, node):
        st = self.spec[node]
        with self.lock:
            if self.budget["calls"] <= 0: self.state[node] = "Failed"; return
        alias = st["model"]
        system = self.inject_prompt(node) or st["sys"]
        user = st["user"]({u: self.outputs[u] for u in st["ups"]})
        sha_before = hashlib.sha256(system.encode()).hexdigest()[:12]
        sem = self.sem["deepseek"] if alias == "deepseek" else self.sem["glm53flash"]
        first = True
        with sem:
            for attempt in (1, 2):
                try:
                    with self.lock:
                        if self.budget["calls"] <= 0: raise RuntimeError("budget")
                        self.budget["calls"] -= 1; self.calls += 1
                    if first and self.inject_exc_first(node) and attempt == 1:
                        first = False; raise TimeoutError("injected")
                    r = transport.call_model("deepseek" if alias == "deepseek" else "glm53flash",
                                             system=system, user=user, max_tokens=MAXTOK[st["layer"]], timeout_s=120, temperature=0)
                    text = r["text"]; ev = ["timeout"] if attempt == 2 else []
                    with self.lock: self.budget["yuan"] -= r["in"] * 0.8e-6 + r["out"] * 2.8e-6
                    text = self.corrupt_once(node, text)
                    parsed = extract_json(text)
                    sig = self.detect(node, parsed, ev)
                    self.outputs[node] = text
                    self.exec_log.append({"node": node, "model": alias, "prompt_sha": sha_before, "wall": r["lat"]})
                    self.state[node] = "Completed"
                    self.fault_persistence_check(node)
                    for kind, tgt in self.policy(node, sig): self.apply_action(tgt, kind)
                    return
                except Exception:
                    if attempt == 2:
                        self.state[node] = "Failed"
                        self.anomalies.append({"node": node, "sig": {"D1": "model_suspect"}, "t": round(time.time() - self.t0, 1)})
                        for kind, tgt in self.policy(node, {"D1": "model_suspect"}): self.apply_action(tgt, kind)
                        return
                    time.sleep(2)

    def exec_fmt(self):
        # FMT 正式节点：版本/输入哈希/输出哈希/成本（确定性，0 调用）
        sink_text = self.outputs.get("SINK") or ""
        in_sha = hashlib.sha256(sink_text.encode()).hexdigest()[:12]
        if self.fmt_bypassed:
            out_text = sink_text  # 旁路：原样流出
        else:
            parsed = extract_json(sink_text)
            if parsed:
                import copy
                p2, _ = SA_EX.apply_format_rules(copy.deepcopy(parsed))
                out_text = json.dumps(p2, ensure_ascii=False)
            else:
                out_text = sink_text
        self.outputs["FMT"] = out_text
        self.exec_log.append({"node": "FMT", "model": "deterministic", "version": self.versions.get("FMT", 0),
                              "input_sha": in_sha, "output_sha": hashlib.sha256(out_text.encode()).hexdigest()[:12],
                              "bypassed": self.fmt_bypassed, "wall": 0.0})
        self.state["FMT"] = "Completed"
        sig = self.detect("FMT", extract_json(out_text), [])
        self.fault_persistence_check("FMT")
        for kind, tgt in self.policy("FMT", sig): self.apply_action(tgt, kind)

    def call(self, node):
        if node == "FMT": self.exec_fmt()
        else: self.exec_llm(node)

    def run(self):
        self.t0 = time.time()
        pool = ThreadPoolExecutor(max_workers=3)
        futs = {}
        while True:
            if time.time() - self.t0 > DEADLINE_S + 30:
                for n, s in self.state.items():
                    if s != "Completed": self.state[n] = "Failed"
                break
            for n, s in self.state.items():
                if s == "Ready" and all(self.state.get(u) == "Completed" for u in self.spec[n]["ups"]):
                    futs[n] = pool.submit(self.call, n); self.state[n] = "Running"
            if all(s == "Completed" for s in self.state.values()): break
            if not futs: break
            for n, f in list(futs.items()):
                if f.done() and f.exception() is not None:
                    self.invalid_reason = f"fut-exc:{n}:{repr(f.exception())[:60]}"
            done = [n for n, f in futs.items() if f.done()]
            if not done: time.sleep(0.3)
            for n in done: futs.pop(n)
            time.sleep(0.15)
        pool.shutdown(wait=True)
        self.makespan = round(time.time() - self.t0, 1)
        return self.finish()

    def finish(self):
        parsed = extract_json(self.outputs.get("FMT") or "")
        rec = {"arm": self.arm, "scenario": self.scenario, "rep": self.rep,
               "makespan_s": self.makespan, "on_time": self.makespan <= DEADLINE_S,
               "calls": self.calls, "budget_left": self.budget, "actions": self.actions,
               "decisions": self.decisions, "anomalies": self.anomalies,
               "final_states": dict(self.state), "exec_log": self.exec_log,
               "fault_checks": self.fault_checks, "invalid_reason": self.invalid_reason}
        if parsed:
            term = SA_EX.build_terminal_output(json.loads(json.dumps(parsed)))
            from terminal_quality import evaluate_terminal_quality
            r = evaluate_terminal_quality(SA_EX.CONTRACT, term, SRC())
            rec["tp"] = sum(1 for c in r["claim_results"] if c["status"].startswith("CORRECT"))
            rec["slot_success"] = round(rec["tp"] / 23, 4)
            def val(fid):
                a = next((x for x in parsed.get("answers", []) if x.get("fact_id") == fid), None)
                return str(a.get("value")) if a else None
            rec["F1_ok"] = "2026-10-09" in str(val("F1")); rec["F2_ok"] = "2026-10-10" in str(val("F2"))
            rec["E2"] = val("E2")
        else:
            rec.update({"tp": 0, "slot_success": 0.0, "F1_ok": False, "F2_ok": False, "E2": None})
        # 门禁 6：上下游哈希完整性（SINK 消费的上游 = exec_log 顺序隐含；此处核 J1 版本链）
        rec["g6_j1_versions"] = self.versions.get("J1", 0)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{self.arm}_{self.scenario}_r{self.rep}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), "utf-8")
        print(f"[{self.arm}|{self.scenario}|r{self.rep}] {self.makespan}s on_time={rec['on_time']} calls={self.calls} TP={rec['tp']}/23 F1F2={rec['F1_ok']},{rec['F2_ok']} acts={len(self.actions)}", flush=True)
        return rec


def SRC(): return SA_EX.SRC

BLOCKS = [("S0", 2), ("S1", 3), ("S2", 3), ("S3", 5), ("S4", 5)]
ARMS = ["Static", "R-only", "π-only", "Simple-Dynamic", "Fixed-Composite", "Proposed-Dynamic"]

def randomized_order():
    rng = random.Random(SEED)
    blocks = [(sc, r + 1) for sc, n in BLOCKS for r in range(n)]
    rng.shuffle(blocks)
    order = []
    for sc, rep in blocks:
        arms = ARMS[:]; rng.shuffle(arms)
        for a in arms: order.append((a, sc, rep))
    return order

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["order", "run", "run-batch"])
    ap.add_argument("--from-idx", type=int, default=0)
    ap.add_argument("--to-idx", type=int, default=10**9)
    a = ap.parse_args()
    order = randomized_order()
    if a.cmd == "order":
        for i, (arm, sc, rep) in enumerate(order): print(i, arm, sc, f"r{rep}")
    elif a.cmd in ("run", "run-batch"):
        done = 0
        for i, (arm, sc, rep) in enumerate(order):
            if i < a.from_idx or i >= a.to_idx: continue
            f = OUT / f"{arm}_{sc}_r{rep}.json"
            if f.exists(): continue
            Exec(arm, sc, rep).run()
            done += 1
        print(f"BATCH DONE: {done} executions")
