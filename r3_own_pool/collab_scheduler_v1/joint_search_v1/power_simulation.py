"""Exact power simulation for the NET-BENEFIT primary endpoint.

Primary: one-sided exact McNemar (binomial on discordant pairs), alpha=0.05,
H1: Help > Harm, at (mechanism, fault30, B*=3000), D vs A, n=50 paired tasks.

Model: discordant count D ~ Binom(n, p_d); Help|D=d ~ Binom(d, q).
Reject when P(Binom(d, 0.5) >= k_obs) <= alpha  (one-sided exact).

Historical anchor (FROZEN200_RESULTS_CORRECTED.json, v1 scoring, fault30,
3 seeds x 200 tasks, single vs dynamic): help=71, harm=67 -> q_hat=0.514,
p_d_hat=0.230. The historical effect is nearly balanced; if that is the true
state, NO affordable n confirms superiority. Design decisions must therefore
be made per effect-size scenario, not from the anchor alone.

Zero model requests.  python3 -m ...power_simulation
"""
import json
import sys
from pathlib import Path

from scipy.stats import binom

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/POWER_SIMULATION.json'
ALPHA = 0.05


def mcnemar_one_sided_p(help_, harm):
    """Exact one-sided p for Help > Harm."""
    d = help_ + harm
    if d == 0:
        return 1.0
    return binom.sf(help_ - 1, d, 0.5)


def k_min(d):
    """Smallest observed help count that rejects at alpha (one-sided)."""
    if d == 0:
        return d + 1  # never reject
    k = d // 2 + 1
    while k <= d and mcnemar_one_sided_p(k, d - k) > ALPHA:
        k += 1
    return k


def power(n, p_d, q, alpha=ALPHA):
    """Exact power by complete enumeration over D."""
    total = 0.0
    for d in range(0, n + 1):
        pw_d = binom.pmf(d, n, p_d)
        if pw_d < 1e-12:
            continue
        km = k_min(d)
        if km > d:
            continue
        total += pw_d * binom.sf(km - 1, d, q)
    return total


def run():
    # --- verification of the exact test itself (known p-values) ---
    verify = [
        dict(help=15, harm=0, expect_p=0.000030517578125),
        dict(help=8, harm=4, expect_p=None),  # reported, not asserted
        dict(help=0, harm=15, expect_p=1.0),
    ]
    for v in verify:
        v['p'] = mcnemar_one_sided_p(v['help'], v['harm'])

    # --- historical anchor ---
    f = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_RESULTS_CORRECTED.json').read_text())
    r = f['results']
    seeds = {}
    pooled = dict(help=0, harm=0)
    for seed in (20260923, 20260924, 20260925):
        s, d = r[f'f30_s{seed}|single'], r[f'f30_s{seed}|dynamic']
        uids = set(s) & set(d)
        h = sum(1 for u in uids if s[u]['ok'] == 0 and d[u]['ok'] == 1)
        m = sum(1 for u in uids if s[u]['ok'] == 1 and d[u]['ok'] == 0)
        seeds[seed] = dict(help=h, harm=m, p=mcnemar_one_sided_p(h, m))
        pooled['help'] += h
        pooled['harm'] += m
    d_all = pooled['help'] + pooled['harm']
    anchor = dict(
        source='FROZEN200_RESULTS_CORRECTED.json f30 single-vs-dynamic, v1 scoring',
        per_seed=seeds, pooled=pooled,
        p_pooled=mcnemar_one_sided_p(pooled['help'], pooled['harm']),
        q_hat=pooled['help'] / d_all, p_d_hat=d_all / 600,
        caveat='historical anchor under v1 close() scoring and the frozen200 '
               'panel; the NET-BENEFIT panel, v2.1 contract, fault draws and '
               'budget metric all differ — anchor only, not a prediction')

    # --- power grid ---
    grid = []
    for q in (0.514, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9):
        for p_d in (0.15, 0.23, 0.30, 0.40):
            row = dict(q=q, p_d=p_d,
                       n50=round(power(50, p_d, q), 3),
                       n100=round(power(100, p_d, q), 3),
                       n200=round(power(200, p_d, q), 3),
                       n400=round(power(400, p_d, q), 3))
            grid.append(row)

    # --- required n for 80% power ---
    required = []
    for q in (0.6, 0.65, 0.7, 0.8, 0.9):
        for p_d in (0.15, 0.23, 0.30, 0.40):
            n = 50
            while n <= 5000 and power(n, p_d, q) < 0.80:
                n += 50
            required.append(dict(q=q, p_d=p_d,
                                 n_for_80pct=(n if n <= 5000 else None)))

    out = dict(
        role='Phase 0.4 pre-registered power simulation (zero model requests)',
        test='one-sided exact McNemar, alpha=0.05, H1: Help > Harm',
        verification=verify,
        historical_anchor=anchor,
        power_grid=grid,
        required_n_for_80pct=required,
        reading=dict(
            anchor_q='q_hat=0.514 with p_d=0.23: power at n=50 is '
                     f'{power(50, 0.23, 0.514):.3f} — at the historical effect '
                     'the planned n=50 CANNOT confirm D>A (and neither can '
                     'much larger n; the historical point estimate is a '
                     'near-balance, not a positive effect)',
            design_q='a true discordant-help share q>=0.7 with p_d>=0.23 '
                     'gives >=0.80 power only from n≈150-200; q>=0.8 reaches '
                     'it near n=50-100',
            decision='n=50 is powered as a PILOT for the historical effect '
                     'size; it is a CONFIRMATORY design only under effects '
                     'q>=~0.8. The confirmatory claim must therefore be '
                     'conditional: pre-registered as pilot-confirmatory with '
                     'explicit power caveat; no post-hoc task addition may be '
                     'counted as the same confirmatory test'))
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ('verification', 'historical_anchor')},
                     indent=1)[:900])
    print('power at anchor (n=50):', round(power(50, 0.23, 0.514), 3))
    for row in grid:
        if row['p_d'] == 0.23:
            print(' q=%.3f p_d=0.23  n50=%.2f n100=%.2f n200=%.2f' %
                  (row['q'], row['n50'], row['n100'], row['n200']))
    print('required n (80% power):',
          [(x['q'], x['p_d'], x['n_for_80pct']) for x in required
           if x['p_d'] == 0.23])


if __name__ == '__main__':
    run()
