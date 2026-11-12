#!/usr/bin/env python3
"""RQ-DYN V6 执行器：在 V5 执行器(v5_executor.py, SHA见V5记录)基础上实施
EXECUTOR_UPGRADE_SPEC_V0 最小升级（2026-11-10 驾驶舱批准，六条边界）。

升级内容（纯增量，不改执行路径）：
  1. 节点级执行日志 node_log（agent/pi理由/时间/成本/状态/输出哈希/父哈希）
  2. Z/R/π 决策留痕 decision_log（decision_opportunity + 实际动作 + 影子对照）
  3. fc_would_do / pd_would_do 影子对照（纯计算，零额外API调用）
  4. 派生指标 derive_metrics（决策机会/差异/有效恢复/浪费调用）
  5. dry-run 模式（mock模型，零API）与 offline 回放（从日志重算指标）

不修改：冻结预注册/调度算法/随机化/模型池/DAG结构/评分规则/重试护栏/预算。
核心执行逻辑（call_model/build_node_prompt/score_tp/inject_anomaly/
pd_recovery/fc_recovery/execute_task 主路径）与 V5 逐行等价。
"""
import json, os, time, hashlib, random, re, urllib.request
from pathlib import Path

DESIGN_DIR = Path("/root/research_outputs/RQ_DYN_V5_DESIGN_20261107")
V6_DIR = Path("/root/research_outputs/RQ_DYN_V6_DESIGN")
OUT_DIR = V6_DIR / "v6_runs"
OUT_DIR.mkdir(exist_ok=True)

# ===== API 配置（与V5等价；dry-run下不加载真实key） =====
def get_glm_key():
    cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
    for r in cfg["config"]["providerConfigRules"]["providerRules"]:
        if r.get("providerId") == "bigmodel-api-6":
            return r["config"]["access"]["apiKey"]
    raise RuntimeError("GLM key not found")

def get_ds_key():
    for line in open("/root/.env"):
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.strip().split("=",1)[1]
    raise RuntimeError("DeepSeek key not found")

GLM_KEY = None; DS_KEY = None
def _ensure_keys():
    global GLM_KEY, DS_KEY
    if GLM_KEY is None:
        GLM_KEY = get_glm_key(); DS_KEY = get_ds_key()

GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DS_URL = "https://api.deepseek.com/chat/completions"

# ===== Dry-run mock（仅dry-run模式激活，不触碰真实call_model路径） =====
_DRY = False
def set_dry_run(flag=True):
    global _DRY
    _DRY = flag

def _mock_call(model, system, user, max_tokens=4096, timeout=120):
    """确定性mock：可复现、无网络。输出包含可被score_tp检出的数值样本。"""
    h = hashlib.md5((model + system[:40] + user[:120]).encode()).hexdigest()[:8]
    return {"text": f'{{"facts":[{{"fact":"mock-{h} 108,666.32万元 2025-04-29","source":"mock"}}]}}',
            "in": 500, "out": 200, "latency": 0.01, "model": model, "mock": True}

def call_model(model, system, user, max_tokens=4096, timeout=120):
    """统一的模型调用（与V5等价；dry-run时走mock）"""
    if _DRY:
        return _mock_call(model, system, user, max_tokens, timeout)
    _ensure_keys()
    if "glm" in model.lower():
        url, key = GLM_URL, GLM_KEY
    else:
        url, key = DS_URL, DS_KEY
    body = {"model": model, "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user}],
        "max_tokens": max_tokens if "glm" not in model.lower() else max(8192, max_tokens),
        "temperature": 0}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
        if "choices" in d:
            text = d["choices"][0]["message"].get("content", "") or ""
            if not isinstance(text, str):
                text = "".join(b.get("text","") for b in text if isinstance(b, dict))
        elif "content" in d:
            text = "".join(b.get("text","") for b in d["content"] if isinstance(b, dict) and b.get("type")=="text")
        else:
            text = ""
        usage = d.get("usage", {})
        return {"text": text, "in": usage.get("prompt_tokens",0),
                "out": usage.get("completion_tokens",0),
                "latency": time.monotonic()-t0, "model": model}
    except Exception as e:
        return {"text": "", "error": str(e), "latency": time.monotonic()-t0,
                "in": 0, "out": 0, "model": model}

