#!/usr/bin/env python3
"""Stage D 真实动态 DAG 调度器（Tier D1，STAGE_D_PREREGISTRATION 冻结执行）。

真实并发（线程池+模型资源槽 K_glm=2/K_ds=1）、DAG 状态机（版本感知失效，已完成节点
不重复执行）、截止期/双限预算、故障注入（评估侧持标签，调度器盲）、在途检测器、
六臂动态策略 a_t=(Z_t,R_t,π_t)。
"""
import argparse, hashlib, json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SA = Path("/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, str(SA))
sys.path.insert(0, "/root/capital_opinion_pilot")
import transport
import executor as SA_EX  # stage_a 冻结提示词/适配器/格式层

HERE = Path(__file__).parent
OUT = HERE / "runs_d1"
DEADLINE_S = 180
BUDGET = {"calls": 12, "yuan": 0.15}
SLOTS = {"glm53flash": threading.Semaphore(2), "deepseek": threading.Semaphore(1)}
X1 = SA / "runs_x" / "run1"   # 冻结上游快照（E 层全文输入用合同，不需上游；此处仅取 E3/E4 语义无需——E 层每次真实执行）

CONTRACT, SRC = SA_EX.CONTRACT, SA_EX.SRC
J2_ORIG, J2_DIS = SA_EX.J2_SYSTEM, SA_EX.J2_SYSTEM + SA_EX.DISAMBIG_ADDENDUM
J1_FULL = SA_EX.J1_SYSTEM + SA_EX.RELAY_ADDENDUM + SA_EX.J1_POSITIONS_ADDENDUM
E_POS = SA_EX.E_SYSTEM + SA_EX.E_POSITION_ADDENDUM

def e_user(doc): return SA_EX.e_user(doc)

# ---- 节点规格：id, 模型, 提示词构造(上游文本 dict)->(system,user), 下游 ----
def spec():
    return {
        "E1": dict(model="glm53flash", layer="E", sys=E_POS, user=lambda u: e_user("E1"), ups=[], downs=["J1"]),
        "E2": dict(model="glm53flash", layer="E", sys=E_POS, user=lambda u: e_user("E2"), ups=[], downs=["J1"]),
        "E3": dict(model="glm53flash", layer="E", sys=SA_EX.E_SYSTEM, user=lambda u: e_user("E3"), ups=[], downs=["J2"]),
        "E4": dict(model="glm53flash", layer="E", sys=SA_EX.E_SYSTEM, user=lambda u: e_user("E4"), ups=[], downs=["J2"]),
        "J1": dict(model="glm53flash", layer="J1", sys=J1_FULL,
                   user=lambda u: SA_EX.j1_user(json.dumps({"E1": u["E1"], "E2": u["E2"]}, ensure_ascii=False)),
                   ups=["E1", "E2"], downs=["J2", "SINK"]),
        "J2": dict(model="glm53flash", layer="J2", sys=J2_DIS,
                   user=lambda u: SA_EX.j2_user(json.dumps({"J1": u["J1"], "E3": u["E3"], "E4": u["E4"]}, ensure_ascii=False)),
                   ups=["J1", "E3", "E4"], downs=["SINK"]),
        "SINK": dict(model="glm53flash", layer="SINK", sys=SA_EX.SINK_SYSTEM,
                     user=lambda u: SA_EX.sink_user(json.dumps({"J1": u["J1"], "J2": u["J2"]}, ensure_ascii=False)),
                     ups=["J1", "J2"], downs=[]),
    }

MAXTOK = {"E": 2000, "J1": 3000, "J2": 4000, "SINK": 4000}
FAULT_LABEL = {"S0": "none", "S1": "structure", "S2": "model_visible+caliber_hidden"}


def corrupt_positions(text):
    import re
    t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    d = json.loads(t[i:j + 1]); d.pop("positions", None)
    return json.dumps(d, ensure_ascii=False)


def extract_json(text):
    import re
    if not isinstance(text, str): return None
    t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i: return None
    try: return json.loads(t[i:j + 1])
    except json.JSONDecodeError: return None


class Exec:
    def __init__(self, arm, scenario):
        self.arm, self.scenario = arm, scenario
        self.spec = spec()
        self.state = {n: "Ready" for n in self.spec}
        self.outputs, self.versions = {}, {}
        self.budget = dict(BUDGET); self.t0 = None
        self.anomalies, self.actions, self.calls = [], [], 0
        self.lock = threading.Lock()
        self.sem = dict(SLOTS)

    # ---- 故障注入（调度器代码不可读 scenario 分支之外的信息；标签仅评估侧） ----
    def inject_prompt(self, node):
        if node == "J2" and self.scenario == "S2" and not getattr(self, "_s2_done", False):
            self._s2_done = True  # 一次性计划偏离（首次执行）；恢复重跑按策略指令
            return J2_ORIG
        return None

    def inject_exc_first(self, node):
        if node == "J2" and self.scenario == "S2" and not getattr(self, "_s2_to_done", False):
            self._s2_to_done = True  # 一次性超时注入（仅首次执行的首次尝试）
            return True
        return False

    def corrupt(self, node, text):
        if node == "E2" and self.scenario == "S1" and not getattr(self, "_s1_done", False):
            self._s1_done = True  # 一次性篡改（预注册口径：真实节点完成后确定性篡改一次）
            return corrupt_positions(text)
        return text

    # ---- 在途检测器 ----
    def detect(self, node, text, parsed, events):
        sig = {}
        if "parse_fail" in events or "timeout" in events: sig["D1"] = "model_suspect"
        if node in ("E1", "E2") and self.spec[node]["sys"] == E_POS and not (parsed or {}).get("positions"):
            sig["D2"] = "structure"
        if node == "J1" and not ((parsed or {}).get("dates_relay") and (parsed or {}).get("positions_relay")):
            sig["D2"] = "structure"
        if node == "J2":
            c = (parsed.get("counts") or {}) if parsed else {}
            if c.get("personal") is not None and c.get("announcing") is not None and c["personal"] > c["announcing"]:
                sig["D6"] = "caliber_suspect"
        if sig: self.anomalies.append({"node": node, "sig": sig, "t": time.time() - self.t0})
        return sig

    # ---- 策略（a_t=(Z,R,π)：返回重跑指令列表） ----
    def policy(self, node, sig):
        arm, t_rem = self.arm, DEADLINE_S - (time.time() - self.t0)
        crit_rem = 60.0  # 关键路径剩余估计（J2+SINK 最坏）
        ds_ok = self.budget["calls"] >= 2 and t_rem > crit_rem * 1.2
        acts = []
        if arm == "Static": return acts
        if not sig: return acts
        fam = next(iter(sig.values()))
        if arm == "R-only": acts = [("rerun", node, {"mode": "restore"})]
        elif arm == "π-only": acts = [("rerun", node, {"mode": "swap"})] if ds_ok else []
        elif arm == "Simple-Dynamic": acts = [("rerun", node, {"mode": "retry"})]
        elif arm == "Fixed-Composite":
            acts = [("rerun", node, {"mode": "restore"})] + ([("rerun", node, {"mode": "swap"})] if ds_ok else [])
        elif arm == "Proposed-Dynamic":
            if fam == "structure": acts = [("rerun", node, {"mode": "restore"})]
            elif fam == "caliber_suspect": acts = [("rerun", node, {"mode": "restore"})]
            elif fam == "model_suspect": acts = [("rerun", node, {"mode": "swap"})] if ds_ok else [("rerun", node, {"mode": "retry"})]
        # 截止期压力：放弃非必要恢复
        if t_rem < crit_rem * 1.0 and arm not in ("Static",):
            acts = []
        print(f"[POLICY {self.arm}|{node}|{sig}|t_rem={t_rem:.0f}] -> {acts}", flush=True)
        return acts

    def rerun_node(self, node, opts):
        """恢复执行：目标节点按指令重跑（restore=计划提示词原模型 / swap=换模 / retry=按被执行配置）；
        版本变化 → 仅下游失效重算（已完成无关节点不动）。"""
        self.actions.append({"node": node, **opts, "t": round(time.time() - self.t0, 1)})
        print(f"[RERUN {node}|{opts}]", flush=True)
        st = self.spec[node]
        override = {}
        if opts["mode"] == "restore":
            override = {"sys": st["sys"], "model": "glm53flash"}
        elif opts["mode"] == "swap":
            override = {"sys": st["sys"], "model": "deepseek"}
        elif opts["mode"] == "retry":
            exec_sys = self.inject_prompt(node) or st["sys"]
            override = {"sys": exec_sys, "model": "glm53flash"}
        self._reruncount = getattr(self, "_reruncount", {})
        self._reruncount[node] = self._reruncount.get(node, 0) + 1
        if self._reruncount[node] > 2: return  # 单节点恢复上限
        st.update(override)
        # 失效下游（版本感知）
        def inval(n):
            for d in self.spec[n]["downs"]:
                if self.state.get(d) in ("Completed", "Ready"):
                    self.state[d] = "Ready"  # 上游版本变化后重算
                inval(d)
        self.versions[node] = self.versions.get(node, 0) + 1
        self.state[node] = "Ready"
        inval(node)

    def call(self, node):
        st = self.spec[node]
        with self.lock:
            if self.budget["calls"] <= 0: self.state[node] = "Failed"; return
        alias = st["model"]
        system = self.inject_prompt(node) or st["sys"]
        ups = {u: self.outputs[u] for u in st["ups"]}
        user = st["user"](ups)
        sem_key = "deepseek" if alias == "deepseek" else "glm53flash"
        first = True
        with self.sem[sem_key]:
            for attempt in (1, 2):
                try:
                    with self.lock:
                        if self.budget["calls"] <= 0: raise RuntimeError("budget-exhausted")
                        self.budget["calls"] -= 1; self.calls += 1
                    if first and self.inject_exc_first(node) and attempt == 1:
                        first = False
                        raise TimeoutError("injected-timeout")
                    r = transport.call_model(alias if alias in ("deepseek",) else "glm53flash",
                                             system=system, user=user, max_tokens=MAXTOK[st["layer"]],
                                             timeout_s=120, temperature=0)
                    text = r["text"]; ev = []
                    if attempt == 2: ev.append("timeout")
                    with self.lock:
                        self.budget["yuan"] -= r["in"] * 0.8e-6 + r["out"] * 2.8e-6
                    parsed = extract_json(text)
                    text = self.corrupt(node, text)  # 故障注入（S1：完成后篡改）
                    parsed = extract_json(text) or parsed
                    sig = self.detect(node, text, parsed, ev)
                    self.outputs[node] = text
                    self.state[node] = "Completed"
                    for kind, target, opts in self.policy(node, sig):
                        self.rerun_node(target, opts)
                    return
                except Exception as e:
                    import traceback
                    if attempt == 2:
                        print(f"[EXC {node} attempt2]", repr(e)[:120], flush=True)
                        traceback.print_exc()
                        self.state[node] = "Failed"; self.anomalies.append({"node": node, "sig": {"D1": "model_suspect"}, "t": round(time.time() - self.t0, 1)})
                        for kind, target, opts in self.policy(node, {"D1": "model_suspect"}):
                            self.rerun_node(target, opts)
                        return
                    time.sleep(2)

    def run(self):
        self.t0 = time.time()
        pool = ThreadPoolExecutor(max_workers=3)
        futs = {}
        while True:
            el = time.time() - self.t0
            if el > DEADLINE_S + 30:  # 硬超时保护
                for n, s in self.state.items():
                    if s != "Completed": self.state[n] = "Failed"
                break
            progressed = False
            for n, stt in self.state.items():
                if stt == "Ready" and all(self.state.get(u) == "Completed" for u in self.spec[n]["ups"]):
                    futs[n] = pool.submit(self.call, n); self.state[n] = "Running"; progressed = True
            if all(s == "Completed" for s in self.state.values()): break
            if not futs:
                break
            for n, f in list(futs.items()):
                if f.done() and f.exception() is not None:
                    print(f"[FUT-EXC {n}]", repr(f.exception())[:120], flush=True)
            done_any = [n for n, f in futs.items() if f.done()]
            if not done_any and not progressed:
                time.sleep(0.3)
            for n in done_any: futs.pop(n)
            time.sleep(0.2)
        pool.shutdown(wait=True)
        self.makespan = round(time.time() - self.t0, 1)
        return self.finish()

    def finish(self):
        sink_text = self.outputs.get("SINK")
        parsed = extract_json(sink_text or "")
        rec = {"arm": self.arm, "scenario": self.scenario, "label": FAULT_LABEL[self.scenario],
               "node_outputs_sha": {n: hashlib.sha256(t.encode()).hexdigest()[:12] for n, t in self.outputs.items()},
               "makespan_s": self.makespan, "on_time": self.makespan <= DEADLINE_S,
               "calls": self.calls, "budget_left": self.budget,
               "actions": self.actions, "anomalies": self.anomalies,
               "final_states": dict(self.state)}
        if parsed:
            p2, log = SA_EX.apply_format_rules(json.loads(json.dumps(parsed)))
            term = SA_EX.build_terminal_output(p2)
            from terminal_quality import evaluate_terminal_quality
            r = evaluate_terminal_quality(CONTRACT, term, SRC)
            rec["tp"] = sum(1 for c in r["claim_results"] if c["status"].startswith("CORRECT"))
            rec["slot_success"] = round(rec["tp"] / 23, 4)
            rec["fmt_log"] = log
            e2v = next((str(a.get("value")) for a in p2.get("answers", []) if a.get("fact_id") == "E2"), None)
            a5v = next((str(a.get("value")) for a in p2.get("answers", []) if a.get("fact_id") == "A5"), None)
            rec["E2"] = e2v; rec["A5_sem"] = bool(a5v and "职务" in a5v)
        else:
            rec["tp"] = 0; rec["slot_success"] = 0.0
        (OUT / f"{self.arm}_{self.scenario}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), "utf-8")
        print(f"[{self.arm}|{self.scenario}] makespan={self.makespan}s on_time={rec['on_time']} calls={self.calls} "
              f"TP={rec['tp']}/23 E2={rec.get('E2')} A5含职务={rec.get('A5_sem')} actions={len(self.actions)}")
        return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["Static", "R-only", "π-only", "Simple-Dynamic", "Fixed-Composite", "Proposed-Dynamic"])
    ap.add_argument("scenario", choices=["S0", "S1", "S2"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    Exec(a.arm, a.scenario).run()
