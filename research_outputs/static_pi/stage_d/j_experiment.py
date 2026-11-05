#!/usr/bin/env python3
"""J 节点最小真实对照实验（授权 2026-11-04；~45-50 调用）。

任务：MVR1 舜天（16 槽，7 个主体-罚款金额配对——J 节点核心目标场景）
臂：Baseline E→V→SINK vs Treatment E→J→V→SINK
rep：3 次（共享 E 输出）

GO 门：J_EXPERIMENT_GO=1
"""
import json, os, sys, time, random, re, hashlib
import urllib.request
from pathlib import Path

STAGE_A = Path("/root/research_outputs/static_pi/stage_a")
STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE_A))
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, "/root/capital_opinion_pilot")

import transport
from executor import extract_json

OUT = STAGE_D / "j_experiment_runs"
GOLD_PATH = "/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
REPS = 3

# ===== 提示词 =====
E_SYSTEM = ("你是精确的处罚文书抽取器。只输出 JSON：{\"parties\": [{name, penalty_amount, "
            "penalty_type, market_ban, quote}], \"doc_numbers\": {...}, \"dates\": {...}, "
            "\"totals\": {..., all_parties_total}, \"facts\": [{item, value, quote}]}。"
            "每个金额必须标注对应的当事人姓名（从原文中逐字找到）。不得编造。")

J_SYSTEM = ("你是主体-数值关系配对器。给定上游抽取结果和任务槽位列表，你的唯一任务是：\n"
            "1. 将每个金额精确配对到正确的当事人\n"
            "2. 计算全部当事人罚款合计\n"
            "3. 标记任何你不确定的配对（confidence: low）\n"
            "只输出 JSON：{\"pairings\": [{fact_id, subject, value, confidence, evidence_quote}], "
            "\"derived\": [{fact_id, value, computation}]}\n"
            "配对必须基于上游抽取中的 quote 证据，不得凭记忆。")

V_SYSTEM = ("你是事实核验器。检查上游配对结果：数值是否与证据一致、主体是否正确、合计是否等于各部分之和。"
            "只输出 JSON：{\"verified\": [{fact_id, status: VERIFIED|CORRECTED|UNCERTAIN, "
            "final_value, correction_note}]}")

SINK_SYSTEM = ("你是严谨的最终答案汇总器。只输出 JSON：{\"answers\": [{fact_id, value, quote, doc}], "
               "\"unknown_slots\": []}。不得使用给定上游材料之外的任何信息。")


