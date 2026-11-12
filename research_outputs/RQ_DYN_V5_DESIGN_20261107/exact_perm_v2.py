#!/usr/bin/env python3
"""修订版精确符号翻转检验（v2 草案，供 48 对扩展批次预注册审议）。

相对冻结版 exact_perm.py 的变化（统计思想不变：平均秩、正秩和 W+、单侧）：
① 配对级检验改用子集和 DP 精确计算任意 m 的零分布（O(m·总秩)），
   取消 m≤16 全枚举上限；m≤16 时与冻结版逐位一致（自检）。
② 新增任务簇级符号翻转检验：同一 DAG 任务的全部配对差值整体翻转，
   尊重任务内重复相关性；W+ = Σ_g (M_g + s_g·A_g)，零分布由簇块
   {2A_g} 的子集和 DP 精确计算，粒度 2^-G。
③ 簇级检验在 G=m（每对自成一簇）时与配对级 DP 逐位一致（自检）。

前提与边界同冻结版：配对差值（簇级：簇块）关于 0 联合对称；不提供跨事件
泛化保证。本文件为预注册草案组件，未经操作者冻结不得用于确认性分析。
"""
import random
import sys
from collections import defaultdict
from itertools import product

sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
from exact_perm import exact_paired_perm, _avg_ranks  # noqa: E402  冻结版，仅自检用

ALPHA = 0.05


def _ranks_scaled(nz):
    """平均秩 ×2 转整数（平均秩是 0.5 的倍数）。"""
    return [int(round(r * 2)) for r in _avg_ranks(nz)]


def exact_p_dp(diffs):
    """配对级：任意 m 的精确符号翻转 p（单侧，P(W+ ≥ W_obs)）。"""
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
            nxt[s] += c
            nxt[s + r] += c
        counts = nxt
    total = 1 << m
    return sum(c for s, c in counts.items() if s >= W_obs) / total


def exact_p_cluster(diffs, clusters):
    """簇级：同一簇（=同一 DAG 任务）的差值整体翻转，精确 p（单侧）。

    diffs: 配对差值列表；clusters: 等长列表，同一任务的配对同标签。
    簇 g 正负秩和差 B_g = P_g − N_g（×2 整数秩尺度）。按簇符号展开
    W+ 后，条件 W(s) ≥ W_obs 化简为 subsum_B(S) ≥ B_total，故
    p = P({B_g} 子集和 ≥ ΣB_g)，由子集和 DP 精确计算，粒度 2^-G。
    """
    if len(diffs) != len(clusters):
        raise ValueError('diffs/clusters length mismatch')
    idx = [(d, c) for d, c in zip(diffs, clusters) if d != 0]
    if not idx:
        return 1.0
    ranks = _ranks_scaled([d for d, _ in idx])
    pos, neg = defaultdict(int), defaultdict(int)
    for r, (d, c) in zip(ranks, idx):
        (pos if d > 0 else neg)[c] += r
    B = [pos[c] - neg[c] for c in sorted(pos.keys() | neg.keys(), key=str)]
    total = sum(B)
    counts = {0: 1}
    for b in B:
        nxt = defaultdict(int)
        for s, c in counts.items():
            nxt[s] += c
            nxt[s + b] += c
        counts = nxt
    return sum(c for s, c in counts.items() if s >= total) / (1 << len(B))


def self_test():
    rng = random.Random(20261107)
    # ① 配对级 DP == 冻结版全枚举（含并列与零差），500 例
    for case in range(500):
        n = rng.randint(1, 12)
        diffs = [rng.choice([-3, -2, -1, 0, 0, 1, 2, 3]) for _ in range(n)]
        a, b = exact_p_dp(diffs), exact_paired_perm(diffs)['p_value']
        assert abs(a - b) < 1e-15, (case, diffs, a, b)
    print('pair-level DP == frozen enumeration: 500/500')
    # ② 簇级在每对自成一簇时 == 配对级 DP，500 例
    for case in range(500):
        n = rng.randint(1, 12)
        diffs = [rng.choice([-3, -2, -1, 0, 0, 1, 2, 3]) for _ in range(n)]
        a = exact_p_cluster(diffs, list(range(n)))
        b = exact_p_dp(diffs)
        assert abs(a - b) < 1e-15, (case, diffs, a, b)
    print('cluster(singletons) == pair-level DP: 500/500')
    # ③ 簇级在 G≤12 时 == 簇组合暴力枚举，300 例
    for case in range(300):
        G = rng.randint(1, 6)
        k = rng.randint(1, 4)
        diffs, clusters = [], []
        for g in range(G):
            for _ in range(k):
                diffs.append(rng.choice([-3, -1, 0, 0, 1, 2, 3]))
                clusters.append(g)
        nzr = [(d, c) for d, c in zip(diffs, clusters) if d != 0]
        ranks = _ranks_scaled([d for d, _ in nzr])
        idx = [(d, c) for d, c in zip(diffs, clusters) if d != 0]
        W_obs = sum(r for r, (d, c) in zip(ranks, idx) if d > 0)
        glabels = sorted(set(c for _, c in idx))
        extreme = 0
        for signs in product((1, -1), repeat=len(glabels)):
            sg = dict(zip(glabels, signs))
            W = sum(r for r, (d, c) in zip(ranks, idx)
                    if (d > 0) == (sg[c] > 0))
            extreme += W >= W_obs - 1e-12
        p_brute = extreme / (1 << len(glabels))
        assert abs(exact_p_cluster(diffs, clusters) - p_brute) < 1e-15, (case,)
    print('cluster DP == cluster brute force: 300/300')
    # ④ 历史 16 对复现
    hist = [0, 0, 1, 1, 10, 13, -2, 11, 0, 9, 0, 0, 0, 0, 0, -1]
    p16 = exact_p_dp(hist)
    cl16 = ['S3'] * 8 + ['S4'] * 8
    pc16 = exact_p_cluster(hist, cl16)
    assert abs(p16 - 0.0546875) < 1e-15, p16
    print(f'observed 16 pairs: pair-level p={p16:.7f} (== archived 0.0546875); '
          f'cluster(S3,S4) p={pc16:.6f} (4 flips, floor 0.25)')


if __name__ == '__main__':
    self_test()
