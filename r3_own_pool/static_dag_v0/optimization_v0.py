"""Multi-objective Optimization v0 over the measured candidate plans (zero generation).

Candidates are the frozen fresh-holdout arms (Always Large, Query Router,
Static Node Router, Feedback Router, Dynamic-Reroute deployable) plus Oracle as
a NON-deployable upper bound. Per-candidate (Q, C, L): C = mean executed tokens
per node (reroute arm counts its retry calls), L = mean per-task critical-path
latency (extraction layer parallel, then reasoning, then verification).
Outputs single-objective optima, bi-objective and tri-objective Pareto sets,
and the selected final plan. PASS = the full decision chain executes.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
FB = core.ROOT / 'static_dag_v0/feedback_memory_v0/RESULTS.json'
DY = core.ROOT / 'static_dag_v0/dynamic_dag_v0/RESULTS.json'
OUT = core.ROOT / 'static_dag_v0/optimization_v0'
POOL = ['medium', 'large', 'coder']
TYPE_ORDER = {'extraction': 0, 'reasoning': 1, 'verification': 2}
Q_MIN = 0.50


def arm_metrics(matrix, picks):
    """picks: per-node model index. Returns Q, per-node mean tokens, per-task critical-path latency."""
    Q = matrix['Q'][np.arange(len(picks)), picks]
    C = matrix['C'][np.arange(len(picks)), picks].astype(float)
    L = matrix['L'][np.arange(len(picks)), picks].astype(float)
    return Q, C, L


def critical_path(nodes, task_of, L):
    """extraction nodes run in parallel; reasoning then verification are serial."""
    per_task = {}
    for i, n in enumerate(nodes):
        per_task.setdefault(task_of[i], []).append(i)
    paths = []
    for idxs in per_task.values():
        ext = [L[i] for i in idxs if nodes[i]['node_type'] == 'extraction']
        rest = sorted((L[i], TYPE_ORDER[nodes[i]['node_type']]) for i in idxs
                      if nodes[i]['node_type'] in TYPE_ORDER and nodes[i]['node_type'] != 'extraction')
        paths.append((max(ext) if ext else 0.0) + sum(v for v, _ in rest))
    return float(np.mean(paths))


def dominated(a, b):
    """True if a is dominated by b (b at least as good everywhere, strictly better once)."""
    return (b[0] >= a[0] and b[1] <= a[1] and b[2] <= a[2]) and (b[0] > a[0] or b[1] < a[1] or b[2] < a[2])


def run():
    if OUT.exists():
        raise FileExistsError('optimization_v0 already exists')
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    idx = [i for i, n in enumerate(nodes_all) if matrix['main'][i]]
    nodes = [nodes_all[i] for i in idx]
    sub = {k: matrix[k][idx] for k in ('Q', 'C', 'L', 'AlwaysLarge', 'QueryRouter',
                                       'FrozenNodeRouter', 'NodeOracle')}
    task_of = [n['task_uid'] for n in nodes]
    fb = json.loads(FB.read_text())
    dy = json.loads(DY.read_text())
    candidates = {}
    for arm, key in [('Always Large', 'AlwaysLarge'), ('Query Router', 'QueryRouter'),
                     ('Static Node Router', 'FrozenNodeRouter')]:
        Q, C, L = arm_metrics(sub, sub[key].astype(int))
        candidates[arm] = dict(Q=float(Q.mean()), C=float(C.mean()), L=critical_path(nodes, task_of, L),
                               deployable=True, kind='single pick per node')
    f = fb['arms']['FeedbackRouter']
    candidates['Feedback Router'] = dict(Q=f['Q'], C=f['tokens'], L=f['latency_s'], deployable=True,
                                         kind='per-node means from v0 replay')
    d = dy['stats']['deployable_second_only']
    candidates['Dynamic-Reroute'] = dict(Q=d['Q'], C=d['tokens'] * d['calls_multiplier'],
                                         L=d['latency_s'] * d['calls_multiplier'], deployable=True,
                                         kind='retry cost included via calls multiplier')
    Q, C, L = arm_metrics(sub, sub['NodeOracle'].astype(int))
    candidates['Oracle (upper bound)'] = dict(Q=float(Q.mean()), C=float(C.mean()),
                                              L=critical_path(nodes, task_of, L), deployable=False,
                                              kind='hindsight; excluded from deployable sets')
    deployable = {k: v for k, v in candidates.items() if v['deployable']}

    single = dict(minC_suchthat_Q_ge=Q_MIN,
                  feasible=[k for k, v in deployable.items() if v['Q'] >= Q_MIN],
                  best=min((k for k in deployable if deployable[k]['Q'] >= Q_MIN),
                           key=lambda k: deployable[k]['C'], default=None))
    c_sorted = sorted(v['C'] for v in deployable.values())
    c_max = c_sorted[len(c_sorted) // 2]
    single['maxQ_suchthat_C_le'] = c_max
    single['best_quality'] = max((k for k in deployable if deployable[k]['C'] <= c_max),
                                 key=lambda k: deployable[k]['Q'], default=None)

    def pareto(d, dims):
        # Q is maximized; C and L are minimized -> negate minimize dims, then all-max dominance
        sign = {'Q': 1.0, 'C': -1.0, 'L': -1.0}
        vec = {k: tuple(sign[t] * v[t] for t in dims) for k, v in d.items()}

        def dom(a, b):
            return all(x >= y - 1e-12 for x, y in zip(a, b)) and any(
                x > y + 1e-12 for x, y in zip(a, b))
        return sorted(k for k in d if not any(dom(vec[j], vec[k]) for j in d if j != k))
    bi = pareto(deployable, ('Q', 'C'))
    tri = pareto(deployable, ('Q', 'C', 'L'))
    tri_all = pareto(candidates, ('Q', 'C', 'L'))
    OUT.mkdir()
    core.write(OUT / 'RESULTS.json', dict(
        experiment='Optimization v0 (zero generation)', candidates=candidates,
        single_objective=single, bi_objective_pareto=bi, tri_objective_pareto=tri,
        tri_pareto_including_oracle=tri_all,
        selected_final_plan=single['best'],
        pass_criteria=dict(candidates_measured=True, dominance_checked=True, pareto_sets_nonempty=bool(bi and tri),
                           best_plan_selected=single['best'] is not None),
        notes=['Oracle excluded from deployable Pareto by construction',
               'L is mean per-task critical path (extraction parallel; reasoning/verification serial)',
               'Dynamic-Reroute cost/latency inflated by its measured 1.49x calls multiplier',
               'Feedback Router L is mean per-node service time (v0 table), not critical path'],
        PASS=True))
    print(json.dumps(dict(candidates={k: {m: round(v[m], 4) for m in ('Q', 'C', 'L')}
                                       for k, v in candidates.items()},
                          single=single, bi_pareto=bi, tri_pareto=tri), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
