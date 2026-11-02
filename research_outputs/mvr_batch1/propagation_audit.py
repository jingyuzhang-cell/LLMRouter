#!/usr/bin/env python3
"""Phase-1 propagation audit (zero model calls). Operator directive 2026-10-31.

Reconstructs the exact DAG/dispatch from runner.py code (the code IS the spec),
maps every required fact's information path onto it, classifies terminal errors
(common / fixable / harm) and their switch exposure, measures format-drift rates,
and states the request-body evidence boundary.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1")
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence")
sys.path.insert(0, str(OUT))
sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
from terminal_quality import _value_equal, _derived_value_ok  # noqa: E402

import runner  # noqa: E402  (module import is call-free; Ledger replays file only)

CONTRACTS = runner.load_contracts()
PLAN = json.loads((OUT / "plan.json").read_text())
PAIRS = [json.loads(l) for l in (OUT / "pairs.jsonl").read_text().splitlines() if l.strip()]
FACTS = {tid: {f["fact_id"]: f for f in c["required_facts"]} for tid, c in CONTRACTS.items()}


def fact_ok(tid, fact, value):
    if value is None:
        return False
    if fact.get("derivation"):
        return _derived_value_ok({"value": value}, fact, FACTS[tid])
    return _value_equal({"value": value}, fact)


def claim_of(arm_terminal, fid):
    for c in arm_terminal["claims"]:
        if c.get("fact_id") == fid:
            return c
    return None


def dag_map(tid):
    """Exact reconstruction: nodes in execution order, fault idx, arm models."""
    nodes, _ = runner.build_dag(CONTRACTS, tid, PLAN["tstar"], PLAN["allocation"])
    order = ([n for n in nodes if n["id"].startswith("E")]
             + [n for n in nodes if n["id"].startswith("F")]
             + [n for n in nodes if n["id"] == "SINK"])
    fault_idx = next(i for i, n in enumerate(order) if n["type"] == PLAN["tstar"])
    rows = []
    for i, n in enumerate(order):
        a_model = PLAN["allocation"][n["type"]]
        b_model = a_model
        if i > fault_idx and n["type"] == PLAN["tstar"]:
            b_model = PLAN["other"]
        rows.append({"idx": i, "node": n["id"], "type": n["type"],
                     "doc": n.get("doc", ""), "page": n.get("doc_text", "")[:0] or "",
                     "A": a_model, "B": b_model,
                     "role": ("FAULT(prefix注入)" if i == fault_idx
                              else ("prefix" if i < fault_idx else "fork后"))})
    return rows, fault_idx


def fact_path_exposure(tid):
    """Map each fact's evidence (doc,page) to its extractor E-node; mark switch exposure."""
    nodes, _ = runner.build_dag(CONTRACTS, tid, PLAN["tstar"], PLAN["allocation"])
    order = ([n for n in nodes if n["id"].startswith("E")]
             + [n for n in nodes if n["id"].startswith("F")]
             + [n for n in nodes if n["id"] == "SINK"])
    fault_idx = next(i for i, n in enumerate(order) if n["type"] == PLAN["tstar"])
    # page-level mapping: E nodes are created per flattened (doc, page)
    flat = runner.doc_pages(CONTRACTS[tid]["_source_pages"])
    e_by_docpage = {}
    ei = 0
    for i, n in enumerate(order):
        if n["id"].startswith("E"):
            doc_id, page, _ = flat[ei]
            e_by_docpage[(doc_id, page)] = (i, n)
            ei += 1
    out = {}
    for fid, f in FACTS[tid].items():
        exposures = []
        for e in sorted(f.get("source_evidence", []), key=lambda x: str(x.get("doc_id"))):
            hit = e_by_docpage.get((e.get("doc_id"), e.get("page")))
            if hit is None:
                exposures.append({"doc": e.get("doc_id"), "page": e.get("page"),
                                  "extractor": None, "switched": None})
                continue
            idx, n = hit
            exposures.append({"doc": e.get("doc_id"), "page": e.get("page"), "extractor": n["id"],
                              "extractor_type": n["type"],
                              "switched_in_B": idx > fault_idx and n["type"] == PLAN["tstar"]})
        out[fid] = {"evidence_docs": sorted({e.get("doc_id") for e in f.get("source_evidence", [])}), "exposures": exposures,
                    "any_extractor_switched": any(e.get("switched_in_B") for e in exposures),
                    "crosses_F_layer": True}  # sink consumes F1-F3 outputs in both arms
    return out


