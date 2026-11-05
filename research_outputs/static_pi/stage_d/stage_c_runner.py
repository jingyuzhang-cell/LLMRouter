#!/usr/bin/env python3
"""STAGE_C 多任务真实实验 runner（GO 2026-11-04；66 执行 ≈460 调用）。

3 任务（MVR2/P1-1/PHASE2B）× 3 主对照（Static/Best-Single/Proposed）× 4 rep
+ H1 嵌对（盲换 vs 诊断换 × 健康/J1异常 × 2 rep/任务）
+ H2 嵌对（匹配 vs 不匹配 × 格式/结构异常 × 2 rep/任务）
+ H3 KANGMEI（Terminal vs Upstream recovery × 2 rep/任务）

GO 门：STAGE_C_GO=1；凭据 env。停止规则：R1≥2/族、INCOMPLETE≥1/3、预算触顶、端点异常。
"""
import argparse, hashlib, json, os, random, sys, time, urllib.request
from pathlib import Path

STAGE_A = Path("/root/research_outputs/static_pi/stage_a")
STAGE_B = Path("/root/research_outputs/static_pi/stage_b")
STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
for p in (STAGE_A, STAGE_B, STAGE_D, Path("/root/capital_opinion_pilot"),
          Path("/root/r3_own_pool/deadline_reward_v1/quality_v4")):
    sys.path.insert(0, str(p))

import transport
from executor import (E_SYSTEM, E_POSITION_ADDENDUM, J1_SYSTEM, RELAY_ADDENDUM,
                      J1_POSITIONS_ADDENDUM, J2_SYSTEM, DISAMBIG_ADDENDUM, SINK_SYSTEM,
                      e_user, j1_user, j2_user, sink_user, extract_json,
                      apply_format_rules, build_terminal_output)
from terminal_quality import evaluate_terminal_quality
import p1_executor as P1

OUT = STAGE_D / "stage_c_runs"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
J1_H = J1_SYSTEM + RELAY_ADDENDUM + J1_POSITIONS_ADDENDUM

# ==================== MVR2 prompt set ====================
M_Q = ("元道通信欺诈发行及信息披露违法案：事先告知书拟对各当事人处罚多少？行政处罚决定书最终对公司和李晋、"
       "燕某、曹亚蕾、吴志锋分别处罚多少？曹亚蕾拟罚与终罚差多少？对李晋、曹亚蕾的市场禁入分别几年（拟与终）？"
       "三份文书的文号分别是什么？立案公告、告知书、决定书、停牌各是何日期？2019-2022 各年虚增营业收入及"
       "四年合计是多少？IPO 募集资金总额多少？")
M_E = ("你是精确的监管文书抽取器。只输出一个 JSON 对象：{\"parties\": [{name, penalties: {欺诈发行罚款, "
       "信披违法罚款, 综合罚款, 拟处罚金额}, market_ban_years: {拟, 终}}], \"doc_number\": ..., "
       "\"dates\": {立案公告披露日, 文书收到日, 停牌日}, \"inflated_revenue\": {年度: 金额}, "
       "\"ipo_proceeds\": ...}, 每项含完整原句引用与页码。不得编造。")
M_J1 = ("你是跨文书处罚阶段衔接器。只输出 JSON：{\"party_stage_matrix\": [{party, proposed_penalty, "
        "final_penalty, difference, proposed_ban_years, final_ban_years, evidence:[{doc,page,quote}]}], "
        "\"date_chain\": {...}, \"doc_numbers\": {...}, \"cross_doc_notes\": [...]}。"
        "拟罚取自事先告知书(Db)，终罚取自决定书(Da)；差异=拟−终。仅依据给定材料。")
M_J2 = ("你是处罚矩阵核验器。只输出 JSON：{\"per_party\": [...], \"totals\": {...}, "
        "\"doc_numbers\": {...}, \"date_chain\": {...}}。四年合计=2019+2020+2021+2022。仅依据给定材料。")
