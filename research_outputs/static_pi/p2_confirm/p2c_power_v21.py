#!/usr/bin/env python3
"""P2-C power V2.1 — zero model calls.

Part A: paired t-test (scenario reference, same formula as V2) — labelled as such, NOT the P2-C test.
Part B: the P2-C preregistered test (P2_STATISTICAL_PLAN §4 / P2_PROTOCOL_V1.1 §5):
        task-level paired exact sign-flip permutation test, n>20 -> 1e5 Monte Carlo sign flips;
        H2 one-sided; Holm family H1-H5 (H2 reported at alpha=0.05 and at the Holm first-step 0.01 bound);
        interaction q two-sided permutation, alpha=0.05.
Simulation: task-level differences ~ Normal(delta, sigma) (V2 scenarios) and a heavy-tail
sensitivity t(3) rescaled to the same SD. Fixed seed; one shared sign-flip matrix per n.
"""
import json, math, sys
import numpy as np
from scipy import stats as sps

SEED, B, R, N_TASKS = 20261108, 100_000, 10_000, 26
SCEN = {'保守': (0.08, 0.22), '中性': (0.10, 0.20), '乐观': (0.12, 0.18)}

def t_power(d, s, n, a=0.05, sided='one'):
    df = n - 1; tc = sps.t.ppf(1 - a if sided == 'one' else 1 - a / 2, df)
    ncp = d / (s / math.sqrt(n))
    return sps.nct.sf(tc, df, ncp) + (sps.nct.cdf(-tc, df, ncp) if sided == 'two' else 0.0)

def draws(rng, kind, mu, sd, n, r):
    if kind == 'normal':
        return rng.normal(mu, sd, size=(n, r))
    z = rng.standard_t(3, size=(n, r)) / math.sqrt(3.0)   # t(3) has var 3 -> unit SD
    return mu + sd * z

def perm_pvals(S, D, two_sided):
    obs = D.sum(axis=0)
    out = np.empty(D.shape[1])
    for i in range(0, D.shape[1], 200):
        M = S @ D[:, i:i + 200]
        o = obs[i:i + 200]
        if two_sided:
            cnt = (np.abs(M) >= np.abs(o) - 1e-12).sum(axis=0)
        else:
            cnt = (M >= o - 1e-12).sum(axis=0)
        out[i:i + 200] = (1 + cnt) / (B + 1)
    return out

def main():
    rng = np.random.default_rng(SEED)
    S = rng.choice(np.array([-1.0, 1.0]), size=(B, N_TASKS))
    res = dict(seed=SEED, B=B, R=R, n=N_TASKS, partA_paired_t={}, partB_permutation={})
    for n in (24, 25, 26, 27):
        res['partA_paired_t'][n] = {k: dict(alpha05=round(t_power(d, s, n), 4), holm_first_alpha01=round(t_power(d, s, n, 0.01), 4),
                                            interaction_two_sided=round(t_power(0.05, s * 1.2, n, 0.05, 'two'), 4))
                                    for k, (d, s) in SCEN.items()}
    for kind in ('normal', 't3'):
        for k, (d, s) in SCEN.items():
            D = draws(rng, kind, d, s, N_TASKS, R)
            p = perm_pvals(S, D, two_sided=False)
            ttest = sps.ttest_1samp(D, 0.0, axis=0, alternative='greater').pvalue
            Q = draws(rng, kind, 0.05, s * 1.2, N_TASKS, R)
            pq = perm_pvals(S, Q, two_sided=True)
            res['partB_permutation'][f'{kind}/{k}'] = dict(
                H2_alpha05=round(float((p <= 0.05).mean()), 4),
                H2_holm_first_alpha01=round(float((p <= 0.01).mean()), 4),
                interaction_two_sided_alpha05=round(float((pq <= 0.05).mean()), 4),
                same_data_paired_t_alpha05=round(float((ttest <= 0.05).mean()), 4),
                mc_se=round(math.sqrt(0.25 / R), 4))
    print(json.dumps(res, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    sys.exit(main())
