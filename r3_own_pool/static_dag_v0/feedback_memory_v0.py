"""Feedback Memory v0: sequential replay over the frozen fresh-holdout node table.

Zero generation. Walks the 493 primary nodes in frozen task order; each node:
predict with the frozen dev Node Router, fuse with the online memory estimate
Q_mem(type,m)=(S+1)/(N+2), select by the frozen utility, 'execute' by reading
the chosen model's realized Q/C/L from SCORED_MATRIX, then update memory.
Pass criterion for v0 is mechanical: the loop runs end-to-end and earlier
executions demonstrably change later selections. No tuning; lambda=0.3 primary
with {0.1,0.5} reported as non-gating sensitivity.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/feedback_memory_v0'
POOL = ['medium', 'large', 'coder']
TYPE_ORDER = {'extraction': 0, 'reasoning': 1, 'verification': 2}
LAMBDA = 0.3
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0


def features(npz, nodes):
    types = np.array([[1.0 if n['node_type'] == t else 0.0 for t in ['extraction', 'transformation', 'reasoning', 'verification']]
                      for n in nodes])
    ctx = np.log1p(np.array([len(n['question']) for n in nodes], dtype=float)).reshape(-1, 1)
    qmap = {q: i for i, q in enumerate(npz['questions'].tolist())}
    emb = np.array([npz['emb'][qmap[n['question']]] for n in nodes])
    return np.hstack([emb, types, ctx])


def replay(nodes, matrix, X, coef, intercept, mean_C, mean_L, lam):
    N = {(t, m): 0 for t in TYPE_ORDER for m in POOL}
    S = {(t, m): 0 for t in TYPE_ORDER for m in POOL}
    qhat = X @ coef.T + intercept                      # (nodes, 3)
    trace, choices = [], np.zeros(len(nodes), dtype=int)
    for i, n in enumerate(nodes):
        mem = np.array([(S[(n['node_type'], m)] + 1) / (N[(n['node_type'], m)] + 2) for m in POOL])
        q_fb = (1 - lam) * qhat[i] + lam * mem
        u = q_fb - ALPHA_C * mean_C - ALPHA_L * mean_L
        pick = int(np.argmax(u))
        choices[i] = pick
        actual_q = float(matrix['Q'][i, pick])
        upstream_valid = True  # conditional node table: reasoning/verification scored on gold inputs
        if upstream_valid:
            N[(n['node_type'], POOL[pick])] += 1
            S[(n['node_type'], POOL[pick])] += int(actual_q > 0)
        trace.append(dict(task_uid=n['task_uid'], node_id=n['node_id'], node_type=n['node_type'],
                          model=POOL[pick], predicted_q_node=round(float(qhat[i, pick]), 4),
                          q_mem_prior=round(float(mem[pick]), 4), q_fused=round(float(q_fb[pick]), 4),
                          actual_q=actual_q, tokens=int(matrix['C'][i, pick]),
                          latency_s=round(float(matrix['L'][i, pick]), 4),
                          status='success' if actual_q > 0 else 'failure',
                          upstream_valid=upstream_valid))
    return choices, trace, (N, S)


def realize(choices, matrix):
    Q = matrix['Q'][np.arange(len(choices)), choices]
    C = matrix['C'][np.arange(len(choices)), choices].astype(float)
    L = matrix['L'][np.arange(len(choices)), choices].astype(float)
    return dict(Q=float(Q.mean()), tokens=float(C.mean()), latency_s=float(L.mean()),
                utility=float((Q - ALPHA_C * C - ALPHA_L * L).mean()))


def run():
    if OUT.exists():
        raise FileExistsError('feedback_memory_v0 already exists')
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    order = {t['uid']: k for k, t in enumerate(json.loads((SRC / 'TASKS.json').read_text()))}
    idx = [i for i, n in enumerate(nodes_all) if matrix['main'][i]]
    idx.sort(key=lambda i: (order[nodes_all[i]['task_uid']], TYPE_ORDER.get(nodes_all[i]['node_type'], 9),
                            nodes_all[i]['node_id']))
    nodes = [nodes_all[i] for i in idx]
    sub = {k: v[idx] for k, v in matrix.items() if k in ('Q', 'C', 'L', 'FrozenNodeRouter', 'NodeOracle')}
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    X = features(emb, nodes)
    coef, intercept = dev['NodeRouter_coef'], dev['NodeRouter_intercept']
    mean_C, mean_L = dev['mean_C'], dev['mean_L']

    choices, trace, counts = replay(nodes, sub, X, coef, intercept, mean_C, mean_L, LAMBDA)
    frozen = sub['FrozenNodeRouter'].astype(int)
    oracle = sub['NodeOracle'].astype(int)
    changed = choices != frozen
    helped = sum(sub['Q'][i, choices[i]] > sub['Q'][i, frozen[i]] for i in np.flatnonzero(changed))
    harmed = sum(sub['Q'][i, choices[i]] < sub['Q'][i, frozen[i]] for i in np.flatnonzero(changed))
    sensitivity = {}
    for lam in (0.1, 0.5):
        c, _, _ = replay(nodes, sub, X, coef, intercept, mean_C, mean_L, lam)
        sensitivity[f'lambda={lam}'] = realize(c, sub)
    tasks = sorted({n['task_uid'] for n in nodes})
    task_of = np.array([tasks.index(n['task_uid']) for n in nodes])
    rng = np.random.default_rng(20260915)
    diff = sub['Q'][np.arange(len(choices)), choices] - sub['Q'][np.arange(len(choices)), frozen]
    per_task = np.array([diff[task_of == t].mean() for t in range(len(tasks))])
    boots = rng.integers(0, len(tasks), (10000, len(tasks)))
    ci = np.quantile(per_task[boots].mean(1), [.025, .975]).tolist()
    OUT.mkdir()
    (OUT / 'REPLAY.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in trace))
    memN, memS = counts
    results = dict(
        experiment='Feedback Memory v0 (sequential replay, zero generation)',
        frozen=dict(order='TASKS.json order; intra-task extraction->reasoning->verification',
                    memory_update='Q_mem(type,m)=(S+1)/(N+2); only upstream_valid rows update',
                    upstream_valid_note='conditional table: all rows valid by construction',
                    fusion=f'Q_fb=(1-lambda)*Q_node+lambda*Q_mem with lambda={LAMBDA} primary',
                    selection='frozen utility weights, dev C/L profiles'),
        arms=dict(FrozenNodeRouter=realize(frozen, sub), FeedbackRouter=realize(choices, sub),
                  NodeOracle=realize(oracle, sub)),
        mechanism=dict(decision_changes=int(changed.sum()), helped=int(helped), harmed=int(harmed),
                       changed_examples=[dict(node_id=nodes[i]['node_id'], node_type=nodes[i]['node_type'],
                                              frozen=POOL[frozen[i]], feedback=POOL[choices[i]])
                                         for i in np.flatnonzero(changed)[:8]],
                       final_memory={t: {m: [memS[(t, m)], memN[(t, m)]] for m in POOL} for t in TYPE_ORDER}),
        feedback_minus_frozen=dict(Q_mean=float(diff.mean()), ci95_task_cluster=ci),
        sensitivity_non_gating=sensitivity,
        gates=dict(v0_pass=f'loop runs end-to-end; decision_changes={int(changed.sum())}>0',
                   note='no significance gate today; lambda and order seeds for later'))
    core.write(OUT / 'RESULTS.json', results)
    print(json.dumps(dict(arms=dict(FrozenNodeRouter=realize(frozen, sub), FeedbackRouter=realize(choices, sub),
                                    NodeOracle=realize(oracle, sub)),
                          decision_changes=int(changed.sum()), helped=int(helped),
                          harmed=int(harmed), Q_delta_ci=ci), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
