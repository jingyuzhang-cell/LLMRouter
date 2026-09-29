"""Dual-session sensitivity audit for cube_clean (zero model calls).

The cube ledger contains an earlier partial session plus the final run; 108
cross-session duplicate (model, prompt) executions, 20 with divergent temp-0
answers (server-session nondeterminism). This audit recomputes the full
15-config cube under three resolution policies:

  as_published  by_key last + prompt first  (replicates the runner; 15/15
                agreement verified in CUBE_CLEAN_ANALYSIS.json)
  all_early     both first                 (earlier session wins everywhere)
  all_late      both last                  (final-run session wins everywhere)

and reports per-config Q/C/L spread, P*_clean stability, and the stability of
the Y ranking (SER vs SERV vs PARALLELER/DYNAMICDAG) and X ranking
(HETEROGENEOUS vs QUALITY vs BALANCED). If the front and the coarse rankings
survive, the dual-session issue is downgraded to a reproducibility note.

Run: python3 -m collab_scheduler_v1.session_sensitivity_audit
"""
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/SESSION_SENSITIVITY_AUDIT.json'

POLICIES = {
    'as_published': dict(by_policy='last', prompt_policy='first'),
    'all_early': dict(by_policy='first', prompt_policy='first'),
    'all_late': dict(by_policy='last', prompt_policy='last'),
}


def rankings(results):
    """Mean Q by Y group and by X family (NONE configs only, dedup labels)."""
    y, x = {}, {}
    for cid, r in results.items():
        if not cid.endswith('__NONE__FRESH'):
            continue
        topo, fam, _, _ = cid.split('__')
        y.setdefault(topo, []).append(r['Q'])
        x.setdefault(fam, []).append(r['Q'])
    ym = {k: round(sum(v) / len(v), 4) for k, v in y.items()}
    xm = {k: round(sum(v) / len(v), 4) for k, v in x.items()}
    return ym, xm


def order_stable(m1, m2, tol=0.01):
    for a, b in combinations(m1, 2):
        d1 = m1[a] - m1[b]
        d2 = m2[a] - m2[b]
        if d1 > tol and d2 < -tol:
            return False
        if d1 < -tol and d2 > tol:
            return False
    return True


def run():
    from collab_scheduler_v1 import cube_analyze
    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
                       .read_text())['tasks']
    out = dict(policies={}, comparison={})
    for name, kw in POLICIES.items():
        led = cube_analyze.load_ledgers(**kw)
        res = cube_analyze.evaluate(tasks, led=led)
        summary = {cid: dict(Q=v['Q'], C=v['C'], L=v['L'])
                   for cid, v in res.items() if v['n'] == v['n_total']}
        ym, xm = rankings(res)
        out['policies'][name] = dict(configs=summary, Y_mean_Q=ym, X_mean_Q=xm)
        print(f'{name}: {len(summary)}/15 complete  Y={ym}  X={xm}')

    base = out['policies']['as_published']['configs']
    spread = {}
    for cid in base:
        qs = [out['policies'][p]['configs'][cid]['Q'] for p in POLICIES
              if cid in out['policies'][p]['configs']]
        spread[cid] = dict(Q_min=min(qs), Q_max=max(qs), Q_range=round(max(qs) - min(qs), 4))
    fronts = {}
    for p in POLICIES:
        pts = {cid: (v['Q'], v['C'], v['L'])
               for cid, v in out['policies'][p]['configs'].items()}
        pts['SINGLE__QUALITY__RETRY__FRESH'] = (0.55, 612.8, 0.46)
        Cmax = max(v[1] for v in pts.values())
        Lmax = max(v[2] for v in pts.values())
        objs = {cid: (q, 1 - c / Cmax, 1 - l / Lmax)
                for cid, (q, c, l) in pts.items()}
        front = [cid for cid in objs if not any(
            all(x >= y for x, y in zip(objs[d], objs[cid]))
            and any(x > y for x, y in zip(objs[d], objs[cid]))
            for d in objs if d != cid)]
        fronts[p] = sorted(front)

    y_stable = all(order_stable(out['policies']['as_published']['Y_mean_Q'],
                                out['policies'][p]['Y_mean_Q'])
                   for p in POLICIES)
    x_stable = all(order_stable(out['policies']['as_published']['X_mean_Q'],
                                out['policies'][p]['X_mean_Q'])
                   for p in POLICIES)
    out['comparison'] = dict(
        per_config_Q_spread=spread,
        max_Q_range=max(s['Q_range'] for s in spread.values()),
        fronts_by_policy=fronts,
        front_stable=len({tuple(f) for f in fronts.values()}) == 1,
        Y_rank_stable_tol_0_01=y_stable,
        X_rank_stable_tol_0_01=x_stable,
        single_dominates_all_policies=all(
            'SINGLE__QUALITY__RETRY__FRESH' in f and len(f) == 1 for f in fronts.values()))
    verdict = 'DOWNGRADE to reproducibility note' if (
        out['comparison']['front_stable'] and y_stable and x_stable) else \
        'MATERIAL — session noise moves rankings; consider targeted re-execution'
    out['verdict'] = verdict
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out['comparison'].items()
                      if k != 'per_config_Q_spread'}, indent=1))
    print('VERDICT:', verdict)


if __name__ == '__main__':
    run()
