#!/usr/bin/env python3
"""RQ-DYN V5 确认性实验执行器：12任务 × 4配对 × 2策略 = 96次真实调用。
按冻结协议v1.0执行：300s截止、¥8上限、无期中分析。
"""
import json, os, time, hashlib, random, re, urllib.request
from pathlib import Path

DESIGN_DIR = Path("/root/research_outputs/RQ_DYN_V5_DESIGN_20261107")
STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
OUT_DIR = DESIGN_DIR / "v5_runs"
OUT_DIR.mkdir(exist_ok=True)

# ===== API 配置 =====
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

GLM_KEY = get_glm_key()
DS_KEY = get_ds_key()

GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DS_URL = "https://api.deepseek.com/chat/completions"

def call_model(model, system, user, max_tokens=4096, timeout=120):
    """统一的模型调用（GLM-5.3-Flash 或 DeepSeek）"""
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
        # OpenAI/DeepSeek格式: choices[0].message.content 为字符串
        if "choices" in d:
            text = d["choices"][0]["message"].get("content", "") or ""
            if not isinstance(text, str):
                text = "".join(b.get("text","") for b in text if isinstance(b, dict))
        # Anthropic/GLM格式: content 为块列表
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

# ===== 节点提示词构建 =====
def build_node_prompt(node_info, task_docs_text, upstream_outputs):
    """为DAG节点构建提示词"""
    kind = node_info.get("kind", "extract")
    role = node_info.get("role", "")

    system = f"你是精确的信息{kind}智能体。{role}。只输出一个JSON对象，不得编造。"

    if kind == "extract":
        user = f"请从以下文书中提取与'{role}'相关的所有事实。输出JSON：{{\"facts\": [{{\"fact\": \"...\", \"source\": \"...\"}}]}}\n\n文书内容：\n{task_docs_text[:6000]}"
    elif kind == "timeline":
        user = f"请基于以下上游事实构建时间线。输出JSON：{{\"timeline\": [{{\"date\": \"...\", \"event\": \"...\"}}]}}\n\n上游事实：\n{json.dumps(upstream_outputs, ensure_ascii=False)[:4000]}"
    elif kind in ("verification", "reason", "merge"):
        user = f"请核验以下上游事实的一致性与矛盾。输出JSON：{{\"verified\": [{{\"fact\": \"...\", \"status\": \"consistent|conflict|unverifiable\"}}]}}\n\n上游事实：\n{json.dumps(upstream_outputs, ensure_ascii=False)[:4000]}"
    else:  # report
        user = f"请综合以下上游事实生成最终结论。输出JSON：{{\"conclusions\": [{{\"fact\": \"...\", \"evidence\": \"...\"}}]}}\n\n上游事实：\n{json.dumps(upstream_outputs, ensure_ascii=False)[:4000]}"
    return system, user

# ===== 评分 =====
def norm(s):
    return re.sub(r'[\s,，、（）()〔〕\[\]""'']+', '', str(s))

def score_tp(output_text, slots):
    """对照Gold槽位评分"""
    flat = norm(output_text)
    tp = 0
    for slot in slots:
        val = norm(slot.get("value", ""))
        if not val or len(val) < 4:
            continue
        # 检查值是否出现在输出中
        if val in flat or any(norm(ae) in flat for ae in slot.get("allowed_expressions", []) if ae):
            tp += 1
        else:
            # 数值匹配：抽取输出中的数值
            nums_in_val = re.findall(r'[0-9][0-9,，.．%万元亿元]+', slot.get("value", ""))
            if nums_in_val and all(n.replace(",","").replace("，","") in flat.replace(",","").replace("，","") for n in nums_in_val if len(n) >= 4):
                tp += 1
    return tp

