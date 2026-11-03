#!/usr/bin/env python3
"""精确符号翻转检验的动态规划实现（候选，不改冻结 exact_perm.py）。

目的：当前 exact_perm.py 用 2^m 全枚举，m>16 不可行；但精确符号翻转分
布可由"子集和"DP 精确计算，复杂度 O(m × 秩和)，与 2^m 无关。
统计方法完全不变：零差剔除、平均秩、单侧 W+、全符号组合等概率。
"""
import math
import random
import sys
import time
from collections import defaultdict

sys.path.insert(0, ".")
from exact_perm import exact_paired_perm, _avg_ranks


def _ranks_scaled(nz):
    """平均秩 ×2 转整数（平均秩为 0.5 的倍数）。"""
    return [int(round(r * 2)) for r in _avg_ranks(nz)]


def exact_p_dp(diffs):
    nz = [d for d in diffs if d != 0]
    m = len(nz)
    if m == 0:
        return 1.0
    ranks = _ranks_scaled(nz)
    W_obs = sum(r for r, d in zip(ranks, nz) if d > 0)
    counts = {0: 1}
    for r in ranks:
        nxt = defaultdict(int)
        for s, c in counts.items():
            nxt[s] += c          # 符号为负
            nxt[s + r] += c      # 符号为正
        counts = nxt
    total = 1 << m
    ge = sum(c for s, c in counts.items() if s >= W_obs)
    return ge / total


def verify():
    from itertools import product
    # D2 反演
    s3 = exact_p_dp([2, 1, 0, 2, 0]); s4 = exact_p_dp([7, 4, 5, 7, 5])
    print("D2 inversion: S3", s3, "S4", s4)
    assert abs(s3 - 0.125) < 1e-15 and abs(s4 - 0.03125) < 1e-15
    # 随机 m<=12 与枚举逐例一致
    rng = random.Random(20261102)
    for case in range(500):
        n = rng.randint(1, 12)
        diffs = [rng.choice([-3, -2, -1, 0, 0, 1, 2, 3]) for _ in range(n)]
        a = exact_p_dp(diffs); b = exact_paired_perm(diffs)["p_value"]
        assert abs(a - b) < 1e-15, (case, diffs, a, b)
    print("random m<=12: DP == enumeration (500 cases)")
    # m=24/32 计时
    for m in (16, 24, 32, 64):
        diffs = [rng.choice([-3, -2, -1, 0, 1, 2, 3]) for _ in range(m)]
        t0 = time.time(); p = exact_p_dp(diffs); dt = time.time() - t0
        print(f"m={m}: p={p:.6f} time={dt*1000:.2f} ms")


def simulate_power_dp(n, p_tie, mu, sd, nsim=2000, seed=20261102, integerize=True):
    rng = random.Random(seed)
    sig = 0
    for _ in range(nsim):
        diffs = []
        for _ in range(n):
            if rng.random() < p_tie:
                diffs.append(0)
            else:
                d = rng.gauss(mu, sd)
                diffs.append(int(round(d)) if integerize else d)
        if exact_p_dp(diffs) < 0.05:
            sig += 1
    return sig / nsim


if __name__ == "__main__":
    verify()
    print("\nprojected power (DP exact, conservative prior p_tie=0.30 mu=0.8 sd=1.3):")
    for n in (16, 24, 32):
        t0 = time.time(); p = simulate_power_dp(n, 0.30, 0.8, 1.3, 2000); dt = time.time() - t0
        print(f"n={n}: power≈{p:.4f} (nsim=2000, {dt:.1f}s)")
