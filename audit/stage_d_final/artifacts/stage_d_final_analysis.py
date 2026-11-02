#!/usr/bin/env python3
"""Stage D 终局分析入口（零调用；预注册冻结件）。

唯一正式分析程序：主检验（S3+S4 合并 16 对精确符号翻转置换）、
族非伤害门禁、保护集三级判定措辞。

对称性旁证（V1.3.1 A.1 / V1.3.2 §一 预登记）：Hodges–Lehmann 位置差、
固定种子 20261102 的 percentile bootstrap 95% CI、逐对删除（leave-one-out）
敏感性。旁证不替代主检验，不改变判定。

强制：`from exact_perm import exact_paired_perm`；禁止 scipy 作正式 p 值。

输入 JSON（由执行器导出，字段名冻结）：
{
  "experiment_id": "...",
  "pairs": [
    {"scenario": "S3", "rep": 1, "tp_proposed": 15, "tp_simple": 14},
    ... 恰好 8 个 S3 + 8 个 S4，rep 1..8 各一次
  ],
  "protection_regressions": 0
}

保护集计数由预登记保护集审计（V1.2 §修订四：8 槽 × 8 重复 × 6 臂）
产生；本脚本只消费该计数，不重新定义或选择口径。

用法：
  python3 stage_d_final_analysis.py FINAL_RUNS.json [OUT.json]
  python3 stage_d_final_analysis.py --selftest
"""
import json
import random
import statistics
import sys

from exact_perm import exact_paired_perm

ALPHA = 0.05
EXPECTED = {"S3": 8, "S4": 8}


def _validate(payload):
    pairs = payload.get("pairs")
    if not isinstance(pairs, list):
        raise SystemExit("input error: missing 'pairs' list")
    seen = set()
    for p in pairs:
        sc, rep = p.get("scenario"), p.get("rep")
        if sc not in EXPECTED:
            raise SystemExit(f"input error: unknown scenario {sc!r}")
        if isinstance(rep, bool) or not isinstance(rep, int) or not 1 <= rep <= EXPECTED[sc]:
            raise SystemExit(f"input error: bad rep {rep!r} for {sc}")
        key = (sc, rep)
        if key in seen:
            raise SystemExit(f"input error: duplicate pair {key}")
        seen.add(key)
        for k in ("tp_proposed", "tp_simple"):
            v = p.get(k)
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 23:
                raise SystemExit(f"input error: {k} must be int in [0,23] for {key}, got {v!r}")
    for sc, n in EXPECTED.items():
        got = {rep for s, rep in seen if s == sc}
        if got != set(range(1, n + 1)):
            raise SystemExit(f"input error: {sc} expects reps 1..{n}, got {sorted(got)}")
    pr = payload.get("protection_regressions")
    if isinstance(pr, bool) or not isinstance(pr, int) or pr < 0:
        raise SystemExit("input error: 'protection_regressions' must be a non-negative int")
    return pairs, pr


