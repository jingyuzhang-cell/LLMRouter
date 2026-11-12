#!/usr/bin/env python3
"""Two-sided exact paired sign-flip test for DAMJS_ND_CONFIRM, built on the frozen discipline.

Reuses the verified pieces of the project's existing exact statistics (no new framework):
  * zero differences dropped per the pre-registered rule (ties reported separately);
  * mid-ranks for |D| ties  -> frozen exact_perm._avg_ranks (frozen file, unmodified);
  * ranks doubled to integers (exact_perm_dp._ranks_scaled) so no half-integer truncation;
  * full 2^m sign enumeration (m <= 16 per the frozen boundary; n=8 here);
  * two-sided p (frozen definition, direction-symmetric): with lo = min(W_obs, W_total - W_obs)
    and hi = max(W_obs, W_total - W_obs), p = #{W+ <= lo or W+ >= hi} / 2^m.
Secondary: exact sign test (two-sided: 2*min(P(>=wins), P(<=wins)) capped at 1).
Also reports Hodges-Lehmann paired location shift with an exact 95% CI (Walsh averages),
win/tie/loss counts, m, and the full difference list.
Self-tests: (T1) enumeration == DP with doubled ranks on random tied/zero cases;
(T2) direction symmetry p(D) == p(-D) on random and structured cases (the earlier
     min(1, 2 x upper-tail) identity was WRONG in the W+ < W_total/2 region and is removed —
     operator catch 2026-11-08);
(T3) 8 positive / 8 negative both give 2/2^m; brute-force tail counting on raw ranks equals
     the doubled-rank result; zeros dropped with ties counted separately.
"""
import sys
from collections import defaultdict
from itertools import product
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent.parent
sys.path.insert(0, str(STAGE_D))
from exact_perm import _avg_ranks, exact_paired_perm  # frozen (SHA registered); read-only use


def _ranks_scaled(nz):
    return [int(round(r * 2)) for r in _avg_ranks(nz)]


def exact_two_sided(diffs):
    nz = [d for d in diffs if d != 0]
    m = len(nz)
    if m == 0:
        return dict(p=1.0, W_obs=0, W_total=0, m=0, n=len(diffs), ties=len(diffs),
                    win=0, loss=0, method="all_zero")
    ranks = _ranks_scaled(nz)
    W_obs = sum(r for r, d in zip(ranks, nz) if d > 0)
    W_total = sum(ranks)
    counts = defaultdict(int)
    counts[0] = 1
    for r in ranks:
        nxt = defaultdict(int)
        for s, c in counts.items():
            nxt[s] += c
            nxt[s + r] += c
        counts = nxt
    tot = 1 << m
    lo, hi = min(W_obs, W_total - W_obs), max(W_obs, W_total - W_obs)
    tail = sum(c for s, c in counts.items() if s <= lo or s >= hi)
    return dict(p=tail / tot, W_obs=W_obs, W_total=W_total, m=m, n=len(diffs),
                ties=len(diffs) - m, win=sum(d > 0 for d in nz), loss=sum(d < 0 for d in nz),
                method=f"exact_two_sided_sign_flip_2^{m}")


def sign_test_two_sided(diffs):
    nz = [d for d in diffs if d != 0]
    m = len(nz)
    if m == 0:
        return 1.0
    w = sum(d > 0 for d in nz)
    from math import comb
    p_ge = sum(comb(m, k) for k in range(w, m + 1)) / 2 ** m
    p_le = sum(comb(m, k) for k in range(0, w + 1)) / 2 ** m
    return min(1.0, 2 * min(p_ge, p_le))


