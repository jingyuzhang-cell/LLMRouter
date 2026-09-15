"""Type-aware Verifier Gate Ablation: three failure-detection policies.

Same deterministic replay universe as system_verifier_impact (fresh table,
frozen router utilities, verifier behaviour from measured confusion matrices,
seed 20260915). Arms: (1) No verifier - detection never fires, equals static
picks; (2) Global verifier - detection on all expression-bearing nodes (the
system_verifier_impact result); (3) Type-aware - verifier-driven reroute ONLY
on verification-type nodes (recall .95 / FA .20); reasoning nodes keep their
first pick conservatively. One reroute attempt with one re-verify.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
DYN = core.ROOT / 'static_dag_v0/dynamic_dag_v0/RESULTS.json'
OUT = core.ROOT / 'static_dag_v0/type_aware_gate_ablation'
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
CM = {'verification': [0.95, 0.20], 'reasoning': [0.273, 0.167]}
SEED = 20260915


def replay(nodes, sub, u, policy):
    rng = np.random.default_rng(SEED)
    picks = np.zeros(len(nodes), dtype=int)
    stats = dict(reroutes=0, recovered=0, missed_failures=0, wasted_replans=0, verifier_calls=0)
    for i, n in enumerate(nodes):
        order = list(np.argsort(-u[i]))
        pick = int(order[0])
        q_val = float(sub['Q'][i, pick])
        detect = (n['node_type'] in CM) and (policy == 'global' or
                                             (policy == 'type_aware' and n['node_type'] == 'verification'))
        if detect:
            reject_p = CM[n['node_type']][0] if q_val <= 0 else CM[n['node_type']][1]
            stats['verifier_calls'] += 1
            if rng.random() < reject_p:
                stats['reroutes'] += 1
                if q_val > 0:
                    stats['wasted_replans'] += 1
                second = int(order[1])
                q2 = float(sub['Q'][i, second])
                reject2_p = CM[n['node_type']][0] if q2 <= 0 else CM[n['node_type']][1]
                stats['verifier_calls'] += 1
                if rng.random() < reject2_p and len(order) > 2:
                    stats['reroutes'] += 1
                    if q2 > 0:
                        stats['wasted_replans'] += 1
                    pick = int(order[2])
                    q2 = float(sub['Q'][i, pick])
                else:
                    pick = second
                q_val = q2
                if q_val > 0 and float(sub['Q'][i, int(order[0])]) <= 0:
                    stats['recovered'] += 1
            elif q_val <= 0:
                stats['missed_failures'] += 1
        picks[i] = pick
    Q = sub['Q'][np.arange(len(picks)), picks]
    C = sub['C'][np.arange(len(picks)), picks].astype(float)
    return dict(Q=float(Q.mean()), tokens=float(C.mean()),
                calls_multiplier=float((len(nodes) + stats['reroutes']) / len(nodes)),
                **stats)


def run():
    if OUT.exists():
        raise FileExistsError('type_aware_gate_ablation already exists')
    OUT.mkdir()
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    idx = [i for i, n in enumerate(nodes_all) if matrix['main'][i]]
    nodes = [nodes_all[i] for i in idx]
    sub = {k: matrix[k][idx] for k in ('Q', 'C', 'L', 'FrozenNodeRouter')}
    types = np.array([[1.0 if n['node_type'] == t else 0.0
                       for t in ['extraction', 'transformation', 'reasoning', 'verification']] for n in nodes])
    ctx = np.log1p(np.array([len(n['question']) for n in nodes], dtype=float)).reshape(-1, 1)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    X = np.hstack([np.array([emb['emb'][qmap[n['question']]] for n in nodes]), types, ctx])
    u = X @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
        ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
    dyn = json.loads((DYN).read_text())['stats']
    static_q = float(np.mean(sub['Q'][np.arange(len(nodes)), sub['FrozenNodeRouter'].astype(int)]))
    arms = {p: replay(nodes, sub, u, p) for p in ('no_verifier', 'global', 'type_aware')}
    oracle_q = dyn['final']['Q']
    for p, a in arms.items():
        a['recovery_vs_static'] = (a['Q'] - static_q) / (oracle_q - static_q)
    core.write(OUT / 'RESULTS.json', dict(arms=arms, static_q=static_q, perfect_detection_reference=dyn['deployable_second_only'],
                                          oracle_bound=oracle_q,
                                          note='verifier behaviour from measured confusion matrices; '
                                               'type_aware gates only verification-type nodes; zero generation'))
    print(json.dumps(dict(arms={p: {k: (round(v, 4) if isinstance(v, float) else v)
                                    for k, v in a.items()} for p, a in arms.items()},
                          static_q=round(static_q, 4)), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