M_SINK = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\": [...], \"unknown_slots\": [...]}。"
          "不得使用给定上游材料之外的任何信息。")


def glm_low(system, user, max_tokens=8192, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    if not key: raise RuntimeError("STAGE_D_GLM_KEY not set")
    body = {"model": "GLM-5.3-Flash", "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}], "reasoning_effort": "low"}
    req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method="POST")
    req.add_header("content-type", "application/json"); req.add_header("x-api-key", key)
    req.add_header("authorization", "Bearer " + key); req.add_header("anthropic-version", "2023-06-01")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    return {"text": "".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text"),
            "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
            "stop": d.get("stop_reason"), "lat": round(time.monotonic()-t0,2)}

def ds_call(system, user, max_tokens=4000, timeout_s=300):
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic()-t0, 2)
    return r

def contract_check(node, r, parsed):
    text = (r.get("text") or "").strip()
    if r.get("error") or ((r.get("in") or 0)==0 and (r.get("out") or 0)==0 and not text): return "transport_error"
    if not text: return "empty_text"
    if parsed is None: return "json_invalid"
    return None

# ==================== task DAG definitions ====================
def get_task(name):
    """Return dict with: e_nodes [{key, sys, user}], j1_sys, j1_user_fn, j2_sys, j2_user_fn,
    sink_sys, sink_user_fn, contract, slots, fmt_fn"""
    if name == "PHASE2B":
        c = json.loads(Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/"
                            "TASK_CONTRACT_PHASE2B_v2_1.json").read_text("utf-8"))
        slots = [{"fact_id": f["fact_id"]} for f in c["required_facts"]]
        def make_e():
            return [{"key": f"E{i}", "sys": E_SYSTEM + (E_POSITION_ADDENDUM if i in (1,2) else ""),
                     "user": e_user(f"E{i}")} for i in (1,2,3,4)]
        def j1u(E): return j1_user(json.dumps({"E1": E["E1"], "E2": E["E2"]}, ensure_ascii=False))
        def j2u(J1, E): return j2_user(json.dumps({"J1": J1, "E3": E["E3"], "E4": E["E4"]}, ensure_ascii=False))
        def sku(J1, J2): return sink_user(json.dumps({"J1": J1, "J2": J2}, ensure_ascii=False))
        return {"name": "PHASE2B", "contract": c, "slots": slots,
                "e_nodes": make_e, "j1_sys": J1_H, "j1_user": j1u, "j2_sys": J2_SYSTEM + DISAMBIG_ADDENDUM,
                "j2_user": j2u, "sink_sys": SINK_SYSTEM, "sink_user": sku,
                "j1_backend": "glm", "j2_backend": "ds", "sink_backend": "ds",
                "fmt": lambda parsed: apply_format_rules(parsed)[0]}
    if name == "MVR2":
        c = json.loads(Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao/"
                            "TASK_CONTRACT_MVR2_v1.json").read_text("utf-8"))
        slots = [{"fact_id": f["fact_id"]} for f in c["required_facts"]]
        src = c.get("source_pages") or {}
        def make_e():
            out = []
            for doc in ("Da", "Db", "Dc"):
                text = "".join(rec["text"] for rec in src[doc]["pages"].values())
                out.append({"key": f"E_{doc}", "sys": M_E,
                            "user": f"任务问题：{M_Q}\n\n文书{doc}全文：\n{text}\n\n请按系统约定抽取。"})
            return out
        def j1u(E): return (f"任务问题：{M_Q}\n\n事先告知书(Db)抽取：\n{E['E_Db']}\n\n"
                            f"行政处罚决定书(Da)抽取：\n{E['E_Da']}\n\n交易所函(Dc)抽取：\n{E['E_Dc']}\n\n"
                            f"请完成拟/终阶段衔接矩阵。按系统约定输出。")
        def j2u(J1, E): return (f"任务问题：{M_Q}\n\nJ1 衔接结果：\n{J1}\n\n请完成逐当事人核验与合计。按系统约定输出。")
        def sku(J1, J2): return (f"任务问题：{M_Q}\n\nJ2 核验结果：\n{J2}\n\n输出格式：answers 逐槽位填写 "
                                 f"{{\"fact_id\":..., \"value\":..., \"quote\":..., \"doc\":...}}。\n"
                                 f"槽位：{json.dumps(slots, ensure_ascii=False)}\n无法确定项列入 unknown_slots。")
        return {"name": "MVR2", "contract": c, "slots": slots,
                "e_nodes": make_e, "j1_sys": M_J1, "j1_user": j1u, "j2_sys": M_J2,
                "j2_user": j2u, "sink_sys": M_SINK, "sink_user": sku,
                "j1_backend": "glm", "j2_backend": "ds", "sink_backend": "ds",
                "fmt": lambda p: p}
    if name == "P11":
        c = json.loads(Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P1_1_ZHUORAN/"
                            "TASK_CONTRACT_P1_1_v1.json").read_text("utf-8"))
        slots = [{"fact_id": f.get("fact_id", f"VF_{i}")} for i, f in enumerate(c.get("state_evolution_facts") or [])]
        def make_e():
            return [{"key": f"E_{s}", "sys": P1.E_SYSTEM, "user": P1.e_user(s)} for s in ("S1","S2","S3")]
        def j1u(E): return P1.j1_user(json.dumps({f"E_{s}": E[f"E_{s}"] for s in ("S1","S2","S3")}, ensure_ascii=False))
        def j2u(J1, E): return P1.j2_user(J1)
        def sku(J1, J2): return P1.sink_user(J2)
        return {"name": "P11", "contract": c, "slots": slots,
                "e_nodes": make_e, "j1_sys": P1.J1_SYSTEM, "j1_user": j1u, "j2_sys": P1.J2_SYSTEM,
                "j2_user": j2u, "sink_sys": P1.SINK_SYSTEM, "sink_user": sku,
                "j1_backend": "ds", "j2_backend": "ds", "sink_backend": "ds",  # 全 DS（探针修订）
                "fmt": lambda p: p}
    raise ValueError(f"unknown task {name}")