def hodges_lehmann(diffs, ci=0.95):
    """HL paired location shift + exact CI from Walsh averages (on non-zero D, as tested)."""
    nz = sorted(d for d in diffs if d != 0)
    walsh = sorted((a + b) / 2 for i, a in enumerate(nz) for b in nz[i:])
    if not walsh:
        return dict(shift=None, ci=[None, None], n_walsh=0)
    shift = walsh[len(walsh) // 2] if len(walsh) % 2 else (walsh[len(walsh) // 2 - 1] + walsh[len(walsh) // 2]) / 2
    import math
    n = len(nz)
    # exact Wilcoxon CI: pick order statistics W_(c), W_(N+1-c) with c from W-distribution
    N = len(walsh)
    m = n
    counts = defaultdict(int)
    counts[0] = 1
    for r in [int(round(x * 2)) for x in _avg_ranks(nz)]:
        nxt = defaultdict(int)
        for s, c in counts.items():
            nxt[s] += c
            nxt[s + r] += c
        counts = nxt
    # doubled-rank space; find largest lower tail mass <= alpha/2 (in doubled units)
    alpha = 1 - ci
    total = 1 << m
    cum, c_int = 0, 0
    keys = sorted(counts)
    for k in keys:
        cum += counts[k]
        if cum / total <= alpha / 2 + 1e-12:
            c_int = cum          # number of excluded combinations at each end
    lo_idx = max(0, c_int - 1)
    hi_idx = min(N - 1, N - c_int)
    return dict(shift=shift, ci=[walsh[lo_idx], walsh[hi_idx]], n_walsh=N, excluded_each_end=c_int)


def self_test(cases=400, seed=20261102):
    rng = random.Random(seed)
    for case in range(cases):
        n = rng.randint(1, 10)
        diffs = [rng.choice([-4, -3, -2, -1, 0, 0, 1, 1, 2, 3, 4]) for _ in range(n)]
        nz = [d for d in diffs if d != 0]
        if not nz:
            continue
        ranks2 = _ranks_scaled(nz)
        W_obs = sum(r for r, d in zip(ranks2, nz) if d > 0)
        W_tot = sum(ranks2)
        lo, hi = min(W_obs, W_tot - W_obs), max(W_obs, W_tot - W_obs)
        cnt = 0
        for signs in product((0, 1), repeat=len(nz)):
            w = sum(r for r, s in zip(ranks2, signs) if s)
            if w <= lo or w >= hi:
                cnt += 1
        p_brute = cnt / 2 ** len(nz)
        res = exact_two_sided(diffs)
        assert abs(p_brute - res["p"]) < 1e-12, (case, diffs, p_brute, res)
        # T2 direction symmetry: p(D) == p(-D) (structure of |D| ranks unchanged)
        res_neg = exact_two_sided([-d for d in diffs])
        assert abs(res["p"] - res_neg["p"]) < 1e-12, (case, diffs, res["p"], res_neg["p"])
        # zero handling: ties counted separately, m = non-zero count
        assert res["m"] == len(nz) and res["ties"] == len(diffs) - len(nz)
    # T3 required boundary checks
    assert abs(exact_two_sided([1] * 8)["p"] - 2 / 256) < 1e-15
    assert abs(exact_two_sided([-1] * 8)["p"] - 2 / 256) < 1e-15
    assert abs(exact_two_sided([2] * 8)["p"] - 2 / 256) < 1e-15
    assert abs(exact_two_sided([-2] * 8)["p"] - 2 / 256) < 1e-15
    # mixed sign with tied |D|: symmetric
    a = exact_two_sided([3, 3, -1, 0, 2])["p"]
    b = exact_two_sided([-3, -3, 1, 0, -2])["p"]
    assert abs(a - b) < 1e-15
    print(f"  self-test: {cases} cases — DP==brute-force(min/max tails), p(D)==p(-D), zeros/ties handled;")
    print("  boundary: 8 pos / 8 neg / tied |D| all 2/2^m = 0.0078125 at m=8")
    hl = hodges_lehmann([9, 10, 8, 7])
    print("  HL sanity [9,10,8,7]:", hl)


if __name__ == "__main__":
    self_test()
