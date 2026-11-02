#!/usr/bin/env python3
"""MVR-BATCH-1 sensitivity analysis (zero model calls, archives only). Operator 2026-10-31.

 S1 recompute A/B deltas excluding leaked facts (MVR2: FA2,FB4,FC1,FC2,FD2,FD3,FH1;
    robustness tier: also exclude MVR1 formula-hint facts F1,F7,F10)
 S2 dependency-path trace for MVR2-p4 FD facts (structural; corrects the earlier
    overclaim "switch-independent": FD path runs E->F*(switched in B)->SINK)
 S3 where the node advantage dies: calibration F1 vs per-fact terminal correctness
    in the T* domain (which facts wrong in both arms vs A-only)
 S4 temperature-deviation impact scope: repeated-sampling variance measured from
    identical-prompt repeats (A arm across p1-p4), value-form instability per fact
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1")
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence")
sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")
from terminal_quality import _value_equal, _derived_value_ok  # noqa: E402

LEAK_MVR2 = {"FA2", "FB4", "FC1", "FC2", "FD2", "FD3", "FH1"}
HINT_MVR1 = {"F1", "F7", "F10"}
TSTAR_DOMAIN = {"MVR1": {"F11", "F12", "F13", "F14", "F15"},
                "MVR2": {"FE1", "FE2", "FE3", "FF1", "FF2", "FF3", "FF4"}}


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


CONTRACTS = {}
for tid, p in (("MVR1", "MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json"),
               ("MVR2", "MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json")):
    c = json.loads((EVID / p).read_text(encoding="utf-8"))
    CONTRACTS[tid] = {f["fact_id"]: f for f in c["required_facts"]}
PAIRS = [json.loads(l) for l in (OUT / "pairs.jsonl").read_text().splitlines() if l.strip()]


def claim_of(arm_or_terminal, fid):
    terminal = arm_or_terminal.get("terminal", arm_or_terminal)
    for c in terminal["claims"]:
        if c.get("fact_id") == fid:
            return c
    return None


def fact_ok(tid, fact, value):
    if value is None:
        return False
    if fact.get("derivation"):
        return _derived_value_ok({"value": value}, fact, CONTRACTS[tid])
    return _value_equal({"value": value}, fact)


def restricted_f1(p, tid, arm, exclude):
    tp = fp = fn = 0
    for fid, fact in CONTRACTS[tid].items():
        if fid in exclude:
            continue
        c = claim_of(p["arms"][arm]["terminal"], fid)
        if c is None or c.get("value") is None:
            fn += 1
        elif fact_ok(tid, fact, c.get("value")):
            tp += 1
        else:
            fp += 1
            fn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return 2 * prec * rec / (prec + rec) if prec + rec else 0.0


def s1():
    rows = []
    for tierset, label in ((set(), "原始(全事实)"),
                           (LEAK_MVR2, "排除MVR2数值泄漏7项"),
                           (LEAK_MVR2 | HINT_MVR1, "再排除MVR1公式提示3项")):
        per_pair, per_event = [], defaultdict(list)
        for p in PAIRS:
            fA = restricted_f1(p, p["task"], "A", tierset)
            fB = restricted_f1(p, p["task"], "B", tierset)
            per_pair.append(round(fB - fA, 4))
            per_event[p["task"]].append(fB - fA)
        rows.append({"tier": label, "per_pair_d_f1": per_pair,
                     "batch_mean": round(sum(per_pair) / len(per_pair), 4),
                     "per_event_mean": {k: round(sum(v) / len(v), 4) for k, v in per_event.items()}})
    return rows


def s2():
    p = next(x for x in PAIRS if x["task"] == "MVR2" and x["pair"] == 4)
    paths = {}
    for fid in ("FD1", "FD2", "FD3"):
        paths[fid] = {
            "数据路径": "E页抽取(当事人主体轮换,两臂同GLM) → F1-F3聚合(日期文号类,B臂=DeepSeek/A臂=GLM) → SINK(两臂同GLM)",
            "A值": str((claim_of(p["arms"]["A"], fid) or {}).get("value")),
            "B值": str((claim_of(p["arms"]["B"], fid) or {}).get("value")),
            "结论": "两臂FD差异只能产生自F层(路径上唯一不同的执行者)；'与切换无关'不成立，修正为：FD格式漂移经F层传递影响sink的可能性无法排除（F层输出未持久化，为数据缺口）",
        }
    return paths


def s3():
    out = {}
    for tid in ("MVR1", "MVR2"):
        wrong = defaultdict(lambda: {"A": 0, "B": 0, "runs": 0})
        for p in PAIRS:
            if p["task"] != tid:
                continue
            for fid in TSTAR_DOMAIN[tid]:
                fact = CONTRACTS[tid][fid]
                for arm in ("A", "B"):
                    c = claim_of(p["arms"][arm], fid)
                    ok = fact_ok(tid, fact, c.get("value")) if c else False
                    if not ok:
                        wrong[fid][arm] += 1
        rows = []
        for fid in sorted(TSTAR_DOMAIN[tid]):
            a, b = wrong[fid]["A"], wrong[fid]["B"]
            if a or b:
                rows.append({"fact": fid, "A错次": a, "B错次": b, "共同错": min(a, b), "仅A错": max(0, a - b), "仅B错": max(0, b - a)})
        out[tid] = rows
    return out


def s4():
    """A臂跨4次重复=同提示同模型的重复采样；统计每事实值形式的不稳定度。"""
    out = {}
    for tid in ("MVR1", "MVR2"):
        unstable, total = [], 0
        for fid, fact in CONTRACTS[tid].items():
            forms = []
            for p in PAIRS:
                if p["task"] != tid:
                    continue
                c = claim_of(p["arms"]["A"], fid)
                forms.append(norm(c.get("value")) if c else None)
            total += 1
            distinct = len(set(forms))
            if distinct > 1:
                unstable.append({"fact": fid, "distinct_value_forms_across_4_repeats": distinct,
                                 "forms": [f[:24] for f in forms]})
        out[tid] = {"n_facts": total, "n_unstable_in_A_repeats": len(unstable), "examples": unstable[:6]}
    return out


if __name__ == "__main__":
    res = {"S1_leak_excluded_deltas": s1(), "S2_p4_dependency_trace": s2(),
           "S3_tstar_domain_wrong_pattern": s3(), "S4_sampling_variance": s4()}
    (OUT / "sensitivity_analysis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))
