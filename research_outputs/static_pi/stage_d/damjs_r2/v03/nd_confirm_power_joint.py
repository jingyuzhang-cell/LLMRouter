#!/usr/bin/env python3
"""Joint-difference power analysis for DAMJS_ND_CONFIRM (operator-revised basis, 2026-11-07).

Simulates the PAIRED difference D_i = TP_ND,i - TP_R2,i directly, not independent marginal
ranges. Models are mechanistic (shared fixture quality + protection loss + downstream noise),
anchored on observed data, with integer TP (|D| ties emerge naturally) and zero-difference
strata. Uses the frozen exact two-sided test (nd_confirm_stats.exact_two_sided) — the same
function that will analyze the real data. >=20,000 sims x three fixed seeds per cell.
"""
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from nd_confirm_stats import exact_two_sided

SEEDS = (20261107, 20261108, 20261109)
NSIM = 20000


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def draw(rng, model):
    """One paired difference. Mechanistic: shared v1-world base S, protection loss L, noise."""
    if model == "independent":            # old (invalid) basis, kept for contrast only
        r2 = rng.choice([3, 5, 7, 8])
        nd = rng.choice([11, 12, 13, 14])
        return nd - r2
    S = rng.choice([8, 9, 10, 11, 12, 13, 14])       # v1-world downstream quality (shared fixture)
    if model == "correlated":
        L = rng.choice([5, 6, 7, 8, 9, 10])          # protection loss (r1b=9, r2=5, replay 6-10)
    elif model == "pessimistic":
        L = rng.choice([0, 1, 2]) if rng.random() < 0.30 else rng.choice([4, 5, 6, 7, 8])
    elif model == "hostile":
        L = rng.choice([0, 1, 2]) if rng.random() < 0.50 else rng.choice([3, 4, 5, 6])
    e_nd = rng.choice([-1, 0, 0, 1])
    e_r2 = rng.choice([-2, -1, 0, 1, 2])
    return clip(S + e_nd, 0, 23) - clip(S - L + e_r2, 0, 23)


def power(model, n, seed, nsim=NSIM):
    rng = random.Random(seed)
    hit = 0
    ties = 0
    for _ in range(nsim):
        D = [draw(rng, model) for _ in range(n)]
        ties += sum(d == 0 for d in D)
        if exact_two_sided(D)["p"] <= 0.05:
            hit += 1
    return hit / nsim, ties / (nsim * n)


def main():
    print(f"{'model':<14}{'n':>3} | " + "".join(f"seed {s}  " for s in SEEDS) + "| mean  E[tie]")
    for model in ("correlated", "pessimistic", "hostile", "independent"):
        for n in (8,):
            ps, ts = [], []
            for s in SEEDS:
                p, t = power(model, n, s)
                ps.append(p)
                ts.append(t)
            mean = sum(ps) / len(ps)
            print(f"{model:<14}{n:>3} | " + "".join(f"{p:6.3f}  " for p in ps) + f"| {mean:.3f}  {sum(ts)/3:.3f}")
    # n sensitivity on the two honest models
    print()
    for model in ("pessimistic", "hostile"):
        for n in (8, 10, 12):
            p, t = power(model, n, SEEDS[0])
            print(f"{model:<12} n={n}: power={p:.3f} (seed {SEEDS[0]})")


if __name__ == "__main__":
    main()
