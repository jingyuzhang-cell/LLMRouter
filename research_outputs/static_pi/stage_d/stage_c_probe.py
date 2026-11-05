#!/usr/bin/env python3
"""STAGE_C 可行性探针（授权 14 次；2026-11-04）。

分配：P1-1 端到端 ×1（6 调用，A‴ 路由）；MVR2 端到端 ×1（7 调用）。
- P1-1：复用 stage_b/p1_executor.py 的冻结提示词，仅换 A‴ 路由
  （E×3=DS、J1=GLM-low、J2/SINK=DS），验证当前执行形态下的可行性。
- MVR2：新建最小 DAG（E_Da/E_Db/E_Dc → J1 阶段衔接 → J2 处罚矩阵 → SINK），
  提示词按合同槽位构建（数据准备，非评分改动）。
探针结果仅作可行性与方差初估，不作确认性证据。

GO 门：STAGE_C_PROBE_GO=1。
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

STAGE_B = Path("/root/research_outputs/static_pi/stage_b")
STAGE_A = Path("/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, str(STAGE_B))
sys.path.insert(0, str(STAGE_A))
sys.path.insert(0, "/root/capital_opinion_pilot")
sys.path.insert(0, "/root/r3_own_pool/deadline_reward_v1/quality_v4")

import transport  # noqa: E402
import p1_executor as P1  # noqa: E402
from executor import extract_json  # noqa: E402

OUT = Path("/root/research_outputs/static_pi/stage_d/stage_c_probes")
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"


def glm_low(system, user, max_tokens=8192, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
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
    return {"text": "".join(b.get("text", "") for b in d.get("content", [])
                            if isinstance(b, dict) and b.get("type") == "text"),
            "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
            "stop": d.get("stop_reason"), "lat": round(time.monotonic() - t0, 2)}


def ds(system, user, max_tokens=4000, timeout_s=300):
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic() - t0, 2)
    return r


def call(name, backend, system, user, cap):
    r = glm_low(system, user, cap) if backend == "glm" else ds(system, user, cap)
    parsed = extract_json(r.get("text") or "")
    ok = r.get("stop") in ("end_turn", "stop", None) and parsed is not None
    rec = {"node": name, "backend": backend, "stop": r.get("stop"), "in": r.get("in"),
           "out": r.get("out"), "lat": r.get("lat"), "json_ok": parsed is not None, "pass": ok}
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec, (r.get("text") or "")


# ---------------- P1-1（A‴ 路由复用冻结提示词） ----------------
def probe_p11():
    recs = []
    es = {}
    for s in ("S1", "S2", "S3"):
        rec, txt = call(f"E_{s}", "ds", P1.E_SYSTEM, P1.e_user(s), 4000)
        recs.append(rec)
        es[s] = txt
        if not rec["pass"]:
            return {"task": "P1-1", "status": "HALT", "at": f"E_{s}", "recs": recs}
    up = json.dumps({f"E_{s}": es[s] for s in ("S1", "S2", "S3")}, ensure_ascii=False)
    rec, j1 = call("J1", "glm", P1.J1_SYSTEM, P1.j1_user(up), 8192)
    recs.append(rec)
    if not rec["pass"]:
        return {"task": "P1-1", "status": "HALT", "at": "J1", "recs": recs}
    rec, j2 = call("J2", "ds", P1.J2_SYSTEM, P1.j2_user(j1), 4000)
    recs.append(rec)
    if not rec["pass"]:
        return {"task": "P1-1", "status": "HALT", "at": "J2", "recs": recs}
    rec, sink = call("SINK", "ds", P1.SINK_SYSTEM, P1.sink_user(j2), 4000)
    recs.append(rec)
    parsed = extract_json(sink)
    n_ans = len((parsed or {}).get("answers") or [])
    return {"task": "P1-1", "status": "COMPLETE" if rec["pass"] else "HALT",
            "recs": recs, "n_answers": n_ans,
            "calls": len(recs), "wall_total": round(sum(r["lat"] or 0 for r in recs), 1)}


# ---------------- MVR2（最小 DAG，合同槽位构建） ----------------
MVR2_Q = ("元道通信欺诈发行及信息披露违法案：事先告知书拟对各当事人处罚多少？行政处罚决定书最终对公司和李晋、"
          "燕某、曹亚蕾、吴志锋分别处罚多少？曹亚蕾拟罚与终罚差多少？对李晋、曹亚蕾的市场禁入分别几年（拟与终）？"
          "三份文书的文号分别是什么？立案公告、告知书、决定书、停牌各是何日期？2019-2022 各年虚增营业收入及"
          "四年合计是多少？IPO 募集资金总额多少？")

M_E = ("你是精确的监管文书抽取器。只输出一个 JSON 对象：{\"parties\": [{name, penalties: {欺诈发行罚款, "
       "信披违法罚款, 综合罚款, 拟处罚金额(if 事先告知书)}, market_ban_years: {拟, 终}}], \"doc_number\": ..., "
       "\"dates\": {立案公告披露日, 文书收到日, 停牌日}, \"inflated_revenue\": {年度: 金额}, \"ipo_proceeds\": ..., "
       "\"quotes\": [...]}, 每项含完整原句引用与页码。不得编造。")

M_J1 = ("你是跨文书处罚阶段衔接器。只输出 JSON：{\"party_stage_matrix\": [{party, proposed_penalty, "
        "final_penalty, difference, proposed_ban_years, final_ban_years, evidence:[{doc,page,quote}]}], "
        "\"date_chain\": {立案→告知书→决定书→停牌 各日期与来源}, \"doc_numbers\": {告知书, 决定书, 交易所函}, "
        "\"cross_doc_notes\": [...]}。拟罚取自事先告知书(Db)，终罚与禁入取自决定书(Da)；差异=拟−终。仅依据给定材料。")

M_J2 = ("你是处罚矩阵核验器。只输出 JSON：{\"per_party\": [{party, 欺诈发行罚款, 信披罚款, 综合罚款, 拟终差异, "
        "禁入拟/终}], \"totals\": {四年虚增合计, 各年金额}, \"doc_numbers\": {...}, \"date_chain\": {...}}。"
        "四年合计=2019+2020+2021+2022 逐年相加；逐项保留上游证据引用。仅依据给定材料。")

M_SINK = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\": [...], \"unknown_slots\": [...]}。"
          "不得使用给定上游材料之外的任何信息。")


def mvr2_contract():
    c = json.loads(Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao/"
                         "TASK_CONTRACT_MVR2_v1.json").read_text("utf-8"))
    slots = [{"fact_id": f["fact_id"], "subject": f.get("subject"), "predicate": f.get("predicate"),
              "value_kind": f.get("value_kind", "text"), "unit": f.get("unit", ""),
              "date_type": f.get("date_type", "")} for f in c["required_facts"]]
    return c, slots


def m_e_user(doc, text):
    return f"任务问题：{MVR2_Q}\n\n文书{doc}全文：\n{text}\n\n请按系统约定抽取该文书全部处罚/日期/金额/文号信息。输出上述 JSON。"


def probe_mvr2():
    c, slots = mvr2_contract()
    src = c["source_pages"]
    recs = []
    texts = {}
    for doc in ("Da", "Db", "Dc"):
        body = "".join(rec["text"] for rec in src[doc]["pages"].values())
        rec, txt = call(f"E_{doc}", "ds", M_E, m_e_user(doc, body), 4000)
        recs.append(rec)
        texts[doc] = txt
        if not rec["pass"]:
            return {"task": "MVR2", "status": "HALT", "at": f"E_{doc}", "recs": recs}
    j1u = (f"任务问题：{MVR2_Q}\n\n事先告知书(Db)抽取：\n{texts['Db']}\n\n行政处罚决定书(Da)抽取：\n{texts['Da']}\n\n"
           f"交易所函(Dc)抽取：\n{texts['Dc']}\n\n请完成拟/终阶段衔接矩阵。按系统约定输出。")
    rec, j1 = call("J1", "glm", M_J1, j1u, 8192)
    recs.append(rec)
    if not rec["pass"]:
        return {"task": "MVR2", "status": "HALT", "at": "J1", "recs": recs}
    j2u = (f"任务问题：{MVR2_Q}\n\nJ1 衔接结果：\n{j1}\n\n请完成逐当事人核验与合计。按系统约定输出。")
    rec, j2 = call("J2", "ds", M_J2, j2u, 4000)
    recs.append(rec)
    if not rec["pass"]:
        return {"task": "MVR2", "status": "HALT", "at": "J2", "recs": recs}
    su = (f"任务问题：{MVR2_Q}\n\nJ2 核验结果：\n{j2}\n\n输出格式：answers 逐槽位填写 "
          f"{{\"fact_id\":..., \"value\":..., \"quote\": 上游原句, \"doc\": 文档ID(Da/Db/Dc)}}。\n"
          f"槽位：{json.dumps(slots, ensure_ascii=False)}\n无法确定项列入 unknown_slots。")
    rec, sink = call("SINK", "ds", M_SINK, su, 4000)
    recs.append(rec)
    parsed = extract_json(sink) or {}
    n_ans = len(parsed.get("answers") or [])
    # 粗对分：值与 Gold 前缀匹配（探针级，非正式评分）
    gold = {f["fact_id"]: str(f.get("value")) for f in c["required_facts"]}
    hit = 0
    for a in parsed.get("answers") or []:
        g = gold.get(a.get("fact_id"))
        if g and str(a.get("value", "")).strip()[:6] == g[:6]:
            hit += 1
    return {"task": "MVR2", "status": "COMPLETE" if rec["pass"] else "HALT", "recs": recs,
            "n_answers": n_ans, "probe_prefix_match": hit, "n_facts": len(gold),
            "calls": len(recs), "wall_total": round(sum(r["lat"] or 0 for r in recs), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if not a.go or os.environ.get("STAGE_C_PROBE_GO") != "1":
        raise SystemExit("REFUSED: requires STAGE_C_PROBE_GO=1 and --go")
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"p11": probe_p11(), "mvr2": probe_mvr2()}
    res["total_calls"] = sum(r.get("calls", len(r.get("recs", []))) for r in res.values())
    (OUT / "STAGE_C_PROBE_RESULTS.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: (v if k != "total_calls" else v) for k, v in res.items()
                      if k in ("total_calls",)}, ensure_ascii=False))
    for k in ("p11", "mvr2"):
        r = res[k]
        print(f"{k}: {r['status']} calls={r.get('calls')} wall={r.get('wall_total')}s "
              f"answers={r.get('n_answers')} probe_match={r.get('probe_prefix_match')}/{r.get('n_facts','?')}")


if __name__ == "__main__":
    main()
