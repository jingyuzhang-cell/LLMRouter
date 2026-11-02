#!/usr/bin/env python3
"""E04-J1 probe (operator GO 2026-10-31, E04_J1_GO=1). Six fresh calls on the
frozen r1 upstream snapshot: GLM x3 then DS x3, temperature=0, hard cap CNY 0.05
(per-call guard; if the last call would breach, skip and record arithmetic).
No gold in prompts; P6 diagnostic only; no retries; no model substitution."""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path("/root/research_outputs/mvr_batch1/phase2_step3")
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2")
PRICE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5}}
CAP_CNY = 0.05
GOLD = {"P1": "DIFFERENT_EVENT", "P2": "SAME_EVENT", "P3": "DIFFERENT_EVENT",
        "P4": "DIFFERENT_EVENT", "P5": "SAME_EVENT"}

sys.path.insert(0, str(HERE))
for p in ("/root/.env", "/root/.env.modelpool"):
    for line in open(p):
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k] = v.strip().strip('"').strip("'")
from runner2 import call, parse_json  # noqa: E402


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main():
    # ---- pre-flight: frozen r1 upstream identity ----
    run = json.loads((HERE / "run_E04_r1.json").read_text())
    up = {t["node"]: t["output"] for t in run["trace"] if t["node"] in ("E1", "E2", "E3")}
    up_hash = sha(json.dumps(up, ensure_ascii=False))
    assert up_hash.startswith("e27950727b63168c"), f"upstream hash mismatch {up_hash}"
    upstream_json = json.dumps({k: (parse_json(v) or v[:800]) for k, v in up.items()}, ensure_ascii=False)
    contract = json.loads((EVID / "TASK_CONTRACT_PHASE2_E04_v1.json").read_text(encoding="utf-8"))
    question = contract["question"]

    pairs = [
        {"pair_id": "P1",
         "date_a": "2025-12-19｜公司及实控人收到中国证监会《立案告知书》（据D2/D3）",
         "date_b": "2025-12-20｜公司在上海证券交易所网站披露《关于公司及实控人收到立案告知书的公告》（公告编号2025-053，据D1）"},
        {"pair_id": "P2",
         "date_a": "2026-09-11｜公司收到上海证监局《行政处罚事先告知书》（据D2）",
         "date_b": "2026-09-11｜公司收到上海证监局《行政处罚事先告知书》（据D3）"},
        {"pair_id": "P3",
         "date_a": "2026-10-12｜公司股票收盘价格首次低于1元（据D3）",
         "date_b": "2026-09-23｜公司股票收盘市值首次低于3亿元（据D3）"},
        {"pair_id": "P4",
         "date_a": "2025-12-19｜收到《立案告知书》（据D2）",
         "date_b": "2026-09-11｜收到《行政处罚事先告知书》（据D2）"},
        {"pair_id": "P5",
         "date_a": "2026-10-12｜收盘价首次低于1元当日（据D3）",
         "date_b": "2026-10-12｜当日收盘价0.96元/股、总市值2.24亿元（据D3）"},
    ]
    system = ("你是跨文档事实关系核验器。只输出一个 JSON 对象："
              "{\"checks\":[{\"pair_id\":..., \"relation\":..., \"date_type_a\":..., \"date_type_b\":..., \"reasoning\":...}]}。"
              "relation 只能取 SAME_EVENT（同一实际事件）/ DIFFERENT_EVENT（不同实际事件，即使同属一个案件）/"
              "CONFLICT（同一事件同一性质日期但来源矛盾）/ UNKNOWN（证据不足）。"
              "date_type 用简短英文标签（如 receipt/publication/first_below_1yuan）。reasoning 每项不超过10字。")
    user = (f"任务问题：{question}\n\n以下是各文档结构化抽取结果（冻结快照）：\n{upstream_json}\n\n"
            f"请对下列日期对逐项判定 relation 及两侧 date_type：\n{json.dumps(pairs, ensure_ascii=False)}\n"
            "仅依据给定材料判断；证据不足用 UNKNOWN，不要猜测。")

    prompt_hash = sha(system + "||" + user)
    print(f"pre-flight OK: upstream={up_hash[:16]}… prompt_sha256={prompt_hash[:16]}… chars={len(user)}")

    ledger = {"calls": 0, "cny": 0.0}
    raw = []
    results = {"glm": [], "ds": []}
    for mk in ("glm", "glm", "glm", "ds", "ds", "ds"):
        est = 4600 / 1e6 * PRICE[mk]["in"] + 700 / 1e6 * PRICE[mk]["out"]
        if ledger["cny"] + est > CAP_CNY:
            print(f"CAP_GUARD: skip {mk} call (spent ¥{ledger['cny']:.4f}, est +¥{est:.4f} > ¥{CAP_CNY})")
            continue
        resp = call(mk, system, user, max_tokens=900)
        cost = resp["in"] / 1e6 * PRICE[mk]["in"] + resp["out"] / 1e6 * PRICE[mk]["out"]
        ledger["calls"] += 1
        ledger["cny"] += cost
        obj = parse_json(resp["text"]) or {}
        got = {c.get("pair_id"): c for c in obj.get("checks", []) if isinstance(c, dict)}
        per = {pid: (got.get(pid, {}).get("relation"), GOLD[pid]) for pid in GOLD}
        results[mk if len(results[mk]) < 3 else mk].append(
            {"per_pair": {p: {"out": v[0], "gold": v[1], "ok": v[0] == v[1]} for p, v in per.items()},
             "in": resp["in"], "out": resp["out"], "cny": round(cost, 5), "model_id": resp["model_id"]})
        raw.append({"model": mk, "in": resp["in"], "out": resp["out"], "lat": resp["lat"],
                    "cny": round(cost, 5), "text": resp["text"][:1500]})
        ok_n = sum(1 for v in per.values() if v[0] == v[1])
        print(f"[{mk} #{results[mk].__len__()}] 正确 {ok_n}/5  in={resp['in']} out={resp['out']} cost=¥{cost:.4f}")

    # ---- verdict ----
    def stable_all_correct(model):
        rs = results[model]
        return len(rs) == 3 and all(all(v["ok"] for v in r["per_pair"].values()) for r in rs)
    def stable_all_wrong(model):
        rs = results[model]
        return len(rs) == 3 and all(not any(v["ok"] for v in r["per_pair"].values()) for r in rs)
    divergence_pairs = None
    if len(results["glm"]) == 3 and len(results["ds"]) == 3:
        for pid in GOLD:
            g = [r["per_pair"][pid]["ok"] for r in results["glm"]]
            d = [r["per_pair"][pid]["ok"] for r in results["ds"]]
            if all(g) and not any(d):
                divergence_pairs = (divergence_pairs or []) + [pid]
            if all(d) and not any(g):
                divergence_pairs = (divergence_pairs or []) + [pid]
    verdict = {"glm_3of3_all_correct": stable_all_correct("glm"),
               "ds_3of3_all_correct": stable_all_correct("ds"),
               "repeatable_divergence_pairs": divergence_pairs,
               "n_calls": ledger["calls"], "cny": round(ledger["cny"], 4),
               "upstream_sha256": up_hash, "prompt_sha256": prompt_hash}
    (HERE / "probe5_result.json").write_text(
        json.dumps({"verdict": verdict, "results": results, "raw": raw}, ensure_ascii=False, indent=1))
    print("\nVERDICT:", json.dumps(verdict, ensure_ascii=False))


if __name__ == "__main__":
    main()