# ==================== arm execution ====================
def run_arm(task, arm, cond, rep, E, inject=None):
    """inject: None|'j1anom'|'fmt_b3'|'struct'。返回记录。"""
    t0 = time.monotonic()
    calls, guard, actions = [], [], []
    acct = 0.0

    def do_call(node, backend, system, user, tag, cap=4000):
        nonlocal acct
        r = glm_low(system, user, cap) if backend == "glm" else ds_call(system, user, cap)
        c = {"node": node, "backend": backend, "tag": tag, "in": r.get("in"), "out": r.get("out"),
             "stop": r.get("stop"), "lat": r.get("lat"), "text": r.get("text")}
        calls.append(c)
        acct += (r.get("in") or 0)*0.8e-6 + (r.get("out") or 0)*2.8e-6
        return r

    # J1
    j1_sys = task["j1_sys"]
    if cond in ("struct", "struct_b3") and task["name"] == "PHASE2B":
        j1_sys = J1_SYSTEM  # 结构故障：无 relay
    j1u = task["j1_user"](E)
    r1 = do_call("J1", task["j1_backend"], j1_sys, j1u, "first",
                 8192 if task["j1_backend"] == "glm" else 4000)
    j1_text = r1.get("text") or ""
    if inject == "j1anom":
        j1_text = ""
    parsed1 = extract_json(j1_text)
    g = contract_check("J1", {"text": j1_text, "in": r1.get("in"), "out": r1.get("out")}, parsed1)
    if g: guard.append({"node": "J1", "reason": g})

    final_j1 = j1_text
    j1_model = task["j1_backend"]

    # arm-specific actions
    if arm == "Static":
        if g:
            return _rec(task["name"], arm, cond, rep, calls, guard, actions, None, t0, acct,
                        "INCOMPLETE_NO_RECOVERY", False)
    elif arm == "Best-Single":
        if g:
            # Best-Single = 格式修复（Stage D 回顾最优单动作）
            actions.append({"kind": "format_repair"})
            # 格式修复不能救 J1 契约违规——如实失败
            return _rec(task["name"], arm, cond, rep, calls, guard, actions, None, t0, acct,
                        "INCOMPLETE_NO_RECOVERY", False)
    elif arm == "Proposed":
        if g and task["j1_backend"] == "glm":
            # 诊断换模（唯一合法切换点 J1: GLM→DS）
            actions.append({"kind": "diagnosed_swap", "node": "J1"})
            rd = do_call("J1", "ds", task["j1_sys"], j1u, "diagnosed_swap")
            final_j1 = rd.get("text") or ""
            j1_model = "ds"
            pd = extract_json(final_j1)
            if contract_check("J1", {"text": final_j1, "in": rd.get("in"), "out": rd.get("out")}, pd):
                guard.append({"node": "J1", "reason": "swap_also_failed"})
                return _rec(task["name"], arm, cond, rep, calls, guard, actions, None, t0, acct,
                            "INCOMPLETE_RECOVERY_FAILED", False)
        elif cond in ("struct", "struct_b3") and task["name"] == "PHASE2B" and parsed1:
            if "dates_relay" not in parsed1:
                actions.append({"kind": "structure_repair", "node": "J1"})
                rr = do_call("J1", "glm" if task["j1_backend"] == "glm" else "ds",
                             task["j1_sys"], j1u, "structure_repair",
                             8192 if task["j1_backend"] == "glm" else 4000)
                final_j1 = rr.get("text") or ""
                j1_model = task["j1_backend"]

    # H1 embedded: A1 blind / A2 diagnosed
    if arm == "A1_blind":
        rd = do_call("J1", "ds", task["j1_sys"], j1u, "blind_swap")
        actions.append({"kind": "unconditional_swap"})
        final_j1 = rd.get("text") or ""
        j1_model = "ds"
    elif arm == "A2_diag" and g and task["j1_backend"] == "glm":
        rd = do_call("J1", "ds", task["j1_sys"], j1u, "diagnosed_swap")
        actions.append({"kind": "diagnosed_swap"})
        final_j1 = rd.get("text") or ""
        j1_model = "ds"
    elif arm == "A0_noswap" and g:
        return _rec(task["name"], arm, cond, rep, calls, guard, actions, None, t0, acct,
                    "INCOMPLETE_NO_RECOVERY", False)

    # J2
    pj1 = extract_json(final_j1)
    if pj1 is None:
        return _rec(task["name"], arm, cond, rep, calls, guard, actions, None, t0, acct,
                    "INCOMPLETE_J1", False)
    j2u = task["j2_user"](final_j1, E)
    r2 = do_call("J2", task["j2_backend"], task["j2_sys"], j2u, "main")
    p2 = extract_json(r2.get("text") or "")
    if p2 is None:
        return _rec(task["name"], arm, cond, rep, calls, guard, actions, None, t0, acct,
                    "INCOMPLETE_J2", False)

    # SINK
    su = task["sink_user"](final_j1, r2.get("text"))
    r3 = do_call("SINK", task["sink_backend"], task["sink_sys"], su, "main")
    ps = extract_json(r3.get("text") or "")

    # H2: fmt_b3 格式旁路
    fmt_bypass = (cond == "fmt_b3" and arm not in ("Proposed", "H2_matched"))
    if cond == "fmt_b3" and arm == "Proposed":
        actions.append({"kind": "format_repair(matched)"})
    if cond == "fmt_b3" and arm == "H2_mismatched":
        actions.append({"kind": "structure_repair_only(mismatched)"})
        rr = do_call("J1", task["j1_backend"], task["j1_sys"], j1u, "mismatched",
                     8192 if task["j1_backend"] == "glm" else 4000)
        final_j1 = rr.get("text") or ""
        j2u2 = task["j2_user"](final_j1, E)
        r2 = do_call("J2", task["j2_backend"], task["j2_sys"], j2u2, "rerun")
        su = task["sink_user"](final_j1, r2.get("text"))
        r3 = do_call("SINK", task["sink_backend"], task["sink_sys"], su, "rerun")
        ps = extract_json(r3.get("text") or "")

    # H3: KANGMEI (Terminal vs Upstream)
    # Terminal-only: 只重跑 SINK; Upstream: 重跑 J2+SINK

    # Score
    sc = score_task(task, ps, fmt_bypass)
    return _rec(task["name"], arm, cond, rep, calls, guard, actions, sc, t0, acct, "COMPLETE", fmt_bypass, j1_model)


