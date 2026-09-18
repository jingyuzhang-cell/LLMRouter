"""Complete budget-quality-time curves over the frozen 740 action results (zero new calls).
Universe: 116 nodes whose ORIGINAL final answer was verifiably wrong (clean success criterion).
Adds to the earlier sequential simulation: token-budget grid, full strategy sweep, Pareto
frontier (Q vs delta-C vs delta-L), and lambda/mu utility sensitivity."""
import json
import random
from collections import defaultdict
from .recovery_matrix_v2_full_prep import OUT
from .recovery_matrix_v2_sequential import load, simulate, stats, bootstrap_ci, SEED, B

RECOVERY = ['retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose']
STRATS = {
    'retry_only': ['retry_same'],
    'switch_only': ['switch_model'],
    'retrieval_only': ['evidence_retrieval'],
    'decompose_only': ['local_decompose'],
    'retry_then_switch': ['retry_same', 'switch_model'],
    'switch_then_retry': ['switch_model', 'retry_same'],
    'retry_then_retrieval': ['retry_same', 'evidence_retrieval'],
    'retry_then_decompose': ['retry_same', 'local_decompose'],
    'retry_switch_then_retrieval': ['retry_same', 'switch_model', 'evidence_retrieval'],
    'retry_switch_then_decompose': ['retry_same', 'switch_model', 'local_decompose'],
    'retry_then_retrieval_decompose': ['retry_same', 'evidence_retrieval', 'local_decompose'],
    'all_four_in_order': RECOVERY,
    'oracle_upper': 'any',
}
T_GRID = [0.5, 1.0, 2.0, 5.0, None]
C_GRID = [300, 600, 1200, 2400, 4000, None]

def simulate_budget(nodes, chain, c_rem=None, t_rem=None):
    out = []
    for n in nodes:
        if chain == 'any':
            acts = [a for a in RECOVERY if n['succ'][a]]
            out.append((bool(acts), sum(n['cost'][a] for a in acts), sum(n['dt'][a] for a in acts)))
            continue
        plan = chain if isinstance(chain, list) else chain[n['label']]
        toks = secs = 0.0; rec = False
        for a in plan:
            if t_rem is not None and n['dt'][a] > t_rem - secs: continue
            if c_rem is not None and n['cost'][a] > c_rem - toks: continue
            toks += n['cost'][a]; secs += n['dt'][a]
            if n['succ'][a]: rec = True; break
        out.append((rec, toks, secs))
    return out

def pareto(points):
    nd = []
    for name, (q, c, l) in points.items():
        if not any((q2 >= q and c2 <= c and l2 <= l) and (q2 > q or c2 < c or l2 < l)
                   for _, (q2, c2, l2) in points.items() if (q2, c2, l2) != (q, c, l)):
            nd.append(name)
    return nd

def run():
    nodes_all = load()
    clean = [n for n in nodes_all if not n['orig_correct']]
    rep = dict(seed=SEED, B=B, universe_n=len(clean),
               full_sweep={}, token_budget_grid={}, time_budget_grid={},
               pareto_frontier={}, utility_sensitivity={})
    for name, chain in STRATS.items():
        sim = simulate_budget(clean, chain)
        st = stats(sim); st['Q_ci95_cluster'] = bootstrap_ci(clean, sim)
        rep['full_sweep'][name] = st
    for c in C_GRID:
        rep['token_budget_grid'][str(c)] = {
            name: stats(simulate_budget(clean, chain, c_rem=c)) for name, chain in STRATS.items()}
    for t in T_GRID:
        rep['time_budget_grid'][str(t)] = {
            name: stats(simulate_budget(clean, chain, t_rem=t)) for name, chain in STRATS.items()}
    pts = {n: (v['Q'], v['C_mean_tokens'] / 1000, v['L_mean_s'])
           for n, v in rep['full_sweep'].items() if v['Q'] is not None}
    rep['pareto_frontier'] = pareto(pts)
    rep['pareto_points'] = pts
    # U = Q - lam*C_ktok - mu*L_s
    deployable = {n: p for n, p in pts.items() if n != 'oracle_upper'}
    for lam in [0.0, 0.01, 0.05, 0.2]:
        for mu in [0.0, 0.02, 0.1, 0.5]:
            best = max(deployable, key=lambda n: pts[n][0] - lam * pts[n][1] - mu * pts[n][2])
            rep['utility_sensitivity'][f'lam={lam},mu={mu}'] = best
    (OUT / 'BUDGET_CURVES.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep

if __name__ == '__main__':
    r = run()
    print(json.dumps(dict(universe_n=r['universe_n'], pareto=r['pareto_frontier'], pareto_points=r['pareto_points'],
                          utility=dict(sorted(r['utility_sensitivity'].items())),
                          sweep={k: (v['Q'], v['C_mean_tokens'], v['L_mean_s']) for k, v in r['full_sweep'].items()}), ensure_ascii=False, indent=2))
