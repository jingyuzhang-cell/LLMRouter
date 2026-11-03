#!/usr/bin/env python3
"""Stage D 阶段 2b：A‴ 动态整链（授权 2026-11-03；7 次调用，累计 12/15）。

A‴ 路由：E1-E4=DS@4000（串行，K_ds=1 语义）；J1=GLM-low@8192；
J2=DS@4000；SINK=DS@4000；FMT=本地 apply_format_rules；
终端评分=旧合同 v2.1 + V3 并列 + 完全正确率。

GO 门：STAGE_D_V2_STAGE2B_GO=1。停止规则：任一节点 HTTP 错误/截断/JSON 失败 → 立即停止。
全部节点响应全文落盘（v2_pilot/stage2b/nodes/）。
"""
import hashlib
import json
import os
import sys
import time
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

OUT = STAGE_D / "v2_pilot" / "stage2b"
NODES_DIR = OUT / "nodes"
GLM_URL = "https://open.bigmodel.cn/api/anthropic/v1/messages"
GLM_CAP, DS_CAP = 8192, 4000


class Halt(Exception):
    pass


def glm_call(system, user, timeout_s=300):
    key = os.environ.get("STAGE_D_GLM_KEY", "").strip()
    if not key:
        raise Halt("STAGE_D_GLM_KEY not set")
    body = {"model": "GLM-5.3-Flash", "max_tokens": GLM_CAP, "system": system,
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


def ds_call(system, user, timeout_s=300):
    t0 = time.monotonic()
    r = transport.openai_call("deepseek", system, user, DS_CAP, timeout_s, 0)
    r["lat"] = round(time.monotonic() - t0, 2)
    return r


def step(name, backend, system, user):
    print(f"--- {name} ({backend}) ---", flush=True)
    try:
        r = glm_call(system, user) if backend == "glm" else ds_call(system, user)
    except Halt:
        raise
    except Exception as e:  # noqa: BLE001
        raise Halt(f"{name}: transport error {e!r}")
    parsed = extract_json(r.get("text") or "")
    rec = {"node": name, "backend": backend, "in": r.get("in"), "out": r.get("out"),
           "stop": r.get("stop"), "wall_s": r.get("lat"),
           "text_chars": len(r.get("text") or ""), "json_ok": parsed is not None,
           "prompt_sha256": hashlib.sha256((system + "||" + user).encode()).hexdigest()}
    NODES_DIR.mkdir(parents=True, exist_ok=True)
    (NODES_DIR / f"{name}.json").write_text(
        json.dumps({**rec, "system": system, "user": user, "text": r.get("text")},
                   ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({k: rec[k] for k in ("node", "backend", "stop", "in", "out", "wall_s", "json_ok")}),
          flush=True)
    if r.get("stop") not in ("end_turn", "stop", None):
        raise Halt(f"{name}: stop={r.get('stop')} 截断 -> 停止整链")
    if parsed is None:
        raise Halt(f"{name}: JSON 不可解析 -> 停止整链")
    return rec, r.get("text")


def main():
    if os.environ.get("STAGE_D_V2_STAGE2B_GO") != "1":
        raise SystemExit("REFUSED: requires STAGE_D_V2_STAGE2B_GO=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("REFUSED: DEEPSEEK_API_KEY not set")
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"),
              "routing": {"E*": "DS@4000", "J1": "GLM-low@8192", "J2": "DS@4000",
                          "SINK": "DS@4000", "FMT": "local"}}
    t0 = time.monotonic()
    recs, texts = [], {}
    try:
        for n in ("E1", "E2", "E3", "E4"):
            rec, text = step(n, "ds", E_SYSTEM, e_user(n))
            recs.append(rec)
            texts[n] = text
        rec, text = step("J1", "glm", J1_SYSTEM, j1_user(json.dumps(
            {"E1": texts["E1"], "E2": texts["E2"]}, ensure_ascii=False)))
        recs.append(rec)
        texts["J1"] = text
        rec, text = step("J2", "ds", J2_SYSTEM, j2_user(json.dumps(
            {"J1": texts["J1"], "E3": texts["E3"], "E4": texts["E4"]}, ensure_ascii=False)))
        recs.append(rec)
        texts["J2"] = text
        rec, text = step("SINK", "ds", SINK_SYSTEM, sink_user(json.dumps(
            {"J1": texts["J1"], "J2": texts["J2"]}, ensure_ascii=False)))
        recs.append(rec)
        texts["SINK"] = text
    except Halt as e:
        result["halted"] = str(e)
        result["recs"] = recs
        result["calls"] = len(recs)
        (OUT / "STAGE2B_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps({"halted": str(e), "calls": len(recs)}, ensure_ascii=False))
        return 2
    total_wall = round(time.monotonic() - t0, 2)
    # FMT + 终端评分（零调用）
    sink_parsed = extract_json(texts["SINK"])
    parsed_fmt, fmt_log = apply_format_rules(json.loads(json.dumps(sink_parsed)))
    term = build_terminal_output(parsed_fmt)
    contracts = {}
    for label, fname in (("old", "TASK_CONTRACT_PHASE2B_v2_1.json"),
                         ("v3", "TASK_CONTRACT_PHASE2B_v3_DRAFT.json")):
        c = json.loads((Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2B/")
                        / fname).read_text("utf-8"))
        src = c.pop("source_pages")
        q = evaluate_terminal_quality(c, term, src)
        tp = sum(1 for x in q["claim_results"] if x["status"].startswith("CORRECT"))
        full = sum(1 for x in q["claim_results"] if x["status"] == "CORRECT_GOLD")
        n = max(len(q["claim_results"]), 1)
        contracts[label] = {"fact": round(q["dimensions"]["fact_correctness"], 4),
                            "evidence": round(q["dimensions"]["evidence_support"], 4),
                            "Q_raw": round(q["Q_raw"], 4) if q["Q_raw"] is not None else None,
                            "tp": tp, "n_claims": len(q["claim_results"]),
                            "full_correct_rate": round(full / n, 4)}
    docs = [a.get("doc") for a in (parsed_fmt or {}).get("answers", []) if isinstance(a, dict)]
    result.update({
        "recs": recs, "calls": len(recs), "total_wall_s": total_wall,
        "fmt_log": fmt_log, "score": contracts,
        "citation_spot_check": {"n_answers": len(docs),
                                "legal_doc_ids": sum(1 for d0 in docs if str(d0) in ("D1", "D2", "D3", "D4")),
                                "sample": docs[:6]},
        "tokens": {"in": sum(r["in"] for r in recs), "out": sum(r["out"] for r in recs)},
        "accounting_yuan": round(sum((r["in"] or 0) * 0.8e-6 + (r["out"] or 0) * 2.8e-6
                                     for r in recs), 8)})
    result["gates"] = {
        "hard_all_endturn_json": all(r["json_ok"] and r["stop"] in ("end_turn", "stop", None) for r in recs),
        "hard_wall_lt_300s": total_wall < 300.0,
        "hard_wall_lt_240s_derived": total_wall < 240.0,
        "soft_fact_ge_050_old": contracts["old"]["fact"] >= 0.5,
        "soft_fact_ge_050_v3": contracts["v3"]["fact"] >= 0.5,
    }
    (OUT / "STAGE2B_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps({"calls": result["calls"], "total_wall_s": total_wall,
                      "gates": result["gates"], "score": contracts,
                      "citation": result["citation_spot_check"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