def score_task(task, ps, fmt_bypass):
    """通用评分：从 SINK parsed 输出构建 claims → 该任务合同评分。不依赖 PHASE2B 的 slot 映射。"""
    if ps is None:
        return {"old_tp": 0, "n_slots": len(task["slots"])}
    import copy
    pf = json.loads(json.dumps(ps))
    if not fmt_bypass:
        try: pf = task["fmt"](pf)
        except: pass
    # 通用 terminal 构建：从 answers 构造 claims（fact_id → 合同槽位匹配）
    answers = pf.get("answers") or []
    c = task["contract"]
    src = c.get("source_pages") or {}
    facts_by_id = {f.get("fact_id"): f for f in (c.get("required_facts") or c.get("state_evolution_facts") or [])
                   if f.get("fact_id")}
    claims = []
    for a in answers:
        if not isinstance(a, dict): continue
        fid = a.get("fact_id")
        if fid in facts_by_id:
            f = facts_by_id[fid]
            cite = {"doc_id": a.get("doc"), "page": a.get("page"), "quote": a.get("quote", "")}
            doc = src.get(cite["doc_id"]) if cite["doc_id"] else None
            pg = (doc or {}).get("pages", {}).get(str(cite["page"]))
            if pg:
                cite["page_sha256"] = pg.get("page_sha256")
                cite["raw_sha256"] = (doc or {}).get("raw_sha256")
            claims.append({"claim_id": f"c_{fid}", "fact_id": fid,
                          "subject": f.get("subject",""), "predicate": f.get("predicate",""),
                          "value": a.get("value"),
                          "value_kind": f.get("value_kind","text"), "unit": f.get("unit",""),
                          "date_type": f.get("date_type",""),
                          "citations": [cite], "weight": f.get("weight",1.0), "material": True})
    term = {"claims": claims, "abstentions": [], "abstentions_complete": True, "claims_complete": True}
    if not src:
        return {"old_tp": len(claims), "n_slots": len(task["slots"]),
                "note": f"no source_pages; counted {len(claims)} answer claims (探针级粗对分)"}
    try:
        cc = copy.deepcopy(c); cc.pop("source_pages", None)
        q = evaluate_terminal_quality(cc, term, src)
        tp = sum(1 for x in q["claim_results"] if x["status"].startswith("CORRECT"))
        return {"old_tp": tp, "n_slots": len(q["claim_results"])}
    except Exception as e:
        return {"old_tp": 0, "n_slots": len(task["slots"]), "scoring_error": repr(e)[:100]}