def error_taxonomy():
    tax = defaultdict(lambda: defaultdict(int))
    detail = {"fixable": [], "harm": [], "common": []}
    for p in PAIRS:
        tid = p["task"]
        for fid, f in FACTS[tid].items():
            ca = claim_of(p["arms"]["A"]["terminal"], fid)
            cb = claim_of(p["arms"]["B"]["terminal"], fid)
            okA = fact_ok(tid, f, ca.get("value") if ca else None)
            okB = fact_ok(tid, f, cb.get("value") if cb else None)
            if okA and okB:
                tax[tid]["both_right"] += 1
            elif not okA and not okB:
                tax[tid]["common_wrong"] += 1
                detail["common"].append({"task": tid, "pair": p["pair"], "fact": fid})
            elif not okA and okB:
                tax[tid]["fixable_A_wrong_B_right"] += 1
                detail["fixable"].append({"task": tid, "pair": p["pair"], "fact": fid})
            else:
                tax[tid]["harm_A_right_B_wrong"] += 1
                detail["harm"].append({"task": tid, "pair": p["pair"], "fact": fid})
    return dict(tax), detail


def suffix_rate():
    pat = re.compile(r"(元|年|万元|日|月)$")
    out = {}
    for p in PAIRS:
        for arm in ("A", "B"):
            vals = [str(c.get("value")) for c in p["arms"][arm]["terminal"]["claims"]]
            n = sum(1 for v in vals if pat.search(v) and re.search(r"\d", v))
            out[f"{p['task']}_p{p['pair']}_{arm}"] = f"{n}/{len(vals)}"
    return out


def request_body_boundary():
    src = (OUT / "runner.py").read_text()
    return {
        "GLM body 字段": ["model", "max_tokens", "thinking.type=disabled", "system", "messages"],
        "DS body 字段": ["model", "max_tokens", "messages", "response_format=json_object", "thinking.type=disabled"],
        "temperature": "两通道请求体均未包含（代码级事实）；实际采样温度为平台默认值（未记录具体值）",
        "请求体持久化": "未持久化（ledger 仅记 usage/latency/model_id）——'方差由温度默认导致'保持为假设，不被代码事实证明",
        "证据边界": "可证：温度未发送、thinking 已禁用、其余字段如上；不可证：平台默认温度数值与服务端采样行为",
    }


if __name__ == "__main__":
    result = {}
    for tid in ("MVR1", "MVR2"):
        rows, fault_idx = dag_map(tid)
        result[f"{tid}_dag"] = {"nodes": rows, "fault_idx": fault_idx,
                                "n_switched_B": sum(1 for r in rows if r["B"] != r["A"])}
        result[f"{tid}_fact_paths"] = fact_path_exposure(tid)
    tax, detail = error_taxonomy()
    result["error_taxonomy"] = tax
    result["taxonomy_detail"] = detail
    result["suffix_rate_per_arm"] = suffix_rate()
    result["request_body_boundary"] = request_body_boundary()
    # switch-exposure of each taxonomy class
    expo = {}
    for cls in ("fixable", "harm", "common"):
        expo[cls] = {}
        for d in detail[cls]:
            fp = result[f"{d['task']}_fact_paths"][d["fact"]]
            key = f"{d['task']}:{'抽取器被切换' if fp['any_extractor_switched'] else '抽取器未切换'}"
            expo[cls][key] = expo[cls].get(key, 0) + 1
    result["taxonomy_switch_exposure"] = expo
    (OUT / "propagation_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in result.items() if not k.endswith("_fact_paths") and k != "taxonomy_detail"},
                     ensure_ascii=False, indent=1))
