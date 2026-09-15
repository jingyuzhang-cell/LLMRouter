"""Multi-objective formal experiment: Pareto over measured execution policies.

Two workloads, analyzed separately because Q is not comparable across them:
(a) benchmark scale (fresh 493-node table): Always Large, Static Node Router,
Feedback v1, Dynamic-Reroute (perfect detection), Type-aware Dynamic, Oracle
(upper bound, excluded from deployable sets). Effective cost = mean selected
tokens x execution-call multiplier + verifier-call overhead (600 tokens/call,
flagged estimate). Effective latency = mean per-node service latency x the
same multiplier. (b) follow-up workload (graph_forest_v1): fresh full-chain
execution vs Forest reuse. Outputs single-objective optima, bi/tri-objective
non-dominated sets, and the selected final plan.
"""
import argparse
import json

from . import core

FB = core.ROOT / 'static_dag_v0/feedback_state_aware_v1/RESULTS.json'
DY = core.ROOT / 'static_dag_v0/dynamic_dag_v0/RESULTS.json'
TA = core.ROOT / 'static_dag_v0/type_aware_gate_ablation/RESULTS.json'
GF = core.ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation/SCORED_MATRIX.npz'
OUT = core.ROOT / 'static_dag_v0/multi_objective_formal'
VERIFIER_TOKENS_PER_CALL = 600  # flagged estimate (coder v0 check: question+facts+expression)
Q_MINS = [0.50, 0.52, 0.55]


def pareto(d, dims):
    sign = {'Q': 1.0, 'C': -1.0, 'L': -1.0, 'C_eff': -1.0, 'L_eff': -1.0}
    vec = {k: tuple(sign[t] * v[t] for t in dims) for k, v in d.items()}
    def dom(a, b):
        return all(x >= y - 1e-12 for x, y in zip(a, b)) and any(x > y + 1e-12 for x, y in zip(a, b))
    return sorted(k for k in d if not any(dom(vec[j], vec[k]) for j in d if j != k))


def run():
    if OUT.exists():
        raise FileExistsError('multi_objective_formal already exists')
    import numpy as np
    matrix = dict(np.load(SRC, allow_pickle=False))
    fb = json.loads(FB.read_text())
    dy = json.loads(DY.read_text())['stats']
    ta = json.loads(TA.read_text())['arms']
    gf = json.loads(GF.read_text())['summary']
    n_nodes = int(matrix['main'].sum())
    al = (float(matrix['Q'][matrix['main'], 0].mean()), float(matrix['C'][matrix['main'], 0].mean()),
          float(matrix['L'][matrix['main'], 0].mean()))
    f = fb['arms']['FeedbackV1']
    candidates = {
        'Always Large': dict(Q=al[0], C=al[1], L=al[2], calls=1.0, deployable=True,
                             note='anchor'),
        'Static Node Router': dict(Q=fb['arms']['NodeRouter']['Q'], C=fb['arms']['NodeRouter']['tokens'],
                                   L=fb['arms']['NodeRouter']['latency_s'], calls=1.0, deployable=True,
                                   note='frozen node router'),
        'Feedback v1 (state-aware)': dict(Q=f['Q'], C=f['tokens'], L=f['latency_s'], deployable=True,
                                          calls=fb['calls_multiplier_v1'],
                                          note='memory-driven fallback'),
        'Dynamic-Reroute (perfect detection)': dict(
            Q=dy['deployable_second_only']['Q'], C=dy['deployable_second_only']['tokens'],
            L=dy['deployable_second_only']['latency_s'], deployable=False,
            calls=dy['deployable_second_only']['calls_multiplier'],
            note='upper-bound detection; excluded from deployable sets'),
        'Type-aware Dynamic': dict(Q=ta['type_aware']['Q'], C=ta['type_aware']['tokens'],
                                   L=None, deployable=True, calls=ta['type_aware']['calls_multiplier'],
                                   verifier_calls=ta['type_aware']['verifier_calls'],
                                   note='verifier-gated on verification-type nodes only'),
        'Oracle (upper bound)': dict(Q=dy['final']['Q'], C=float(matrix['C'][matrix['main']].min(1).mean()),
                                     L=float(matrix['L'][matrix['main']].min(1).mean()),
                                     deployable=False, calls=1.0, note='hindsight'),
    }
    for k, c in candidates.items():
        exec_mult = c['calls']
        v_calls = c.get('verifier_calls', 0)
        c['C_eff'] = c['C'] * exec_mult + VERIFIER_TOKENS_PER_CALL * v_calls / n_nodes
        c['L_eff'] = (c['L'] or c['C'] * 0) * exec_mult if c['L'] is not None else None
    lat_avail = {k: v for k, v in candidates.items() if v['L_eff'] is not None}
    deployable = {k: v for k, v in candidates.items() if v['deployable']}
    single = {}
    for qmin in Q_MINS:
        feasible = [k for k, v in deployable.items() if v['Q'] >= qmin]
        single[f'minC_s.t.Q>={qmin}'] = dict(
            feasible=feasible,
            best=min(feasible, key=lambda k: deployable[k]['C_eff']) if feasible else None)
    c_sorted = sorted(v['C_eff'] for v in deployable.values())
    c_max = c_sorted[len(c_sorted) // 2]
    single['maxQ_s.t.C<=median'] = dict(C_max=c_max,
                                        best=max((k for k, v in deployable.items() if v['C_eff'] <= c_max),
                                                 key=lambda k: deployable[k]['Q']))
    bi = pareto(deployable, ('Q', 'C_eff'))
    tri = pareto({k: v for k, v in deployable.items() if v['L_eff'] is not None}, ('Q', 'C_eff', 'L_eff'))
    followup = dict(
        fresh=dict(calls_per_task=4.0, token_reduction=None),
        forest=dict(calls_per_task=2.0, call_reduction=gf['call_reduction'],
                    token_reduction=gf['token_reduction'],
                    executes=gf['executes'], responds=gf['responds_to_modification']),
        note='follow-up workload; Q is execution-level (19/20), not benchmark-comparable')
    selected = single['minC_s.t.Q>=0.52']['best'] or single['minC_s.t.Q>=0.50']['best']
    OUT.mkdir()
    core.write(OUT / 'RESULTS.json', dict(
        candidates=candidates, single_objective=single, bi_pareto=bi, tri_pareto=tri,
        followup_workload=followup, selected_final_plan=selected,
        assumptions=dict(verifier_tokens_per_call=VERIFIER_TOKENS_PER_CALL,
                         C_eff='mean selected tokens x exec call multiplier + verifier overhead / n',
                         L_eff='mean per-node service latency x exec call multiplier',
                         oracle_and_perfect_detection_excluded_from_deployable_sets=True)))
    print(json.dumps(dict(candidates={k: dict(Q=round(v['Q'], 4), C_eff=round(v['C_eff'], 1),
                                              L_eff=round(v['L_eff'], 3) if v['L_eff'] else None,
                                              deployable=v['deployable'])
                                     for k, v in candidates.items()},
                          single={k: v.get('best') for k, v in single.items()},
                          bi_pareto=bi, tri_pareto=tri, selected=selected), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