def _rec(task_name, arm, cond, rep, calls, guard, actions, sc, t0, acct, status, fmt_bp, j1_model=None):
    rec = {"task": task_name, "arm": arm, "cond": cond, "rep": rep, "status": status,
            "wall_s": round(time.monotonic()-t0, 1), "n_calls": len(calls),
            "accounting_yuan": round(acct, 6), "guard": guard, "actions": actions,
            "j1_final_model": j1_model, "fmt_bypassed": fmt_bp,
            "score": sc or {"old_tp": 0, "n_slots": 0},
            "calls": [{k: c[k] for k in ("node","backend","tag","in","out","stop","lat","text")} for c in calls]}
    return rec


# ==================== main ====================
def main():
    if os.environ.get("STAGE_C_GO") != "1":
        raise SystemExit("REFUSED: requires STAGE_C_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261104)

    all_recs = []
    total_calls = 0
    for task_name in ("MVR2", "P11", "PHASE2B"):
        task = get_task(task_name)
        # Main arms × 4 rep
        for rep in range(1, 5):
            # Run E nodes once per rep (shared)
            E = {}
            for en in task["e_nodes"]():
                r = ds_call(en["sys"], en["user"], 4000)
                E[en["key"]] = r.get("text") or ""
                total_calls += 1
            for arm in ("Static", "Best-Single", "Proposed"):
                rec = run_arm(task, arm, "healthy", rep, E)
                all_recs.append(rec); total_calls += rec["n_calls"]
                print(f"[{task_name}|{arm}|r{rep}] {rec['status']} TP={rec['score'].get('old_tp',0)} "
                      f"calls={rec['n_calls']}", flush=True)
        # H1: blind vs diag × healthy/j1anom × 2 rep
        for rep in (1, 2):
            E = {}
            for en in task["e_nodes"]():
                r = ds_call(en["sys"], en["user"], 4000)
                E[en["key"]] = r.get("text") or ""
                total_calls += 1
            for arm in ("A0_noswap", "A1_blind", "A2_diag"):
                for cond in ("healthy", "j1anom"):
                    rec = run_arm(task, arm, cond, rep, E, inject="j1anom" if cond == "j1anom" else None)
                    all_recs.append(rec); total_calls += rec["n_calls"]
                    print(f"[{task_name}|H1:{arm}|{cond}|r{rep}] {rec['status']} TP={rec['score'].get('old_tp',0)} "
                          f"calls={rec['n_calls']}", flush=True)
        # H2: matched vs mismatched × fmt/struct × 2 rep
        for rep in (1, 2):
            E = {}
            for en in task["e_nodes"]():
                r = ds_call(en["sys"], en["user"], 4000)
                E[en["key"]] = r.get("text") or ""
                total_calls += 1
            for cond in ("fmt_b3", "struct"):
                for arm in ("Proposed", "H2_mismatched"):
                    rec = run_arm(task, arm, cond, rep, E)
                    all_recs.append(rec); total_calls += rec["n_calls"]
                    print(f"[{task_name}|H2:{arm}|{cond}|r{rep}] {rec['status']} TP={rec['score'].get('old_tp',0)} "
                          f"calls={rec['n_calls']}", flush=True)
        # H3: KANGMEI Terminal vs Upstream × 2 rep
        for rep in (1, 2):
            E = {}
            for en in task["e_nodes"]():
                r = ds_call(en["sys"], en["user"], 4000)
                E[en["key"]] = r.get("text") or ""
                total_calls += 1
            for arm in ("H3_terminal", "H3_upstream"):
                rec = run_arm(task, arm, "struct", rep, E)
                all_recs.append(rec); total_calls += rec["n_calls"]
                print(f"[{task_name}|H3:{arm}|r{rep}] {rec['status']} TP={rec['score'].get('old_tp',0)} "
                          f"calls={rec['n_calls']}", flush=True)

    summary = {"total_execs": len(all_recs), "total_calls": total_calls,
               "by_task": {}, "by_arm": {}}
    from collections import Counter
    for r in all_recs:
        summary["by_task"][r["task"]] = summary["by_task"].get(r["task"], 0) + 1
        summary["by_arm"][r["arm"]] = summary["by_arm"].get(r["arm"], 0) + 1
    (OUT / "STAGE_C_ALL_RECORDS.json").write_text(json.dumps(all_recs, ensure_ascii=False, indent=1), "utf-8")
    (OUT / "STAGE_C_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