# ===== 异常注入 =====
def inject_anomaly(text, scenario, node_kind):
    """S3=结构异常(截断/乱序) S4=格式异常(编码/格式破坏)"""
    if not text: return text
    if scenario == "S3":
        # 结构异常：截断后半部分
        return text[:len(text)//3]
    elif scenario == "S4":
        # 格式异常：破坏JSON结构
        return text.replace("{", "[").replace("}", "]").replace("\"", "'")
    return text

# ===== 恢复策略 =====
def pd_recovery(anomaly_output, original_prompt, model, scenario):
    """Proposed-Dynamic: 根据异常类型选择恢复动作"""
    if not anomaly_output or "error" in anomaly_output:
        return call_model(model, original_prompt[0],
                          original_prompt[1] + "\n注意：输入可能存在异常，请谨慎处理。", timeout=120)
    # 检测格式异常（S4特征）
    if scenario == "S4" or anomaly_output.count("[") > anomaly_output.count("{"):
        return call_model(model, original_prompt[0],
                          f"以下输出存在格式异常，请修正后重新输出：\n{anomaly_output[:2000]}", timeout=120)
    # 检测结构异常（S3特征：截断）
    if scenario == "S3" or len(anomaly_output) < 50:
        return call_model(model, original_prompt[0], original_prompt[1], timeout=120)
    return anomaly_output

def fc_recovery(anomaly_output, original_prompt, model, scenario):
    """Fixed-Composite: 固定恢复动作（无论异常类型，统一重试+格式修正）"""
    return call_model(model, original_prompt[0],
                      f"以下内容可能有误，请基于原始任务重新输出：\n任务：{original_prompt[1][:2000]}\n可能有误的输出：{anomaly_output[:1000]}", timeout=120)

# ===== 主执行函数 =====
def execute_task(task_pkg, arm, scenario, pair_id, deadline_s=300):
    """执行一个任务的一次配对"""
    t0 = time.monotonic()
    dag = task_pkg["dag"]["nodes"]
    slots = task_pkg["slots"]
    docs = task_pkg.get("docs", {})

    # 读取文档
    doc_texts = {}
    for dn, di in docs.items():
        if os.path.exists(di["path"]):
            doc_texts[dn] = open(di["path"], encoding="utf-8", errors="ignore").read()[:4000]

    # 拓扑排序执行
    upstream = {}
    node_outputs = {}
    total_tokens_in = 0
    total_tokens_out = 0
    total_calls = 0
    total_cost = 0.0

    # 简单拓扑排序（按包内节点顺序，假设已排序）
    inject_node_idx = random.Random(pair_id * 100 + hash(arm) % 100).randint(0, len(dag)-1)

    for idx, node in enumerate(dag):
        if time.monotonic() - t0 > deadline_s:
            break

        node_name = node["node"]
        node_kind = node.get("kind", "extract")
        node_docs = node.get("docs", [])

        # 构建输入
        relevant_text = "\n".join(doc_texts.get(d, "") for d in node_docs if d in doc_texts)
        upstream_for_node = {k: v for k, v in upstream.items() if k in (node.get("upstream") or [])}

        system, user = build_node_prompt(node, relevant_text, upstream_for_node)

        # 选择模型：中间/终节点用GLM，其他用DeepSeek
        model = "glm-5.3-flash" if node_kind in ("verification", "report", "reason", "timeline") else "deepseek-chat"

        # 执行节点
        result = call_model(model, system, user, timeout=min(120, deadline_s - (time.monotonic()-t0)))
        total_calls += 1
        total_tokens_in += result.get("in", 0)
        total_tokens_out += result.get("out", 0)
        # 成本估算（GLM-5.3-Flash ~0.001/token, DeepSeek ~0.0005/token）
        total_cost += result.get("in", 0) * 0.000001 + result.get("out", 0) * 0.000002

        output = result.get("text", "")

        # 异常注入（在中间节点）
        if idx == inject_node_idx and idx > 0:
            corrupted = inject_anomaly(output, scenario, node_kind)

            # 恢复
            if arm == "Proposed-Dynamic":
                recovery = pd_recovery(corrupted, (system, user), model, scenario)
            else:  # Fixed-Composite
                recovery = fc_recovery(corrupted, (system, user), model, scenario)

            total_calls += 1
            total_tokens_in += recovery.get("in", 0)
            total_tokens_out += recovery.get("out", 0)
            total_cost += recovery.get("in", 0) * 0.000001 + recovery.get("out", 0) * 0.000002
            output = recovery.get("text", recovery if isinstance(recovery, str) else corrupted)

        node_outputs[node_name] = output
        upstream[node_name] = output

    # 终端评分
    terminal_output = node_outputs.get(dag[-1]["node"], "") if dag else ""
    # 也把所有节点输出拼接触发跨节点事实
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
    }