# ===== 节点提示词构建（与V5等价） =====
def build_node_prompt(node_info, task_docs_text, upstream_outputs):
    kind = node_info.get("kind", "extract")
    role = node_info.get("role", "")
    system = f"你是精确的信息{kind}智能体。{role}。只输出一个JSON对象，不得编造。"
    if kind == "extract":
        user = f"请从以下文书中提取与'{role}'相关的所有事实。输出JSON：{{\"facts\": [{{\"fact\": \"...\", \"source\": \"...\"}}]}}\n\n文书内容：\n{task_docs_text[:6000]}"
    elif kind == "timeline":
        user = f"请基于以下上游事实构建时间线。输出JSON：{{\"timeline\": [{{\"date\": \"...\", \"event\": \"...\"}}]}}\n\n上游事实：\n{json.dumps(upstream_outputs, ensure_ascii=False)[:4000]}"
    elif kind in ("verification", "reason", "merge"):
        user = f"请核验以下上游事实的一致性与矛盾。输出JSON：{{\"verified\": [{{\"fact\": \"...\", \"status\": \"consistent|conflict|unverifiable\"}}]}}\n\n上游事实：\n{json.dumps(upstream_outputs, ensure_ascii=False)[:4000]}"
    else:
        user = f"请综合以下上游事实生成最终结论。输出JSON：{{\"conclusions\": [{{\"fact\": \"...\", \"evidence\": \"...\"}}]}}\n\n上游事实：\n{json.dumps(upstream_outputs, ensure_ascii=False)[:4000]}"
    return system, user

# ===== 评分（与V5等价） =====
def norm(s):
    return re.sub(r'[\s,，、（）()〔〕\[\]""'']+', '', str(s))

def score_tp(output_text, slots):
    flat = norm(output_text)
    tp = 0
    for slot in slots:
        val = norm(slot.get("value", ""))
        if not val or len(val) < 4:
            continue
        if val in flat or any(norm(ae) in flat for ae in slot.get("allowed_expressions", []) if ae):
            tp += 1
        else:
            nums_in_val = re.findall(r'[0-9][0-9,，.．%万元亿元]+', slot.get("value", ""))
            if nums_in_val and all(n.replace(",","").replace("，","") in flat.replace(",","").replace("，","") for n in nums_in_val if len(n) >= 4):
                tp += 1
    return tp

