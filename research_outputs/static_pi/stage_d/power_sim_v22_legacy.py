#!/usr/bin/env python3
"""终局实验功效模拟 V2.2（与正式分析同一精确符号翻转置换程序）。

V2.1 的缺陷（操作者终审阻断项）：
  - 使用 scipy.wilcoxon(mode='exact')。scipy 文档明示 ties/zeros 下不保证
    精确 p；而 TP 配对差值是离散整数，必然出现并列绝对值与零差。
  - 模拟的是连续差值，与正式分析的整数 TP 差值口径不一致。
  - 因此 V2.1 的 0.818 只对连续、无并列情形成立，不能作为正式分析功效。

V2.2 修订：
  - 正式分析与功效模拟共用 exact_perm.exact_paired_perm()（全枚举 2^m）。
  - 主报告为整数化差值（实际 TP 差值必为整数）功效；
    连续差值仅作敏感性对照（并与 scipy 做无并列情形的交叉验证）。
  - nsim=20000；基准场景三种子收敛，报告均值与极差。

历史差异记录（如实保留）：
  V1（正态近似+连续校正）0.846 — 偏高 ~4pp，弃用
  操作者独立复现（20000 次，scipy 连续）~0.819
  V2（scipy exact, nsim=1200）0.807 — Monte Carlo 噪声
  V2.1（scipy exact, nsim=20000，三种子）0.817/0.823/0.816 → 0.818（连续）
  V1.3 初稿（exact_perm, nsim=500）0.736 — **MC 标准误 ±0.022，不可作结论**
  V2.2（exact_perm, nsim=20000，整数化）→ 见本次输出
"""
import json
import sys
from math import comb

from exact_perm import exact_paired_perm, simulate_power

NSIM = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
BASELINE_SEEDS = [20261102, 42, 12345]
SINGLE_SEED = [20261102]

SCENARIOS = [("基准保守", 0.25, 1.0, 1.2),
             ("更保守", 0.30, 0.8, 1.3),
             ("乐观(接近D2实测)", 0.20, 2.0, 1.5)]


def crosscheck_scipy(n_cases=2000, seed=7):
    """无并列连续差值上，本实现 == scipy exact（验证实现正确性）。"""
    import random
    from scipy.stats import wilcoxon
    rng = random.Random(seed)
    checked = mismatches = 0
    for _ in range(n_cases):
        d = [0.0 if rng.random() < 0.25 else rng.gauss(1.0, 1.2)
             for _ in range(16)]
        p_ours = exact_paired_perm(d)["p_value"]
        try:
            _, p_sp = wilcoxon(d, alternative='greater', zero_method='wilcox',
                               method='exact')
        except Exception:
            continue
        checked += 1
        if abs(p_ours - p_sp) > 1e-9:
            mismatches += 1
    return checked, mismatches


def main():
    out = {"nsim": NSIM, "test": "exact_sign_flip_enumeration",
           "implementation": "exact_perm.exact_paired_perm", "scenarios": {}}
    print(f"=== 功效模拟 V2.2（同一精确置换程序；nsim={NSIM}）===")
    print("生成模型: D=0 w.p. p_tie; else N(mu,sd)；整数化=取整（实际 TP 差）\n")

    for label, pt, mu, sd in SCENARIOS:
        seeds = BASELINE_SEEDS if label == "基准保守" else SINGLE_SEED
        ints, conts = [], []
        for s in seeds:
            ints.append(simulate_power(16, pt, mu, sd, NSIM, s, True))
            conts.append(simulate_power(16, pt, mu, sd, NSIM, s, False))
        mean_i = sum(ints) / len(ints)
        mean_c = sum(conts) / len(conts)
        out["scenarios"][label] = {
            "p_tie": pt, "mu": mu, "sd": sd, "seeds": seeds,
            "integer": ints, "integer_mean": mean_i,
            "continuous": conts, "continuous_mean": mean_c,
            "delta_integer_minus_continuous": mean_i - mean_c}
        print(f"  {label}: 整数化 {mean_i:.4f}（种子 {', '.join(f'{x:.4f}' for x in ints)}）"
              f" | 连续 {mean_c:.4f} | 差 {mean_i - mean_c:+.4f}")

    p_main = out["scenarios"]["基准保守"]["integer_mean"]
    s3 = simulate_power(8, 0.35, 1.0, 1.2, NSIM, 20261102, True)
    out["S3_single_family_integer"] = s3
    print(f"\n  S3 单族 8 对（整数化, nsim={NSIM}）: {s3:.4f}")

    s5 = {wr: sum(comb(8, k) * wr ** k * (1 - wr) ** (8 - k) for k in (7, 8))
          for wr in (0.70, 0.80, 0.90)}
    out["S5_sign_test_power_ge7of8"] = s5
    print("\n=== S5 时延终点（单侧符号检验 N=8，需 ≥7/8）===")
    for wr, p in s5.items():
        print(f"  真实胜率 {wr:.0%}: P(≥7/8) = {p:.4f}")

    p_gate, p_q1, p_qual, p_prot0 = 0.90, 0.85 ** 3, 0.95, 0.85
    p_s5 = s5[0.80]
    layers = {
        "L1_main": p_main,
        "L2_main_x_gate": p_main * p_gate,
        "L3_all_conditions": p_main * p_gate * p_q1 * p_s5 * p_qual * p_prot0,
        "L3_prime_protection_1": p_main * p_gate * p_q1 * p_s5 * p_qual * 0.95,
    }
    out["layers"] = {**layers,
                     "assumptions": {"gate": p_gate, "Q1_three_families": p_q1,
                                     "S5_ge7of8@0.8": p_s5,
                                     "quality_gate": p_qual,
                                     "protection_0": p_prot0,
                                     "protection_1": 0.95}}
    print("\n=== 分层功效（整数化精确置换）===")
    print(f"  层1 主检验（S3+S4 合并, N=16）              = {layers['L1_main']:.4f}")
    print(f"  层2 主检验 + 族非伤害门禁                   = {layers['L2_main_x_gate']:.4f}")
    print(f"  层3 全条件联合                              = {layers['L3_all_conditions']:.4f}")
    print(f"  层3' 保护集 1 级也接受                      = {layers['L3_prime_protection_1']:.4f}")
    print("\n  假设成分（非模拟）: 门禁 0.90, Q1 三族 0.85^3, S5 0.503, "
          "质量门禁 0.95, 保护集 0.85/0.95")

    checked, mism = crosscheck_scipy()
    out["scipy_crosscheck"] = {"cases_compared": checked, "mismatches": mism}
    print(f"\n=== 实现交叉验证（无并列连续数据）===")
    print(f"  本实现 vs scipy exact: {checked} 例, 不一致 {mism} 例"
          f" -> {'PASS' if mism == 0 else 'FAIL'}")

    with open('POWER_SIM_V2_2_OUTPUT.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n输出已写入 POWER_SIM_V2_2_OUTPUT.json")


if __name__ == '__main__':
    main()
