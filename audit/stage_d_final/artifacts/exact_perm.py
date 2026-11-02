#!/usr/bin/env python3
"""离散 TP 配对差值的精确符号翻转置换检验（操作者终审核心修订项）。

与 scipy.wilcoxon(method='exact') 的区别：
  scipy 在出现 ties/zeros 时不保证精确 p（官方文档明示）；本实现：
  ① 零差值按预登记规则剔除（m = 非零对数）
  ② 非零差值的 |D| 计算平均秩（并列取平均）
  ③ 枚举全部 2^m 种正负号翻转
  ④ 统计量 = 正号组的秩和 W+
  ⑤ 单侧精确 p = P(W+ ≥ W_obs | H0)（枚举分布中 ≥ 观测值的比例）

H0: 配对差值关于 0 对称；备择: Proposed > Simple（W+ 偏大）。
**对称性是符号翻转精确性的前提（仅有配对间独立并不充分）**；配对间独立由
设计（同源配对 + 分块随机化）保证，两者不同。本函数不检验对称性；若数据
强烈偏离对称性，主检验结论降级为方向性并如实报告。
预登记最大配对数为 16（m ≤ 16，2^16 = 65536 全枚举可承受）；m > 16 拒绝
计算（确认性分析不做近似）。正式分析与功效模拟共用 exact_paired_perm()。
"""
import random
from itertools import product
from typing import List

import numpy as np

ALPHA = 0.05
MAX_M = 16  # 预登记主检验 m ≤ 16（操作者终审：代码必须严格执行预注册边界）

_SIGN_CACHE = {}


def _avg_ranks(nz: List[float]) -> List[float]:
    """|D| 的平均秩（并列取平均），保持与 nz 同序。"""
    abss = sorted(abs(d) for d in nz)
    ranks = []
    for d in nz:
        v = abs(d)
        lo = sum(1 for x in abss if x < v)
        eq = sum(1 for x in abss if x == v)
        ranks.append(lo + (eq + 1) / 2)
    return ranks


def _sign_matrix(m: int) -> np.ndarray:
    """2^m × m 的 0/1 符号矩阵（缓存）；行=一种正负号组合。"""
    if m not in _SIGN_CACHE:
        if m > MAX_M:
            raise ValueError(f'm={m} exceeds pre-registered MAX_M={MAX_M}; '
                             'confirmatory analysis does not approximate')
        masks = np.arange(1 << m, dtype=np.int64)
        S = np.empty((1 << m, m), dtype=np.float64)
        for i in range(m):
            S[:, i] = (masks >> i) & 1
        _SIGN_CACHE[m] = S
    return _SIGN_CACHE[m]


def _pure_enum(ranks: List[float], signs_iter) -> List[float]:
    """暴力枚举（仅供一致性自检，不用于大规模仿真）。"""
    return [sum(r for r, s in zip(ranks, signs) if s > 0)
            for signs in signs_iter]


def exact_paired_perm(diffs: List[float], alpha: float = ALPHA) -> dict:
    """离散配对差值的精确符号翻转置换检验。

    Returns dict with keys: p_value, W_obs, m, significant, method,
    n_enumerated
    """
    nz = [d for d in diffs if d != 0]
    m = len(nz)
    if m == 0:
        return {"p_value": 1.0, "W_obs": 0.0, "m": 0, "significant": False,
                "method": "all_zero", "n_enumerated": 1}

    ranks = _avg_ranks(nz)
    W_obs = float(sum(r for r, d in zip(ranks, nz) if d > 0))

    S = _sign_matrix(m)
    W_dist = S @ np.asarray(ranks, dtype=np.float64)
    p = float(np.count_nonzero(W_dist >= W_obs - 1e-12)) / len(W_dist)

    return {"p_value": p, "W_obs": W_obs, "m": m,
            "significant": p < alpha, "method": f"exact_sign_flip_2^{m}",
            "n_enumerated": int(len(W_dist))}


def _self_test(n_cases: int = 300, seed: int = 20261102) -> None:
    """向量化枚举 vs 暴力枚举逐例必须完全相等（含并列/零差）。"""
    rng = random.Random(seed)
    for case in range(n_cases):
        n = rng.randint(1, 12)
        diffs = [rng.choice([-3, -2, -1, 0, 0, 1, 2, 3]) for _ in range(n)]
        nz = [d for d in diffs if d != 0]
        if not nz:
            continue
        ranks = _avg_ranks(nz)
        W_obs = sum(r for r, d in zip(ranks, nz) if d > 0)
        pure = _pure_enum(ranks, product((1, -1), repeat=len(nz)))
        p_pure = sum(1 for w in pure if w >= W_obs - 1e-12) / len(pure)
        p_vec = exact_paired_perm(diffs)["p_value"]
        assert abs(p_pure - p_vec) < 1e-12, \
            f'case {case}: pure={p_pure} vec={p_vec} diffs={diffs}'
    print(f'  self-test: {n_cases} random cases, vectorized == brute-force '
          f'enumeration (exact)')


def simulate_power(n: int, p_tie: float, mu: float, sd: float,
                   nsim: int = 20000, seed: int = 20261102,
                   integerize: bool = True) -> float:
    """功效模拟：与正式分析同一 exact_paired_perm()。

    D = 0 w.p. p_tie；否则 N(mu, sd)。integerize=True 时取整（TP 差值必为
    整数；取整产生的额外 0 差值按预登记规则剔除，属实际数据特征）。
    """
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
        if exact_paired_perm(diffs)["significant"]:
            sig += 1
    return sig / nsim


if __name__ == '__main__':
    print('=== exact_perm self-test ===')
    print('  S3 [2,1,0,2,0]:', exact_paired_perm([2, 1, 0, 2, 0]))
    print('  S4 [7,4,5,7,5]:', exact_paired_perm([7, 4, 5, 7, 5]))
    print('  stress 8x+1   :', exact_paired_perm([1] * 8)['p_value'])
    print('  stress +-     :', exact_paired_perm([1, -1] * 4)['p_value'])
    print('  stress zero   :', exact_paired_perm([0] * 8)['p_value'])
    _self_test()
    print('\n=== 小样本功效演示 (nsim=1000; 终版数字见 power_sim.py) ===')
    for label, (pt, mu, sd) in [('基准保守', (0.25, 1.0, 1.2)),
                                 ('更保守', (0.30, 0.8, 1.3)),
                                 ('乐观', (0.20, 2.0, 1.5))]:
        print(f'  {label}: 整数 {simulate_power(16, pt, mu, sd, 1000):.3f} | '
              f'连续 {simulate_power(16, pt, mu, sd, 1000, integerize=False):.3f}')
    print('  S3 单族 8 对（整数）:',
          f'{simulate_power(8, 0.35, 1.0, 1.2, 1000):.3f}')