# ===== 主函数 =====
if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"

    # 加载随机化表
    rand_table = json.load(open(DESIGN_DIR / "RANDOMIZATION_TABLE.json"))

    # 加载12个任务包
    task_packages = {}
    for d in ["st_shun","e06_huanrui","e08_zhongtie","e04","e07c",
              "km","zd","zj","zed","md","cs","ls"]:
        import glob
        files = glob.glob(str(DESIGN_DIR / d / "V5_GOLD_*.json"))
        if files:
            p = json.load(open(files[0]))
            name = {"st_shun":"舜天","e06_huanrui":"E06","e08_zhongtie":"E08",
                    "e04":"E04","e07c":"E07C","km":"KM","zd":"ZD",
                    "zj":"ZJ","zed":"ZED","md":"MD","cs":"CS","ls":"LS"}[d]
            task_packages[name] = p

    print(f"任务包: {len(task_packages)}个")

    if mode == "smoke":
        # Smoke test: 1次执行
        test_task = task_packages["LS"]  # 最小任务
        print(f"\n=== SMOKE TEST: LS (乐视) ===")
        result = execute_task(test_task, "Proposed-Dynamic", "S3", 1)
        print(json.dumps(result, indent=1, ensure_ascii=False))

    elif mode == "full":
        # 完整96次执行
        all_results = []
        total_cost = 0
        start = time.time()

        for entry in rand_table["table"]:
            task_name = entry["task"]
            if task_name not in task_packages:
                continue
            pkg = task_packages[task_name]
            pair = entry["pair"]

            # S3/S4交替（每任务2个S3+2个S4）
            scenario = "S3" if pair <= 2 else "S4"

            # 按随机化表顺序执行
            for arm in [entry["first"], entry["second"]]:
                print(f"[{len(all_results)+1}/96] {task_name} pair{pair} {scenario} {arm}...", flush=True)
                r = execute_task(pkg, arm, scenario, pair)
                all_results.append(r)
                total_cost += r["cost_yuan"]
                print(f"  TP={r['tp']}/{r['n_slots']} ({r['tp_ratio']:.1%}) "
                      f"makespan={r['makespan_s']}s cost=¥{r['cost_yuan']:.4f}", flush=True)

                if total_cost > 8.0:
                    print(f"\n⚠️ 预算超限 ¥{total_cost:.2f} > ¥8.0，停止执行")
                    break

            # 保存中间结果
            json.dump(all_results, open(OUT_DIR/"results_partial.json","w"), indent=1, ensure_ascii=False)

        # 最终保存
        json.dump(all_results, open(OUT_DIR/"results_final.json","w"), indent=1, ensure_ascii=False)
        print(f"\n{'='*60}")
        print(f"执行完成: {len(all_results)}次 | 总成本: ¥{total_cost:.2f} | 耗时: {(time.time()-start)/60:.0f}分钟")

        # 快速统计
        pd_results = [r for r in all_results if r["arm"]=="Proposed-Dynamic"]
        fc_results = [r for r in all_results if r["arm"]=="Fixed-Composite"]
        print(f"PD: n={len(pd_results)} mean_TP={sum(r['tp'] for r in pd_results)/max(len(pd_results),1):.1f}")
        print(f"FC: n={len(fc_results)} mean_TP={sum(r['tp'] for r in fc_results)/max(len(fc_results),1):.1f}")
