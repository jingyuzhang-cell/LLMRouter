#!/usr/bin/env python3
"""终局功效模拟 V2.3（操作者终审三项修正版）。

V2.2 的缺陷（操作者终审 FAIL）：
  1. 实际运行 nsim=3000（非默认 20000），正式报告需统一规模；
  2. 整数化后的实际胜/平/负比例未呈现；p_tie 命名与最终观测平局率混淆；
  3. 联合功效把主检验与族门禁用"独立相乘"处理（同一批数据，独立性未证明）；
     Q1 的 0.85 定义不明（单次 vs 族通过）；S5 已降级却仍乘入确认性联合。

V2.3 修订：
  - NSIM=20000 固定；所有场景 3 种子（20261102 / 42 / 12345）；
  - 报告整数化后的观测胜/平/负比例；
  - p_tie → p_structural_zero（生成模型中强制置零的概率；纯连续模型下=平局率，
    整数化后实际平局率更高并单独报告）；
  - L1 = 主检验模拟功效；**L2 = 联合模拟**（同一批模拟数据上同时检验主检验与
    族非伤害门禁，非独立相乘）；
  - L3 = 情景化联合通过概率（在外部假设成分下），**明确标注非验证性功效**；
  - **S5 移出确认性联合**，独立报告方向性。
"""
import json
import sys
from math import comb

from exact_perm import exact_paired_perm, simulate_power

NSIM = 20000
SEEDS = [20261102, 42, 12345]
SCENARIOS = [
    # (label, p_structural_zero, mu, sd)
    ("基准保守", 0.25, 1.0, 1.2),
    ("更保守", 0.30, 0.8, 1.3),
    ("乐观(接近D2实测)", 0.20, 2.0, 1.5),
]


def simulate_scenario_full(n_pairs, p_zero, mu, sd, nsim, seed):
    """单场景模拟：返回 (功效, 有效n均值, 胜/平/负 观测比例)。"""
    import random
    rng = random.Random(seed)
    sig = 0
    wins = ties = losses = 0
    for _ in range(nsim):
        diffs = []
        for _ in range(n_pairs):
            if rng.random() < p_zero:
                diffs.append(0)
            else:
                diffs.append(int(round(rng.gauss(mu, sd))))
        wins += sum(1 for d in diffs if d > 0)
        ties += sum(1 for d in diffs if d == 0)
        losses += sum(1 for d in diffs if d < 0)
        if exact_paired_perm(diffs)["significant"]:
            sig += 1
    total = nsim * n_pairs
    return {"power": sig / nsim,
            "observed_win": wins / total,
            "observed_tie": ties / total,
            "observed_loss": losses / total}


def simulate_joint_l2(p_zero, mu, sd, nsim, seed, n_per_family=8):
    """L2 联合模拟：同一批数据上同时要求（主检验显著）且（两族中位差均 ≥0）。

    族非伤害门禁定义（预登记）：任一族的中位配对差 < 0 → 主检验判负。
    """
    import random, statistics
    rng = random.Random(seed)
    joint = 0
    main_only = 0
    gate_pass = 0
    for _ in range(nsim):
        d3 = [0 if rng.random() < p_zero else int(round(rng.gauss(mu, sd)))
              for _ in range(n_per_family)]
        d4 = [0 if rng.random() < p_zero else int(round(rng.gauss(mu, sd)))
              for _ in range(n_per_family)]
        main_sig = exact_paired_perm(d3 + d4)["significant"]
        gate_ok = statistics.median(d3) >= 0 and statistics.median(d4) >= 0
        main_only += main_sig
        gate_pass += gate_ok
        joint += (main_sig and gate_ok)
    return {"L2_joint": joint / nsim,
            "main_sig_rate": main_only / nsim,
            "gate_pass_rate": gate_pass / nsim}


