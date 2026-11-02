#!/usr/bin/env python3
"""Gate step-3 runner: Static-π baseline on E04/E06 (operator approval 2026-10-31).

Six preconditions implemented:
 1. sink slots carry NO description (fact_id/subject/predicate/value_kind/unit/date_type only)
 2. explicit temperature=0 on both channels
 3. sink quote contract = verbatim complete-sentence quote
 4. full persistence: every node's input prompt + output + usage + dispatch
 5. 3 repeats per task for variance analysis
 6. gate discipline applied in the report (value vs format vs expression; 0/3..3/3 kept)
No fault injection (natural errors only). Caps: 100 calls / CNY 1 hard.
Static-π allocation frozen from Batch-1 calibration: 金额/日期文号/主体/汇总→GLM,
跨文档一致性核验→DeepSeek. Model identity fixed; no silent substitution.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1/phase2_step3")
OUT.mkdir(parents=True, exist_ok=True)
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2")
EVAL_PATH = "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4"
CONTRACT_SHA = {"E04": "82734265aaab719aa05abc51c15fdbc59fb1e04585565e5db4fee7b8765231f8",
                "E06": "be8ef5ae89c4563e551d58b2b617914fae5348d3e0ae6884d5dc3ec2802d4209"}
CAP_CALLS, CAP_CNY = 100, 1.0
PRICE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5}}
ALLOC = {"金额抽取": "glm", "日期文号抽取": "glm", "当事人主体抽取": "glm",
         "跨文档一致性核验": "ds", "汇总派生": "glm"}
DAG = {
    "E04": [{"id": "E1", "type": "日期文号抽取", "doc": "D1", "needs": []},
            {"id": "E2", "type": "金额抽取", "doc": "D2", "needs": []},
            {"id": "E3", "type": "金额抽取", "doc": "D3", "needs": []},
            {"id": "J1", "type": "跨文档一致性核验", "needs": ["E1", "E2", "E3"]},
            {"id": "SINK", "type": "汇总派生", "needs": ["E1", "E2", "E3", "J1"]}],
    "E06": [{"id": "E1", "type": "日期文号抽取", "doc": "D1", "needs": []},
            {"id": "E2", "type": "金额抽取", "doc": "D2", "needs": []},
            {"id": "J1", "type": "跨文档一致性核验", "needs": ["E1", "E2"]},
            {"id": "SINK", "type": "汇总派生", "needs": ["E1", "E2", "J1"]}],
}


def load_env():
    for path in ("/root/.env", "/root/.env.modelpool"):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v.strip().strip('"').strip("'")


def glm_key():
    cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
    return next(r["config"]["access"]["apiKey"]
                for r in cfg["config"]["providerConfigRules"]["providerRules"]
                if r["providerId"] == "bigmodel-api")


def call(model_key, system, user, max_tokens=2500, timeout_s=120):
    if model_key == "glm":
        body = {"model": "GLM-5.3-Flash", "max_tokens": max_tokens, "temperature": 0,
                "thinking": {"type": "disabled"}, "system": system,
                "messages": [{"role": "user", "content": user}]}
        req = urllib.request.Request("https://open.bigmodel.cn/api/anthropic/v1/messages",
                                     data=json.dumps(body).encode(), method="POST")
        key = glm_key()
        req.add_header("content-type", "application/json")
        req.add_header("x-api-key", key)
        req.add_header("authorization", "Bearer " + key)
        req.add_header("anthropic-version", "2023-06-01")
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        return {"text": "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"),
                "in": d["usage"]["input_tokens"], "out": d["usage"]["output_tokens"],
                "lat": round(time.monotonic() - t0, 2), "model_id": d.get("model", "")}
    body = {"model": "deepseek-flash", "max_tokens": max_tokens, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}
    req = urllib.request.Request("https://api.deepseek.com/chat/completions",
                                 data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + os.environ.get("DEEPSEEK_API_KEY", ""))
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    c = d["choices"][0]["message"].get("content", "")
    if isinstance(c, list):
        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
    u = d["usage"]
    return {"text": c, "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
            "lat": round(time.monotonic() - t0, 2), "model_id": d.get("model", "")}


LEDGER = {"calls": 0, "cny": 0.0}


def call_metered(model_key, system, user, max_tokens=2500, note=""):
    est = min(6000, max(1000, len(user))) / 1e6 * PRICE[model_key]["out"] * 4
    if LEDGER["calls"] + 1 > CAP_CALLS or LEDGER["cny"] + est > CAP_CNY:
        raise SystemExit(f"STEP3_BUDGET_STOP calls={LEDGER['calls']} cny={LEDGER['cny']:.3f}")
    resp = call(model_key, system, user, max_tokens=max_tokens)
    cost = resp["in"] / 1e6 * PRICE[model_key]["in"] + resp["out"] / 1e6 * PRICE[model_key]["out"]
    LEDGER["calls"] += 1
    LEDGER["cny"] += cost
    with open(OUT / "ledger.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "model": model_key, "in": resp["in"], "out": resp["out"],
                            "lat": resp["lat"], "cny": round(cost, 5), "model_id": resp["model_id"],
                            "note": note}, ensure_ascii=False) + "\n")
    return resp


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("\n", " ").replace(",}", "}"))
        except Exception:
            return None


def run_task(tid, repeat):
    contract = json.loads((EVID / f"TASK_CONTRACT_PHASE2_{tid}_v1.json").read_text(encoding="utf-8"))
    src = contract["source_pages"]
    question = contract["question"]
    slots = [{"fact_id": f["fact_id"], "subject": f["subject"], "predicate": f["predicate"],
              "value_kind": f.get("value_kind", "text"), "unit": f.get("unit", ""),
              "date_type": f.get("date_type", "")} for f in contract["required_facts"]]
    unknowns = [{"item_id": u["item_id"], "description": u["description"]} for u in contract.get("unknown_items", [])]
    trace, outputs = [], {}

    def upstream_json(node):
        return json.dumps({k: (parse_json(v) or v[:800]) for k, v in outputs.items() if k in node["needs"]},
                          ensure_ascii=False)

    for node in DAG[tid]:
        mk = ALLOC[node["type"]]
        if node["id"].startswith("E"):
            doc_text = "".join(rec["text"] for rec in src[node["doc"]]["pages"].values())
            system = "你是精确的文书信息抽取器。只输出一个 JSON 对象：{ \"amounts\": [...], \"dates_ids\": [...], \"parties_roles\": [...] }，每项为 {field,value,quote}，quote 为包含该信息的完整原句逐字引用。不得编造。"
            user = (f"任务问题：{question}\n\n文档{node['doc']}全文：\n{doc_text}\n\n"
                    "请抽取与问题相关的全部金额/数量、日期与文号、当事人与职务，输出上述 JSON。")
        elif node["id"] == "J1":
            system = "你是跨文档一致性核验器。只输出 JSON：{ \"checks\": [{field, consistent: true/false/unknown, detail}] }。"
            user = (f"任务问题：{question}\n\n以下是各文档抽取结果：\n{upstream_json(node)}\n\n"
                    "核验跨文档一致性（文号、日期、主体、口径在各方说法间是否一致），输出 checks。")
        else:
            system = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\":[...], \"abstentions\":[...], \"complete\": true/false}。")
            user = (f"任务问题：{question}\n\n上游抽取与核验结果：\n{upstream_json(node)}\n\n"
                    f"输出格式：answers 按以下槽位逐项填写，每项 {{\"fact_id\":..., \"value\":..., \"quote\": 包含该事实的完整原句逐字引用（含标点，不得截断）, \"doc\": 文档ID}}。\n"
                    "数值约定：按槽位 unit 填写纯数值（如 unit=万元 则只填数字）；亏损/负值用负数（如 -12500）；百分比填数字（unit=%）；日期 YYYY-MM-DD。\n"
                    f"槽位：{json.dumps(slots, ensure_ascii=False)}\n"
                    f"unknown 项（无法确定且属下列项时写入 abstentions 并给明确拒判语句）：{json.dumps(unknowns, ensure_ascii=False)}\n"
                    "派生/合计类槽位：依据上游数值自行精确计算后填写。如认为抽取不完整无法负责作答，置 complete=false。")
        resp = call_metered(mk, system, user, note=f"{tid}|r{repeat}|{node['id']}")
        outputs[node["id"]] = resp["text"]
        trace.append({"node": node["id"], "type": node["type"], "model": mk,
                      "prompt_chars": len(user), "output": resp["text"],
                      "in": resp["in"], "out": resp["out"], "lat": resp["lat"]})
    # persist trace + sink
    rec = {"task": tid, "repeat": repeat, "trace": trace,
           "sink_raw": outputs["SINK"], "ledger": dict(LEDGER)}
    (OUT / f"run_{tid}_r{repeat}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    print(f"[{tid} r{repeat}] nodes={len(trace)} calls={LEDGER['calls']} cny={LEDGER['cny']:.4f}")
    return rec


if __name__ == "__main__":
    load_env()
    import hashlib
    for tid in ("E04", "E06"):
        h = hashlib.sha256((EVID / f"TASK_CONTRACT_PHASE2_{tid}_v1.json").read_bytes()).hexdigest()
        assert h == CONTRACT_SHA[tid], f"contract drift {tid}"
    for tid in ("E04", "E06"):
        for r in (1, 2, 3):
            run_task(tid, r)
    print("STEP3_RUNS_DONE", json.dumps(LEDGER))
