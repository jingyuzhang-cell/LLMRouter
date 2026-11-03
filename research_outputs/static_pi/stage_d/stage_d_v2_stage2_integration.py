#!/usr/bin/env python3
"""Stage D V2.0 阶段 2 集成先导（授权 2026-11-03；核心 8 次，上限 15）。

动态真实整链（非重放）：E1-E4(GLM-low) → J1(GLM-low, 消费真实 E1/E2)
→ J2(DS, 消费真实 J1+E3/E4) → SINK(DS, 消费真实 J1+J2) → FMT(本地 apply_format_rules)
→ 终端评分（旧合同 v2.1 + V3 并列 + 完全正确率）。
P-J1DS：冻结基础 J1 提示词（runs/run1/J1.json，无附录）→ DS@4000。

GO 门：STAGE_D_V2_STAGE2_GO=1；凭据仅 env（STAGE_D_GLM_KEY / DEEPSEEK_API_KEY）。
停止规则：任一节点 HTTP 错误/截断/JSON 失败 → 立即停止整链，保留现场，不重试。
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STAGE_A = Path("/root/research_outputs/static_pi/stage_a")
STAGE_D = Path("/root/research_outputs/static_pi/stage_d")
sys.path.insert(0, str(STAGE_A))
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, "/root/capital_opinion_pilot")
sys.path.insert(0, "/root/r3_own_pool/deadline_reward_v1/quality_v4")

import transport  # noqa: E402
from executor import (E_SYSTEM, J1_SYSTEM, J2_SYSTEM, SINK_SYSTEM,  # noqa: E402
                      e_user, j1_user, j2_user, sink_user,
                      apply_format_rules, build_terminal_output, extract_json)
from terminal_quality import evaluate_terminal_quality  # noqa: E402

OUT = STAGE_D / "v2_pilot" / "stage2"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
GLM_CAP, DS_CAP = 8192, 4000
CONTRACTS = {
    "old": json.loads((Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/"
                            "TASK_CONTRACT_PHASE2B_v2_1.json")).read_text("utf-8")),
    "v3": json.loads((Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/"
                           "TASK_CONTRACT_PHASE2B_v3_DRAFT.json")).read_text("utf-8")),
}


class Halt(Exception):
    pass


def glm_call(system, user, max_tokens=GLM_CAP, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    if not key:
        raise Halt("STAGE_D_GLM_KEY not set")
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


def ds_call(system, user, max_tokens=DS_CAP, timeout_s=300):
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, max_tokens, timeout_s, 0)
    r["lat"] = round(time.monotonic() - t0, 2)
    return r


def step(name, fn, text_key="text"):
    print(f"--- {name} ---", flush=True)
    try:
        r = fn()
    except Halt:
        raise
    except Exception as e:  # noqa: BLE001
        raise Halt(f"{name}: transport error {e!r}")
    parsed = extract_json(r.get(text_key) or "")
    rec = {"node": name, "in": r.get("in"), "out": r.get("out"), "stop": r.get("stop"),
           "wall_s": r.get("lat"), "text_chars": len(r.get(text_key) or ""),
           "json_ok": parsed is not None}
    print(json.dumps({k: rec[k] for k in ("node", "stop", "in", "out", "wall_s", "json_ok")}),
          flush=True)
    if r.get("stop") not in ("end_turn", "stop", None):
        raise Halt(f"{name}: stop={r.get('stop')} 截断 -> 停止整链")
    if parsed is None:
        raise Halt(f"{name}: JSON 不可解析 -> 停止整链")
    return rec, parsed, r.get(text_key)


def score(parsed_sink):
    parsed_fmt, fmt_log = apply_format_rules(json.loads(json.dumps(parsed_sink)))
    term = build_terminal_output(parsed_fmt)
    out = {"fmt_log": fmt_log}
    for label in ("old", "v3"):
        c = json.loads(json.dumps(CONTRACTS[label]))
        src = c.pop("source_pages")
        q = evaluate_terminal_quality(c, term, src)
        tp = sum(1 for x in q["claim_results"] if x["status"].startswith("CORRECT"))
        claims = [x for x in q["claim_results"]]
        full = sum(1 for x in claims
                   if x["status"] == "CORRECT_GOLD")
        supported = sum(1 for x in claims if x["status"] == "CORRECT_GOLD")
        n = max(len(claims), 1)
        out[label] = {"fact": round(q["dimensions"]["fact_correctness"], 4),
                      "evidence": round(q["dimensions"]["evidence_support"], 4),
                      "Q_raw": round(q["Q_raw"], 4) if q["Q_raw"] is not None else None,
                      "tp": tp, "n_claims": len(claims),
                      "full_correct_rate": round(full / n, 4)}
    # 引用完整性抽检：SINK answers 的 doc_id 是否为合法 D1-D4
    docs = [a.get("doc") for a in (parsed_fmt or {}).get("answers", []) if isinstance(a, dict)]
    out["citation_spot_check"] = {"n_answers": len(docs),
                                  "legal_doc_ids": sum(1 for d0 in docs
                                                       if str(d0) in ("D1", "D2", "D3", "D4")),
                                  "sample_doc_ids": docs[:6]}
    return out


def chain():
    t0 = time.monotonic()
    recs, texts = [], {}
    for n in ("E1", "E2", "E3", "E4"):
        rec, parsed, text = step(n, lambda n=n: glm_call(E_SYSTEM, e_user(n)))
        recs.append(rec); texts[n] = text
    rec, parsed, text = step(
        "J1", lambda: glm_call(J1_SYSTEM, j1_user(json.dumps(
            {"E1": texts["E1"], "E2": texts["E2"]}, ensure_ascii=False))))
    recs.append(rec); texts["J1"] = text
    rec, parsed, text = step(
        "J2", lambda: ds_call(J2_SYSTEM, j2_user(json.dumps(
            {"J1": texts["J1"], "E3": texts["E3"], "E4": texts["E4"]}, ensure_ascii=False))))
    recs.append(rec); texts["J2"] = text
    rec, parsed, text = step(
        "SINK", lambda: ds_call(SINK_SYSTEM, sink_user(json.dumps(
            {"J1": texts["J1"], "J2": texts["J2"]}, ensure_ascii=False))))
    recs.append(rec); texts["SINK"] = text
    total_wall = round(time.monotonic() - t0, 2)
    sink_parsed = extract_json(texts["SINK"])
    sc = score(sink_parsed)
    return {"recs": recs, "total_wall_s": total_wall, "score": sc,
            "tokens": {"in": sum(r["in"] for r in recs), "out": sum(r["out"] for r in recs)},
            "accounting_yuan": round(sum((r["in"] or 0) * 0.8e-6 + (r["out"] or 0) * 2.8e-6
                                         for r in recs), 8)}


def p_j1ds():
    j1 = json.loads((STAGE_A / "runs" / "run1" / "J1.json").read_text("utf-8"))
    print("--- P-J1DS ---", flush=True)
    t0 = time.monotonic()
    r = ds_call(j1["system"], j1["user"])
    parsed = extract_json(r.get("text") or "")
    rec = {"node": "P-J1DS", "in": r.get("in"), "out": r.get("out"), "stop": r.get("stop"),
           "wall_s": r.get("lat"), "text_chars": len(r.get("text") or ""), "json_ok": parsed is not None,
           "prompt_sha256": hashlib.sha256((j1["system"] + "||" + j1["user"]).encode()).hexdigest(),
           "has_judgments": isinstance(parsed, dict) and isinstance(parsed.get("judgments"), list),
           "n_judgments": len(parsed.get("judgments", [])) if isinstance(parsed, dict) else 0}
    rec["pass"] = (rec["stop"] in ("end_turn", "stop", None) and rec["json_ok"] and rec["has_judgments"])
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


def main():
    if os.environ.get("STAGE_D_V2_STAGE2_GO") != "1":
        raise SystemExit("REFUSED: requires STAGE_D_V2_STAGE2_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "calls": 0}
    try:
        ch = chain()
        result.update({"chain": ch, "calls": result["calls"] + 7})
        result["chain_gates"] = {
            "all_endturn_json": all(r["json_ok"] and r["stop"] in ("end_turn", "stop", None)
                                    for r in ch["recs"]),
            "wall_lt_300s": ch["total_wall_s"] < 300.0,
            "fact_ge_050_soft": ch["score"]["old"]["fact"] >= 0.5,
        }
        pj = p_j1ds()
        result["P_J1DS"] = pj
        result["calls"] += 1
        result["s5prime_action_admissible"] = pj["pass"]
    except Halt as e:
        result["halted"] = str(e)
    (OUT / "STAGE2_INTEGRATION_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: result.get(k) for k in ("halted", "calls", "chain_gates",
                                                 "s5prime_action_admissible")},
                     ensure_ascii=False, indent=1), flush=True)
    if "chain" in result:
        print("wall:", result["chain"]["total_wall_s"], "score:", json.dumps(result["chain"]["score"], ensure_ascii=False))


if __name__ == "__main__":
    main()