def main():
    out = {"nsim": NSIM, "seeds": SEEDS,
           "implementation": "exact_perm.exact_paired_perm",
           "note": "p_structural_zero = 生成模型强制置零概率；整数化后实际平局率见 observed_tie"}
    print(f"=== 功效模拟 V2.3（nsim={NSIM}, 3 种子统一）===")
    print("生成模型: D=0 w.p. p_structural_zero; else N(mu,sd) → int(round)\n")

    for label, p_zero, mu, sd in SCENARIOS:
        rows = [simulate_scenario_full(16, p_zero, mu, sd, NSIM, s) for s in SEEDS]
        pw = [r["power"] for r in rows]
        mean_pw = sum(pw) / len(pw)
        out[label] = {
            "p_structural_zero": p_zero, "mu": mu, "sd": sd,
            "power_per_seed": pw, "power_mean": mean_pw,
            "observed_win": sum(r["observed_win"] for r in rows) / len(rows),
            "observed_tie": sum(r["observed_tie"] for r in rows) / len(rows),
            "observed_loss": sum(r["observed_loss"] for r in rows) / len(rows),
        }
        print(f"  {label} (p_structural_zero={p_zero}, mu={mu}, sd={sd}):")
        print(f"    主检验功效 {mean_pw:.4f}（{', '.join(f'{x:.4f}' for x in pw)}）")
        print(f"    观测胜/平/负 = {out[label]['observed_win']:.1%} / "
              f"{out[label]['observed_tie']:.1%} / {out[label]['observed_loss']:.1%}")

    # L2 联合模拟（基准场景，3 种子）
    print("\n=== L2 联合模拟（主检验 AND 族非伤害门禁；同一批数据）===")
    l2_rows = [simulate_joint_l2(0.25, 1.0, 1.2, NSIM, s) for s in SEEDS]
    l2_joint = sum(r["L2_joint"] for r in l2_rows) / len(l2_rows)
    l2_main = sum(r["main_sig_rate"] for r in l2_rows) / len(l2_rows)
    l2_gate = sum(r["gate_pass_rate"] for r in l2_rows) / len(l2_rows)
    out["L2_joint_simulated"] = {"joint": l2_joint, "main_only": l2_main,
                                 "gate_only": l2_gate, "per_seed": l2_rows}
    print(f"  主检验显著率 {l2_main:.4f} | 门禁通过率 {l2_gate:.4f} | "
          f"**联合通过 {l2_joint:.4f}**（非独立相乘）")

    # S3 单族
    print("\n=== S3 单族（8 对，整数化，3 种子）===")
    s3 = [simulate_scenario_full(8, 0.35, 1.0, 1.2, NSIM, s) for s in SEEDS]
    s3_mean = sum(r["power"] for r in s3) / len(s3)
    out["S3_single_family"] = {"power_mean": s3_mean, "per_seed": [r["power"] for r in s3]}
    print(f"  {s3_mean:.4f}（{', '.join(f'{r[chr(112)+chr(111)+chr(119)+chr(101)+chr(114)]:.4f}' for r in s3)}）")

    # S5（独立报告，不参与确认性联合）
    s5 = {wr: sum(comb(8, k) * wr ** k * (1 - wr) ** (8 - k) for k in (7, 8))
          for wr in (0.70, 0.80, 0.90)}
    out["S5_directional_only"] = s5
    print("\n=== S5（方向性证据，不参与确认性联合）===")
    for wr, p in s5.items():
        print(f"  真实胜率 {wr:.0%}: P(≥7/8) = {p:.4f}")

    # L3 情景化（明确标注非验证性）
    p_q1_family = sum(comb(8, k) * 0.85 ** k * 0.15 ** (8 - k) for k in (7, 8))
    p_qual, p_prot0 = 0.95, 0.85
    l3 = l2_joint * (p_q1_family ** 3) * p_qual * p_prot0
    out["L3_scenario_based"] = {
        "value": l3, "verified": False,
        "components": {"L2_joint_simulated": l2_joint,
                       "Q1_family_pass@0.85_single": p_q1_family,
                       "Q1_three_families": p_q1_family ** 3,
                       "quality_gate_assumed": p_qual,
                       "protection_zero_assumed": p_prot0},
        "label": "情景化联合通过概率（外部假设成分下），非验证性功效"}
    print("\n=== L3 情景化联合通过概率（非验证性）===")
    print(f"  L2 联合(模拟) {l2_joint:.4f} × Q1三族 {p_q1_family**3:.4f} "
          f"(单族@0.85单次正确率={p_q1_family:.4f}) × 质量门禁 {p_qual} × 保护集 {p_prot0}")
    print(f"  = {l3:.4f}  ← 标注为情景化，不作确认性功效宣称")

    with open("POWER_SIM_V2_3_OUTPUT.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n输出写入 POWER_SIM_V2_3_OUTPUT.json")


if __name__ == "__main__":
    main()