def glm_low(system, user, max_tokens=8192, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    if not key: raise RuntimeError("STAGE_D_GLM_KEY not set")
    body = {"model": "GLM-5.3-Flash", "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}], "reasoning_effort": "low"}
    req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", key)
    req.add_header("authorization", "Bearer " + key)
    req.add_header("anthropic-version", "2023-06-01")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    return {"text": "".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text"),
            "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
            "stop": d.get("stop_reason"), "lat": round(time.monotonic()-t0, 2)}

def ds_call(system, user, max_tokens=4000, timeout_s=300):
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic()-t0, 2)
    return r

def do_call(name, backend, system, user, cap=4000):
    r = glm_low(system, user, cap) if backend == "glm" else ds_call(system, user, cap)
    ok = r.get("stop") in ("end_turn","stop",None) and bool(r.get("text","").strip())
    print(f"  {name}({backend}): stop={r.get('stop')} in={r.get('in')} out={r.get('out')} "
          f"wall={r.get('lat')}s ok={ok}", flush=True)
    return r, ok


def load_gold():
    c = json.load(open(GOLD_PATH))
    return c, c["required_facts"], c.get("source_pages", {})


def build_e_user(question, doc_text):
    return f"任务问题：{question}\n\n文书全文：\n{doc_text}\n\n请按系统约定抽取全部信息。"


def build_j_user(slots_json, e_output):
    return (f"以下是上游抽取结果：\n{e_output}\n\n"
            f"任务槽位列表（每个槽位需要配对正确的主体和数值）：\n{slots_json}\n\n"
            f"请完成主体-数值配对。按系统约定输出。")


def build_v_user(j_output_or_e, slots_json):
    return (f"以下是上游结果：\n{j_output_or_e}\n\n"
            f"槽位列表：\n{slots_json}\n\n请核验并按系统约定输出。")


def build_sink_user(v_output, slots_json, question):
    return (f"任务问题：{question}\n\n核验结果：\n{v_output}\n\n"
            f"输出格式：answers 逐槽位填写 {{\"fact_id\":..., \"value\":..., \"quote\":..., \"doc\":\"D1\"}}。\n"
            f"槽位：{slots_json}\n无法确定项列入 unknown_slots。")


def score_answers(answers, gold_facts):
    """粗评分：值前缀匹配 + 主体-数值配对检查。"""
    gold_map = {f['fact_id']: f for f in gold_facts}
    hits = 0; pairing_hits = 0; pairing_total = 0
    for a in answers or []:
        fid = a.get('fact_id')
        if fid not in gold_map: continue
        g = gold_map[fid]
        gv = str(g.get('value',''))
        av = str(a.get('value',''))
        # 值匹配（去千分位/单位）
        def norm(v):
            v = re.sub(r'[,，\s万元亿元]','',v)
            m = re.search(r'[\d.]+', v)
            try: return float(m.group()) if m else None
            except: return None
        gn, an = norm(gv), norm(av)
        if gn is not None and an is not None and abs(gn-an)<0.01:
            hits += 1
        # 主体-数值配对（只对有 subject 的槽位）
        if g.get('subject') and '罚款' in str(g.get('predicate','')):
            pairing_total += 1
            if gn is not None and an is not None and abs(gn-an)<0.01:
                pairing_hits += 1
    return {"value_hits": hits, "n_facts": len(gold_facts),
            "value_rate": round(hits/len(gold_facts), 4),
            "pairing_hits": pairing_hits, "pairing_total": pairing_total,
            "pairing_rate": round(pairing_hits/pairing_total, 4) if pairing_total else None}


def run_arm(arm, rep, E_text, slots_json, question):
    calls = []
    if arm == "treatment":
        # J 节点（独立配对步骤）
        r, ok = do_call("J", "glm", J_SYSTEM, build_j_user(slots_json, E_text), 8192)
        calls.append({"node": "J", "ok": ok, **{k: r.get(k) for k in ("in","out","lat","stop")}})
        if not ok:
            return {"arm": arm, "rep": rep, "status": "J_FAILED", "calls": calls}
        j_out = r["text"]
    else:
        j_out = E_text  # Baseline: 直接传 E 输出

    # V 节点（核验）
    r, ok = do_call("V", "ds", V_SYSTEM, build_v_user(j_out, slots_json))
    calls.append({"node": "V", "ok": ok, **{k: r.get(k) for k in ("in","out","lat","stop")}})
    if not ok:
        return {"arm": arm, "rep": rep, "status": "V_FAILED", "calls": calls}
    v_out = r["text"]

    # SINK
    r, ok = do_call("SINK", "ds", SINK_SYSTEM, build_sink_user(v_out, slots_json, question))
    calls.append({"node": "SINK", "ok": ok, **{k: r.get(k) for k in ("in","out","lat","stop")}})
    ps = extract_json(r["text"]) if ok else None
    answers = (ps or {}).get("answers", [])

    return {"arm": arm, "rep": rep, "status": "COMPLETE" if ok else "SINK_FAILED",
            "calls": calls, "answers": answers,
            "sink_text": r["text"][:500] if ok else ""}


def main():
    if os.environ.get("J_EXPERIMENT_GO") != "1":
        raise SystemExit("REFUSED: requires J_EXPERIMENT_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)

    gold, facts, source_pages = load_gold()
    question = gold.get("question", "")
    slots_json = json.dumps([{"fact_id": f["fact_id"], "subject": f.get("subject",""),
                              "predicate": f.get("predicate","")} for f in facts], ensure_ascii=False)

    # 合并全部文书
    doc_text = ""
    for doc_id, doc in source_pages.items():
        for page in doc.get("pages", {}).values():
            doc_text += page.get("text", "")

    all_results = []
    total_calls = 0

    for rep in range(1, REPS + 1):
        # 共享 E（每 rep 一次）
        r_e, ok_e = do_call(f"E_r{rep}", "glm", E_SYSTEM, build_e_user(question, doc_text), 8192)
        total_calls += 1
        if not ok_e:
            print(f"  E r{rep} FAILED, skipping rep"); continue
        E_text = r_e["text"]

        # 两臂（随机顺序）
        arms = ["baseline", "treatment"]
        random.Random(20261104+rep).shuffle(arms)
        for arm in arms:
            result = run_arm(arm, rep, E_text, slots_json, question)
            total_calls += len(result.get("calls", []))
            if result["status"] == "COMPLETE":
                sc = score_answers(result["answers"], facts)
                result["score"] = sc
                print(f"  [{arm}|r{rep}] value={sc['value_hits']}/{sc['n_facts']} "
                      f"pairing={sc['pairing_hits']}/{sc['pairing_total']}", flush=True)
            else:
                result["score"] = {"value_hits": 0, "n_facts": len(facts)}
            all_results.append(result)

    # 分析
    from collections import defaultdict
    import statistics as st
    groups = defaultdict(list)
    for r in all_results:
        if r["status"] == "COMPLETE":
            groups[r["arm"]].append(r["score"])

    print(f"\n{'='*60}")
    print(f"总调用: {total_calls}")
    for arm in ("baseline", "treatment"):
        scores = groups[arm]
        if not scores: continue
        vr = [s["value_rate"] for s in scores]
        pr = [s["pairing_rate"] for s in scores if s.get("pairing_rate") is not None]
        print(f"\n{arm}: n={len(scores)}")
        print(f"  值正确率: {st.mean(vr):.3f} (±{st.stdev(vr):.3f})" if len(vr)>1 else f"  值正确率: {vr}")
        if pr: print(f"  配对正确率: {st.mean(pr):.3f}" if len(pr)>1 else f"  配对正确率: {pr}")

    # 配对差
    if groups["baseline"] and groups["treatment"]:
        b_v = st.mean([s["value_rate"] for s in groups["baseline"]])
        t_v = st.mean([s["value_rate"] for s in groups["treatment"]])
        print(f"\n  ΔQ (treatment - baseline) = {t_v - b_v:+.3f}")
        b_p_vals = [s.get("pairing_rate") for s in groups["baseline"] if s.get("pairing_rate") is not None]
        t_p_vals = [s.get("pairing_rate") for s in groups["treatment"] if s.get("pairing_rate") is not None]
        if b_p_vals and t_p_vals:
            print(f"  ΔPairing = {st.mean(t_p_vals) - st.mean(b_p_vals):+.3f}")

    (OUT / "J_EXPERIMENT_RESULTS.json").write_text(
        json.dumps({"results": all_results, "total_calls": total_calls}, ensure_ascii=False, indent=1), "utf-8")
    print(f"\n结果已保存 J_EXPERIMENT_RESULTS.json")


if __name__ == "__main__":
    main()