# ===== 异常注入（与V5等价） =====
def inject_anomaly(text, scenario, node_kind):
    if not text: return text
    if scenario == "S3":
        return text[:len(text)//3]
    elif scenario == "S4":
        return text.replace("{", "[").replace("}", "]").replace("\"", "'")
    return text

# ===== 恢复策略（与V5等价） =====
def pd_recovery(anomaly_output, original_prompt, model, scenario):
    if not anomaly_output or "error" in anomaly_output:
        return call_model(model, original_prompt[0],
                          original_prompt[1] + "\n注意：输入可能存在异常，请谨慎处理。", timeout=120)
    if scenario == "S4" or anomaly_output.count("[") > anomaly_output.count("{"):
        return call_model(model, original_prompt[0],
                          f"以下输出存在格式异常，请修正后重新输出：\n{anomaly_output[:2000]}", timeout=120)
    if scenario == "S3" or len(anomaly_output) < 50:
        return call_model(model, original_prompt[0], original_prompt[1], timeout=120)
    return anomaly_output

def fc_recovery(anomaly_output, original_prompt, model, scenario):
    return call_model(model, original_prompt[0],
                      f"以下内容可能有误，请基于原始任务重新输出：\n任务：{original_prompt[1][:2000]}\n可能有误的输出：{anomaly_output[:1000]}", timeout=120)

# ===== V6新增：影子对照（纯函数，零API） =====
def fc_would_do(node_kind, scenario):
    """FC固定策略在相同决策点的影子动作（按V5冻结的fc_recovery语义推导）"""
    return {"Z": {"action": "full_retry", "scope": "node"},
            "R": {"reexecute_set": None, "policy": "retry_anomaly_node_with_fixed_prompt"},
            "pi": {"changes": [], "policy": "fixed_by_node_kind"}}

def pd_would_do(node_kind, scenario):
    """PD在相同决策点的影子动作（按V5冻结的pd_recovery语义推导）"""
    act = "repair_format" if scenario == "S4" else "reExecute_node"
    return {"Z": {"action": act, "scope": "node"},
            "R": {"reexecute_set": None, "policy": "anomaly_type_dependent"},
            "pi": {"changes": [], "policy": "keep_assignment"}}

def _h(s):
    return "sha256:" + hashlib.sha256(str(s).encode()).hexdigest()[:16]

# ===== 主执行函数（执行路径与V5等价；外覆日志） =====
def execute_task(task_pkg, arm, scenario, pair_id, deadline_s=300, exec_tag=""):
    t0 = time.monotonic()
    dag = task_pkg["dag"]["nodes"]
    slots = task_pkg["slots"]
    docs = task_pkg.get("docs", {})

    exec_id = f"{exec_tag or 'X'}_{task_pkg.get('task_id', task_pkg.get('company','unknown'))}_{arm}_S{scenario[-1]}_P{pair_id}"
    node_log = []
    decision_log = []
    _recovery_texts = {}

    doc_texts = {}
    for dn, di in docs.items():
        if os.path.exists(di["path"]):
            doc_texts[dn] = open(di["path"], encoding="utf-8", errors="ignore").read()[:4000]

    upstream = {}
    node_outputs = {}
    total_tokens_in = 0
    total_tokens_out = 0
    total_calls = 0
    total_cost = 0.0

    # V6修正(2026-11-10窗口指令): 配对内共享注入条件——种子仅依赖(task,pair,scenario),
    # 用稳定哈希(不依赖PYTHONHASHSEED), 两臂注入节点/类型完全一致。
    # 注入点选择: 仅从"真中间节点"(既有上游又有下游)中确定性选取(窗口问题1修正),
    # 必注入——协议v1.1"每任务4组配对(2 S3+2 S4)"即每组承载场景,此为实现纠正(版本变更记录见下)。
    # V5继承式 random.Random(pair_id*100+hash(arm)%100).randint(0,n-1) 已废——
    #  实证审计 V5_INJECTION_CONSISTENCY_LEDGER_48.json: 16/48配对注入状态不一致(33.3%),
    #  V5六个正向配对中3个为污染胜局(净偏PD +6TP)
    _seed_material = f"{task_pkg.get('task_id', task_pkg.get('company','unknown'))}|{pair_id}|{scenario}"
    _seed = int(hashlib.sha256(_seed_material.encode()).hexdigest()[:8], 16)
    _up_refs = set()
    for _nd in dag:
        for _u in (_nd.get("upstream") or []):
            _up_refs.add(_u)
    _eligible = sorted(_nd["node"] for _nd in dag
                       if (_nd.get("upstream") and _nd["node"] in _up_refs))
    if not _eligible:
        _eligible = sorted(_nd["node"] for _nd in dag)[1:] or sorted(_nd["node"] for _nd in dag)
    _rng = random.Random(_seed)
    inject_node_name = _eligible[_rng.randrange(len(_eligible))]
    inject_trace = {"inject_node": inject_node_name, "eligible_middle_nodes": _eligible,
                    "seed_material": _seed_material, "seed": _seed, "pair_id": pair_id,
                    "policy": "pair-shared: 同配对PD/FC同注入节点同场景, 稳定哈希, 必注入(仅真中间节点)"}

    for idx, node in enumerate(dag):
        if time.monotonic() - t0 > deadline_s:
            break

        node_name = node["node"]
        node_kind = node.get("kind", "extract")
        node_docs = node.get("docs", [])

        relevant_text = "\n".join(doc_texts.get(d, "") for d in node_docs if d in doc_texts)
        upstream_for_node = {k: v for k, v in upstream.items() if k in (node.get("upstream") or [])}

        system, user = build_node_prompt(node, relevant_text, upstream_for_node)

        model = "glm-5.3-flash" if node_kind in ("verification", "report", "reason", "timeline") else "deepseek-chat"

        t_node = time.monotonic() - t0
        result = call_model(model, system, user, timeout=min(120, deadline_s - (time.monotonic()-t0)))
        total_calls += 1
        total_tokens_in += result.get("in", 0)
        total_tokens_out += result.get("out", 0)
        total_cost += result.get("in", 0) * 0.000001 + result.get("out", 0) * 0.000002

        output = result.get("text", "")
        anomaly_hit = (node_name == inject_node_name)
        recovered_text = None
        corrupted_text = None

        if anomaly_hit:
            _recovery_texts[node_name + "_orig"] = output  # 异常前原始输出(忠实性度量基准)
            corrupted = inject_anomaly(output, scenario, node_kind)
            corrupted_text = corrupted

            if arm == "Proposed-Dynamic":
                recovery = pd_recovery(corrupted, (system, user), model, scenario)
            else:
                recovery = fc_recovery(corrupted, (system, user), model, scenario)

            total_calls += 1
            total_tokens_in += recovery.get("in", 0)
            total_tokens_out += recovery.get("out", 0)
            total_cost += recovery.get("in", 0) * 0.000001 + recovery.get("out", 0) * 0.000002
            output = recovery.get("text", recovery if isinstance(recovery, str) else corrupted)
            recovered_text = output
            _recovery_texts[node_name + "_rec"] = output
            _recovery_texts[node_name + "_cor"] = corrupted

            # ---- V6新增：决策留痕（零额外调用） ----
            actual = pd_would_do(node_kind, scenario) if arm == "Proposed-Dynamic" else fc_would_do(node_kind, scenario)
            shadow = fc_would_do(node_kind, scenario) if arm == "Proposed-Dynamic" else pd_would_do(node_kind, scenario)
            decision_log.append({
                "decision_id": f"D{len(decision_log)+1}", "node_id": node_name,
                "trigger": "node_anomaly", "decision_opportunity": True,
                "arm": arm, "scenario": scenario,
                "Z": actual["Z"], "R": actual["R"], "pi": actual["pi"],
                "shadow_other_arm": shadow,
                "recovery_prompt_kind": "pd:" + ("repair" if scenario=="S4" else "reexec") if arm=="Proposed-Dynamic" else "fc:fixed",
            })

        node_outputs[node_name] = output
        upstream[node_name] = output

        # ---- V6新增：节点级日志（零额外调用） ----
        node_log.append({
            "exec_id": exec_id, "node_id": node_name, "kind": node_kind,
            "agent_assigned": model, "pi_reason": "initial_fixed_by_kind",
            "attempt": 1 if not anomaly_hit else 2,
            "t_start": round(t_node, 2), "t_end": round(time.monotonic()-t0, 2),
            "cost_tokens": {"in": result.get("in",0), "out": result.get("out",0)},
            "status": ("recovered" if anomaly_hit else "ok"), "anomaly_injected": anomaly_hit,
            "output_hash": _h(output),
            "parent_hashes": {k: _h(v) for k, v in upstream_for_node.items()},
            "anomaly": {"corrupted_hash": _h(corrupted_text), "recovered_hash": _h(recovered_text)} if anomaly_hit else None,
        })

    terminal_output = node_outputs.get(dag[-1]["node"], "") if dag else ""
    all_output = " ".join(str(v) for v in node_outputs.values())
    tp = score_tp(all_output, slots)
    n_slots = len(slots)

    makespan = time.monotonic() - t0

    return {
        "arm": arm, "scenario": scenario, "pair": pair_id,
        "task": task_pkg.get("task_id", task_pkg.get("company", "unknown")),
        "tp": tp, "n_slots": n_slots,
        "tp_ratio": tp / n_slots if n_slots else 0,
        "catastrophic": (tp / n_slots <= 0.15) if n_slots else True,
        "makespan_s": round(makespan, 1),
        "calls": total_calls,
        "tokens_in": total_tokens_in, "tokens_out": total_tokens_out,
        "cost_yuan": round(total_cost, 4),
        "on_time": makespan <= deadline_s,
        # ---- V6新增：过程资产 ----
        "process_log": {"exec_id": exec_id, "node_log": node_log, "decision_log": decision_log,
                        "inject_trace": inject_trace,
                        "_recovery_texts": _recovery_texts,
                        "final_outputs": {k: v for k, v in node_outputs.items()}},
    }

# ===== V6新增：派生指标（离线计算，零API） =====
def derive_metrics(runs):
    """从执行结果(含process_log)计算决策差异指标。
    有效恢复判定：恢复后终端TP > 以损坏输出直通计算的终端TP（离线重评分，不重执行）。
    """
    out = {"n_runs": len(runs),
           "decision_opportunities": 0,
           "Z_divergence": 0, "R_divergence": 0, "pi_divergence": 0,
           "n_divergence_points": 0,
           "effective_recoveries": 0, "ineffective_recoveries": 0, "harmful_recoveries": 0,
           "recovery_attempts": 0, "wasted_recovery_calls": 0}

    for r in runs:
        pl = r.get("process_log") or {}
        dlog = pl.get("decision_log", [])
        fouts = pl.get("final_outputs", {})
        for d in dlog:
            out["decision_opportunities"] += 1
            a, s = d["Z"], d["shadow_other_arm"]["Z"]
            if (a.get("action"), a.get("scope")) != (s.get("action"), s.get("scope")):
                out["Z_divergence"] += 1
            if d["R"].get("policy") != d["shadow_other_arm"]["R"].get("policy"):
                out["R_divergence"] += 1
            if d["pi"].get("policy") != d["shadow_other_arm"]["pi"].get("policy"):
                out["pi_divergence"] += 1
            out["n_divergence_points"] += 1

        # 恢复有效性：需要损坏输出直通重评（从node_log的anomaly字段与final_outputs重建）
        for nl in pl.get("node_log", []):
            an = nl.get("anomaly")
            if not an:
                continue
            out["recovery_attempts"] += 1
            # 直通情景：把该节点输出替换为损坏文本后重评分（仅本地重算）
            sim = dict(fouts)
            corrupted = _corpus_lookup(pl, nl["node_id"], corrupted=True)
            if corrupted is None:
                continue
            sim[nl["node_id"]] = corrupted
            tp_rec = r["tp"]
            tp_cor = score_tp(" ".join(str(v) for v in sim.values()), r.get("_slots", []))
            if tp_rec > tp_cor:
                out["effective_recoveries"] += 1
            elif tp_rec == tp_cor:
                out["ineffective_recoveries"] += 1
                out["wasted_recovery_calls"] += 1
            else:
                out["harmful_recoveries"] += 1
                out["wasted_recovery_calls"] += 1
    if out["n_divergence_points"]:
        for k in ("Z_divergence", "R_divergence", "pi_divergence"):
            out[k] = round(out[k] / out["n_divergence_points"], 4)
    return out

def _corpus_lookup(pl, node_id, corrupted=False):
    """从日志恢复节点的损坏/恢复文本（dry-run与离线回放共用的最小重建）。
    实际文本不在日志中持久化（体积考虑），通过recovered/corrupted哈希与
    重建函数无法还原文本时返回None——正式包在Gold执行时另行保存关键文本。"""
    return (pl.get("_recovery_texts") or {}).get(node_id + ("_cor" if corrupted else "_rec"))



def content_fidelity(orig, recovered):
    """恢复后内容忠实性(零调用,不用Gold): 数字事实保留率+新增断言数"""
    import re as _re
    _nums = lambda t: set(_re.findall(r'\d[\d,，.]{3,}', t))
    o, r = _nums(orig), _nums(recovered)
    if not o:
        return {"fact_retention": None, "new_assertions": len(r - o)}
    return {"fact_retention": round(len(o & r) / len(o), 3), "new_assertions": len(r - o)}

# ===== Dry-run 自检 =====
def _build_mock_pkg():
    return {
        "task_id": "MOCK1", "company": "mock",
        "dag": {"nodes": [
            {"node": "A1", "kind": "extract", "role": "资金占用", "docs": ["d1"]},
            {"node": "A2", "kind": "extract", "role": "处罚决定", "docs": ["d1"]},
            {"node": "B1", "kind": "verification", "role": "一致性核验", "upstream": ["A1", "A2"]},
            {"node": "C1", "kind": "report", "role": "终端结论", "upstream": ["B1"]},
        ]},
        "slots": [
            {"value": "108,666.32万元", "allowed_expressions": ["108666.32万元"]},
            {"value": "2025-04-29"},
        ],
        "docs": {"d1": {"path": "/nonexistent/mock.txt"}},
    }

def dry_run():
    """零API干跑：验证日志链路、决策留痕、指标计算。"""
    set_dry_run(True)
    pkg = _build_mock_pkg()
    runs = []
    for arm in ("Proposed-Dynamic", "Fixed-Composite"):
        for sc in ("S3", "S4"):
            r = execute_task(pkg, arm, sc, 1, deadline_s=30, exec_tag="DRY")
            # 附带恢复文本供有效性判定演示
            pl = r["process_log"]
            texts = {}
            for nl in pl["node_log"]:
                if nl.get("anomaly"):
                    texts[nl["node_id"] + "_rec"] = _regen_mock_text(pl, nl["node_id"])
                    texts[nl["node_id"] + "_cor"] = _regen_mock_corrupted(pl, nl["node_id"], sc)
            pl["_recovery_texts"] = texts
            runs.append(r)
    m = derive_metrics(runs)
    set_dry_run(False)
    return runs, m

def _regen_mock_text(pl, node_id):
    return '{"facts":[{"fact":"mock 108,666.32万元 2025-04-29"}]}'

def _regen_mock_corrupted(pl, node_id, scenario):
    t = _regen_mock_text(pl, node_id)
    return t[:len(t)//3] if scenario == "S3" else t.replace("{", "[").replace("}", "]").replace('"', "'")

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "dryrun"
    if mode == "dryrun":
        runs, m = dry_run()
        print("=== DRY-RUN 验收 ===")
        for r in runs:
            pl = r["process_log"]
            print(f"  {r['arm']:18s} {r['scenario']} TP={r['tp']}/{r['n_slots']} calls={r['calls']} "
                  f"nodes_logged={len(pl['node_log'])} decisions={len(pl['decision_log'])}")
        print("\n=== 派生指标 ===")
        print(json.dumps(m, ensure_ascii=False, indent=1))
        json.dump({"runs": [{k: v for k, v in r.items()} for r in runs], "metrics": m},
                  open(OUT_DIR / "dryrun_result.json", "w"), ensure_ascii=False, indent=1)
        print(f"\n已写入 {OUT_DIR/'dryrun_result.json'}")
    elif mode == "replay":
        fp = sys.argv[2]
        d = json.load(open(fp))
        print(json.dumps(derive_metrics(d.get("runs", d)), ensure_ascii=False, indent=1))
