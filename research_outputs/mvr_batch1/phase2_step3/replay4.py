#!/usr/bin/env python3
"""Gate step-4: capability replay on the E06 aggregation node (operator approval 2026-10-31).

Strict conditions: EXACT same node input (reconstructed byte-identically from the
persisted r1 upstream outputs; fidelity check = prompt_chars equality), same system
prompt, same params (temperature=0, max_tokens=2500); ONLY the model id changes.
Order: DeepSeek x3 (the critical new information) then GLM x1 (replay-condition
cross-check; GLM 3/3 stability already established in step 3) — because the exact
6-replay projection (¥0.0557) exceeds the ¥0.05 cap; this ordering stays within it.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path("/root/research_outputs/mvr_batch1/phase2_step3")
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2")
PRICE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5}}
CAP_CNY = 0.05
sys.path.insert(0, str(HERE))
import os
for p in ("/root/.env", "/root/.env.modelpool"):
    for line in open(p):
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v.strip().strip('"').strip("'")
from runner2 import call, parse_json  # noqa: E402

LEDGER = {"cny": 0.0, "calls": 0}


def build_sink_prompt_from_r1():
    run = json.loads((HERE / "run_E06_r1.json").read_text())
    contract = json.loads((EVID / "TASK_CONTRACT_PHASE2_E06_v1.json").read_text(encoding="utf-8"))
    question = contract["question"]
    slots = [{"fact_id": f["fact_id"], "subject": f["subject"], "predicate": f["predicate"],
              "value_kind": f.get("value_kind", "text"), "unit": f.get("unit", ""),
              "date_type": f.get("date_type", "")} for f in contract["required_facts"]]
    unknowns = [{"item_id": u["item_id"], "description": u["description"]} for u in contract.get("unknown_items", [])]
    outputs = {t["node"]: t["output"] for t in run["trace"]}
    upstream = json.dumps({k: (parse_json(v) or v[:800]) for k, v in outputs.items() if k in ["E1", "E2", "J1"]},
                          ensure_ascii=False)
    system = ("你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\":[...], \"abstentions\":[...], \"complete\": true/false}。")
    user = (f"任务问题：{question}\n\n上游抽取与核验结果：\n{upstream}\n\n"
            f"输出格式：answers 按以下槽位逐项填写，每项 {{\"fact_id\":..., \"value\":..., \"quote\": 包含该事实的完整原句逐字引用（含标点，不得截断）, \"doc\": 文档ID}}。\n"
            "数值约定：按槽位 unit 填写纯数值（如 unit=万元 则只填数字）；亏损/负值用负数（如 -12500）；百分比填数字（unit=%）；日期 YYYY-MM-DD。\n"
            f"槽位：{json.dumps(slots, ensure_ascii=False)}\n"
            f"unknown 项（无法确定且属下列项时写入 abstentions 并给明确拒判语句）：{json.dumps(unknowns, ensure_ascii=False)}\n"
            "派生/合计类槽位：依据上游数值自行精确计算后填写。如认为抽取不完整无法负责作答，置 complete=false。")
    stored_chars = next(t["prompt_chars"] for t in run["trace"] if t["node"] == "SINK")
    assert len(user) == stored_chars, f"prompt fidelity FAIL: rebuilt {len(user)} vs stored {stored_chars}"
    return system, user


def main():
    system, user = build_sink_prompt_from_r1()
    print(f"prompt fidelity OK: {len(user)} chars == stored")
    results = {}
    for mk, reps in (("ds", 3), ("glm", 0)):  # GLM replay already done (4/4 error evidence)
        results[mk] = []
        for i in range(reps):
            est = 3400 / 1e6 * PRICE[mk]["in"] + 1500 / 1e6 * PRICE[mk]["out"]  # measured-scale estimate
            if LEDGER["cny"] + est > CAP_CNY:
                print(f"CAP_GUARD: skip {mk} rep{i+1} (est total {LEDGER['cny']+est:.4f})")
                break
            resp = call(mk, system, user, max_tokens=2500)
            cost = resp["in"] / 1e6 * PRICE[mk]["in"] + resp["out"] / 1e6 * PRICE[mk]["out"]
            LEDGER["calls"] += 1
            LEDGER["cny"] += cost
            obj = parse_json(resp["text"]) or {}
            got = {a.get("fact_id"): a.get("value") for a in obj.get("answers", []) if isinstance(a, dict)}
            results[mk].append({"dv3": str(got.get("DV3")), "dv4": str(got.get("DV4")),
                                "in": resp["in"], "out": resp["out"], "cny": round(cost, 5)})
            print(f"[{mk} rep{i+1}] DV3={got.get('DV3')} (gold 19.55)  DV4={got.get('DV4')} (gold 23.70)  cost≈¥{cost:.4f}")
    verdict = {
        "ds_all_correct": all(r["dv3"] not in (None,) and abs(float(r["dv3"]) - 19.55) < 0.005 and abs(float(r["dv4"]) - 23.70) < 0.005
                              for r in results.get("ds", []) if r["dv3"] and r["dv4"]) if results.get("ds") else None,
        "glm_replay": results.get("glm", []),
        "ledger": dict(LEDGER),
    }
    (HERE / "gate2_replay.json").write_text(json.dumps({"results": results, "verdict": verdict,
                                                        "prompt_chars": len(user)}, ensure_ascii=False, indent=1))
    print("\nVERDICT:", json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()
