#!/usr/bin/env python3
"""L2 联合模拟的四类事件计数核验（操作者要求：证明 P(Main∩Gate) 来自同一轮模拟）。

单次循环内同时生成 S3/S4 各 8 对差值 → 同一次 exact_paired_perm(16 对) 判主检验
→ 同一批数据判族门禁 → 四个互斥/包含事件同时累加：
  P(Main)             主检验显著
  P(Gate)             两族中位差均 ≥ 0
  P(Main ∩ Gate)      两者同时
  P(Main ∩ ¬Gate)     主检验过但门禁败
一致性恒等式：P(Main) = P(Main∩Gate) + P(Main∩¬Gate)
"""
import random
import statistics
import sys

from exact_perm import exact_paired_perm

NSIM = 20000
SEEDS = [20261102, 42, 12345]


def run(seed, p_zero=0.25, mu=1.0, sd=1.2, n_per_family=8):
    rng = random.Random(seed)
    n_main = n_gate = n_joint = n_main_not_gate = 0
    for _ in range(NSIM):
        d3 = [0 if rng.random() < p_zero else int(round(rng.gauss(mu, sd)))
              for _ in range(n_per_family)]
        d4 = [0 if rng.random() < p_zero else int(round(rng.gauss(mu, sd)))
              for _ in range(n_per_family)]
        main = exact_paired_perm(d3 + d4)["significant"]   # 同一批 16 对
        gate = statistics.median(d3) >= 0 and statistics.median(d4) >= 0
        n_main += main
        n_gate += gate
        n_joint += (main and gate)
        n_main_not_gate += (main and not gate)
    return {
        "seed": seed,
        "P_Main": n_main / NSIM,
        "P_Gate": n_gate / NSIM,
        "P_Main_and_Gate": n_joint / NSIM,
        "P_Main_and_not_Gate": n_main_not_gate / NSIM,
        "identity_check": abs(n_main / NSIM - (n_joint + n_main_not_gate) / NSIM) < 1e-12,
        "counts": {"main": n_main, "gate": n_gate, "joint": n_joint,
                   "main_not_gate": n_main_not_gate, "nsim": NSIM},
    }


if __name__ == "__main__":
    rows = [run(s) for s in SEEDS]
    print(f"=== L2 联合模拟四类计数（nsim={NSIM}/种子，同一循环内）===")
    print(f"{'seed':>9s} {'P(Main)':>9s} {'P(Gate)':>9s} {'P(M∩G)':>9s} {'P(M∩¬G)':>9s} {'恒等式':>6s}")
    for r in rows:
        print(f"{r['seed']:>9d} {r['P_Main']:9.4f} {r['P_Gate']:9.4f} "
              f"{r['P_Main_and_Gate']:9.4f} {r['P_Main_and_not_Gate']:9.4f} "
              f"{'OK' if r['identity_check'] else 'FAIL':>6s}")
    mean = lambda k: sum(r[k] for r in rows) / len(rows)
    print(f"{'均值':>9s} {mean('P_Main'):9.4f} {mean('P_Gate'):9.4f} "
          f"{mean('P_Main_and_Gate'):9.4f} {mean('P_Main_and_not_Gate'):9.4f}")
    print(f"\n计数明细: {[r['counts'] for r in rows]}")
    import json
    json.dump({"nsim": NSIM, "seeds": SEEDS, "rows": rows,
               "means": {k: mean(k) for k in ("P_Main", "P_Gate", "P_Main_and_Gate", "P_Main_and_not_Gate")}},
              open("L2_JOINT_COUNTS.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("写入 L2_JOINT_COUNTS.json")