def _walsh_median(diffs):
    """Hodges–Lehmann 配对位置差：全部 Walsh 平均的中位数。"""
    w = sorted((diffs[i] + diffs[j]) / 2
               for i in range(len(diffs)) for j in range(i, len(diffs)))
    n = len(w)
    return w[n // 2] if n % 2 else (w[n // 2 - 1] + w[n // 2]) / 2


def _bootstrap_hl_ci(diffs, n_boot=10000, seed=20261102):
    """固定种子 percentile bootstrap 95% CI（对称性旁证，非主检验）。"""
    rng = random.Random(seed)
    n = len(diffs)
    est = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        est.append(_walsh_median(sample))
    est.sort()
    lo = est[int(0.025 * n_boot)]
    hi = est[int(0.975 * n_boot) - 1]
    return lo, hi


def _leave_one_out(diffs):
    """逐对删除后主检验 p 的范围：结论是否依赖少数极端对。"""
    ps = [exact_paired_perm(diffs[:i] + diffs[i + 1:])["p_value"]
          for i in range(len(diffs))]
    return {"min_p": min(ps), "max_p": max(ps), "per_drop": ps}


def analyze(payload):
    pairs, protection = _validate(payload)
    by_family = {"S3": [], "S4": []}
    for p in sorted(pairs, key=lambda x: (x["scenario"], x["rep"])):
        by_family[p["scenario"]].append(p["tp_proposed"] - p["tp_simple"])
    diffs = by_family["S3"] + by_family["S4"]

    hl = _walsh_median(diffs)
    ci_lo, ci_hi = _bootstrap_hl_ci(diffs)
    loo = _leave_one_out(diffs)

    main = exact_paired_perm(diffs)
    fam = {sc: exact_paired_perm(d) for sc, d in by_family.items()}
    medians = {sc: statistics.median(d) for sc, d in by_family.items()}
    gate_fail = [sc for sc, m in medians.items() if m < 0]
    main_pass = (main["p_value"] < ALPHA) and not gate_fail

    if main_pass and protection == 0:
        verdict = "CONFIRMATORY_QUALITY_AND_PROTECTION_PASS"
        wording = "确认性质量证据成立，保护集通过（可报告机制/安全性验证）"
    elif main_pass and protection == 1:
        verdict = "CONFIRMATORY_QUALITY_MIXED_PROTECTION"
        wording = "主检验获得确认性质量证据，但保护集呈现混合结果"
    elif main_pass and protection >= 2:
        verdict = "PROTECTION_FAIL_OVERALL_NOT_MET"
        wording = "保护集不通过，不满足整体预设判定条件"
    else:
        verdict = "MAIN_TEST_NOT_PASSED"
        if gate_fail:
            wording = (f"主检验未通过：族非伤害门禁失败（中位差<0：{gate_fail}）；"
                       "不得声称确认性质量证据")
        else:
            wording = (f"主检验未通过（p={main['p_value']:.6f} ≥ {ALPHA}）；"
                       "不得声称确认性质量证据")

    return {
        "experiment_id": payload.get("experiment_id"),
        "main_test": {**main, "alpha": ALPHA, "diffs": diffs},
        "families": {sc: {**fam[sc], "diffs": by_family[sc],
                          "median_diff": medians[sc]} for sc in ("S3", "S4")},
        "family_gate_failed": gate_fail,
        "main_pass": main_pass,
        "protection_regressions": protection,
        "protection_level": ("0" if protection == 0 else
                             "1" if protection == 1 else ">=2"),
        "symmetry_diagnostics": {
            "hodges_lehmann": hl,
            "bootstrap_95ci": [ci_lo, ci_hi],
            "bootstrap": {"n_boot": 10000, "seed": 20261102,
                          "method": "percentile"},
            "leave_one_out": loo,
            "note": "对称性旁证；不替代主检验，不改变判定",
        },
        "verdict": verdict,
        "allowed_wording": wording,
        "forbidden": ("全部确认条件通过" if protection != 0 else None),
    }


def _selftest():
    def mk(diffs_by_family):
        pairs = []
        for sc, ds in diffs_by_family.items():
            for i, d in enumerate(ds, 1):
                pairs.append({"scenario": sc, "rep": i,
                              "tp_proposed": 16 + d, "tp_simple": 16})
        return pairs

    cases = [
        ("all-positive", mk({"S3": [2, 1, 1, 2, 1, 2, 1, 1],
                             "S4": [7, 4, 5, 7, 5, 4, 7, 5]}), 0,
         "CONFIRMATORY_QUALITY_AND_PROTECTION_PASS"),
        ("all-positive-prot1", mk({"S3": [2, 1, 1, 2, 1, 2, 1, 1],
                                   "S4": [7, 4, 5, 7, 5, 4, 7, 5]}), 1,
         "CONFIRMATORY_QUALITY_MIXED_PROTECTION"),
        ("all-positive-prot2", mk({"S3": [2, 1, 1, 2, 1, 2, 1, 1],
                                   "S4": [7, 4, 5, 7, 5, 4, 7, 5]}), 2,
         "PROTECTION_FAIL_OVERALL_NOT_MET"),
        ("null-alternating", mk({"S3": [1, -1, 1, -1, 1, -1, 1, -1],
                                 "S4": [2, -2, 2, -2, 2, -2, 2, -2]}), 0,
         "MAIN_TEST_NOT_PASSED"),
        ("gate-fail-S3", mk({"S3": [-1] * 8, "S4": [3] * 8}), 0,
         "MAIN_TEST_NOT_PASSED"),
    ]
    for name, pairs, prot, expected in cases:
        out = analyze({"experiment_id": name, "pairs": pairs,
                       "protection_regressions": prot})
        assert out["verdict"] == expected, (name, out["verdict"], expected)
        sd = out["symmetry_diagnostics"]
        if name.startswith("all-positive"):
            assert sd["hodges_lehmann"] > 0, (name, sd)
            assert sd["bootstrap_95ci"][0] > 0, (name, sd)
        if name == "null-alternating":
            lo, hi = sd["bootstrap_95ci"]
            assert lo <= 0 <= hi, (name, sd)
        print(f"  [{'PASS' if out['verdict'] == expected else 'FAIL'}] {name}: "
              f"p={out['main_test']['p_value']:.6f} "
              f"gate_failed={out['family_gate_failed']} "
              f"prot={prot} -> {out['verdict']} | "
              f"HL={sd['hodges_lehmann']:.3f} "
              f"CI=[{sd['bootstrap_95ci'][0]:.3f},{sd['bootstrap_95ci'][1]:.3f}] "
              f"LOO_max={sd['leave_one_out']['max_p']:.6f}")
    # bool 不得通过整数校验（操作者审计项）
    try:
        analyze({"experiment_id": "bool-reject",
                 "pairs": [{"scenario": "S3", "rep": 1, "tp_proposed": True, "tp_simple": 16}],
                 "protection_regressions": 0})
        raise AssertionError("bool passed int check")
    except SystemExit:
        print("  [PASS] bool-reject: True rejected by strict int check")
    print("  all 5 selftest cases passed")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        _selftest()
        return 0
    if len(sys.argv) < 2:
        raise SystemExit("usage: stage_d_final_analysis.py FINAL_RUNS.json [OUT.json] | --selftest")
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
    out = analyze(payload)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if len(sys.argv) >= 3:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
