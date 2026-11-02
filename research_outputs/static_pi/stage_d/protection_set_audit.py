#!/usr/bin/env python3
"""保护集审计（P0-1，零调用）。

从终局执行记录计算保护集倒退（四元组可追溯），输出三级判定。
基准：PROTECTION_BASELINE.json（由 STAGE_D_PROTECTION_SET_SPEC.md 第三节导出）。

用法：
  python3 protection_set_audit.py RUNS_DIR [--baseline PROTECTION_BASELINE.json]
"""
import argparse
import json
import sys
from pathlib import Path

SLOTS = ["B1", "B2", "B4", "E1", "F3", "U2", "F1", "F2"]
ARMS = ["Static", "R-only", "π-only", "Simple-Dynamic", "Fixed-Composite", "Proposed-Dynamic"]


def default_baseline():
    return {
        "source": "STAGE_D_PROTECTION_SET_SPEC.md §三（合同 f92090b0… + V1.2 §修订四）",
        "reference_correct": {
            # 六臂历史正确槽：所有臂、所有场景均为参考正确（V1.2 冻结声明）
            **{s: {"arms": "ALL", "scenarios": "ALL"} for s in
               ["B1", "B2", "B4", "E1", "F3", "U2"]},
            # 修复臂新增：D2 实测修复臂恢复 6/6（R-only/Fixed/Proposed）
            "F1": {"arms": ["R-only", "Fixed-Composite", "Proposed-Dynamic"],
                   "scenarios": ["S3", "S4", "S5"]},
            "F2": {"arms": ["R-only", "Fixed-Composite", "Proposed-Dynamic"],
                   "scenarios": ["S3", "S4", "S5"]},
        },
        "expected": {
            "B1": "证监立案字01120260037号", "B2": "证监立案字01120260037号",
            "B4": "证监立案字0262026012号", "E1": "1",
            "F3": "2026-10-09", "F1": "2026-10-09", "F2": "2026-10-10",
            "U2": "EXPECTED_UNKNOWN",
        },
    }


def load_records(runs_dir):
    recs = {}
    for p in Path(runs_dir).glob("*.json"):
        if p.name == "FINAL_RUNS.json":
            continue
        try:
            r = json.loads(p.read_text("utf-8"))
        except Exception:
            continue
        if "exec_id" in r and "score" in r:
            recs[r["exec_id"]] = r
    return recs


def claim_ok(rec, slot):
    """终局值层正确性：claim status 以 CORRECT 开头；U2 = 未断言具体值。"""
    claims = (rec.get("score") or {}).get("claim_results") or []
    if slot == "U2":
        # 断言了具体值（unknown_asserted）→ 不正确；abstain/缺失 → 正确（保持不可判定）
        for c in claims:
            if c.get("claim_id", "").endswith("U2") or c.get("fact_id") == "U2" \
                    or c.get("item_id") == "U2":
                st = str(c.get("status", ""))
                return not st.startswith("INCORRECT") and "ASSERT" not in st.upper()
        return True
    for c in claims:
        if c.get("fact_id") == slot:
            return str(c.get("status", "")).startswith("CORRECT")
    return False


def reference_correct(baseline, slot, arm, scenario):
    ref = baseline["reference_correct"][slot]
    arms_ok = ref["arms"] == "ALL" or arm in ref["arms"]
    scen_ok = ref["scenarios"] == "ALL" or scenario in ref["scenarios"]
    return arms_ok and scen_ok


def audit(runs_dir, baseline):
    """R1（操作员 2026-11-02 裁定）：S3/S4/S5 各 384，累计 1,152。"""
    recs = load_records(runs_dir)
    regressions = []
    denom = []
    scenarios = ["S3", "S4", "S5"]
    for sc in scenarios:
        for rep in range(1, 9):
            for arm in ARMS:
                rec = recs.get(f"{arm}|{sc}|r{rep}")
                if rec is None:
                    continue
                for slot in SLOTS:
                    entry = (slot, arm, sc, rep)
                    denom.append(entry)
                    if reference_correct(baseline, slot, arm, sc) and not claim_ok(rec, slot):
                        regressions.append({"slot": slot, "arm": arm,
                                            "scenario": sc, "rep": rep,
                                            "exec_id": rec["exec_id"]})
    n = len(regressions)
    verdict = ("PASS" if n == 0 else
               "PASS WITH REGRESSION" if n == 1 else "FAIL")
    by_scen = {}
    for r in regressions:
        by_scen.setdefault(r["scenario"], []).append(r)
    return {"mode": "R1_per_scenario_384", "slot_runs_enumerated": len(denom),
            "regressions": regressions, "n_regressions": n,
            "by_scenario": {k: len(v) for k, v in by_scen.items()},
            "verdict": verdict,
            "mock_note": "MOCK 数据仅验证软件路径，不作科学结果"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_dir")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    baseline = (json.loads(Path(a.baseline).read_text("utf-8"))
                if a.baseline else default_baseline())
    res = audit(a.runs_dir, baseline)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
