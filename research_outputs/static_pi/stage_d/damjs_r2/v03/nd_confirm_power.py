#!/usr/bin/env python3
"""Power analysis for DAMJS_ND_CONFIRM (reproducible; seed 20261107).
Primary test: two-sided exact Wilcoxon signed-rank on paired dTP(strict-normalized+canonicalized).
Sign test shown for comparison. Component models from observed data (see prereg section 2)."""
import random
from math import comb


def wilcoxon_exact_p(diffs):
    nz = [d for d in diffs if d != 0]
    m = len(nz)
    if m == 0:
        return 1.0
    srt = sorted((abs(d), d > 0) for d in nz)
    ranks, i = {}, 0
    while i < m:
        j = i
        while j < m and srt[j][0] == srt[i][0]:
            j += 1
        for k in range(i, j):
            ranks[k] = (i + 1 + j) / 2
        i = j
    Wp = sum(ranks[k] for k in range(m) if srt[k][1])
    tot = sum(ranks.values())
    cnt = 0
    for bits in range(2 ** m):
        w = sum(ranks[k] for k in range(m) if bits >> k & 1)
        if w >= Wp - 1e-9 or w <= tot - Wp + 1e-9:
            cnt += 1
    return min(1.0, cnt / 2 ** m)


def sign_p(k, n):
    return min(1.0, 2 * sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n)


MODELS = {
    "observed": ([3, 5, 7, 8], [11, 12, 13, 14]),
    "conservative_overlap": ([4, 6, 8, 10], [9, 11, 13, 14]),
}


def main():
    rng = random.Random(20261107)
    print("Wilcoxon exact two-sided power (3000 sims/cell)")
    for name, (r2, nd) in MODELS.items():
        for n in (6, 8, 10, 12):
            hit = sum(1 for _ in range(3000) if wilcoxon_exact_p([rng.choice(nd) - rng.choice(r2) for _ in range(n)]) <= 0.05)
            print(f"  {name:<22} n={n}: {hit / 3000:.3f}")
    print("two-sided exact sign test power (win-rate q, tie t)")
    def sign_power(n, q, t):
        pw = 0.0
        for m in range(n + 1):
            pm = comb(n, m) * t ** (n - m) * (1 - t) ** m
            k_min = next((k for k in range(m, -1, -1) if sign_p(k, m) <= 0.05001), None)
            if k_min is None:
                continue
            pw += pm * sum(comb(m, w) * q ** w * (1 - q) ** (m - w) for w in range(k_min, m + 1))
        return pw
    for q in (0.85, 0.95):
        for n in (6, 8, 12):
            print(f"  q={q} t=0.05 n={n}: {sign_power(n, q, 0.05):.3f}")
    print("feasibility: J1 first-call walls n=187: P(<=88s)=0.818 (240s design), P(<=148s)=1.000 (300s design, max 116.4)")


if __name__ == "__main__":
    main()
