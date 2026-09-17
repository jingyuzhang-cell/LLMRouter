"""State-aware Feedback v1: memory now conditions on node state.

Upgrade over v0 on two axes (zero generation, same sequential replay):
(a) initial-choice memory keyed by (node_type, length_bucket, model) instead of
    (node_type, model);
(b) FAILURE-STATE memory: when a node fails, the fallback model is chosen by
    fusing the frozen node-utility with a reroute-state success memory
    (lambda'=0.5), replacing the frozen second-best rule. One fallback max,
    same call budget as Dynamic-Reroute.
Arms: static frozen / Feedback v0 / Feedback v1 / Dynamic-Reroute (fixed rule,
reference) / Node Oracle.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/feedback_state_aware_v1'
POOL = ['medium', 'large', 'coder']
TYPE_ORDER = {'extraction': 0, 'reasoning': 1, 'verification': 2}
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
LAMBDA, LAMBDA_FAIL = 0.3, 0.5
LEN_SPLIT = 150  # frozen: question chars < 150 -> short bucket


def bucket(n):
    return 'short' if len(n['question']) < LEN_SPLIT else 'long'


def beta_mem(S, N):
    return (S + 1) / (N + 2)


def run():
    if OUT.exists():
        raise FileExistsError('feedback_state_aware_v1 already exists')
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX_EXEC.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    order = {t['uid']: k for k, t in enumerate(json.loads((SRC / 'TASKS.json').read_text()))}
    idx = [i for i, n in enumerate(nodes_all) if matrix['main'][i]]
    idx.sort(key=lambda i: order[nodes_all[i]['task_uid']])
    nodes = [nodes_all[i] for i in idx]
    sub = {k: matrix[k][idx] for k in ('Q', 'C', 'L', 'FrozenNodeRouter', 'NodeOracle')}
    types = np.array([[1.0 if n['node_type'] == t else 0.0
                       for t in ['extraction', 'transformation', 'reasoning', 'verification']] for n in nodes])
    ctx = np.log1p(np.array([len(n['question']) for n in nodes], dtype=float)).reshape(-1, 1)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    X = np.hstack([np.array([emb['emb'][qmap[n['question']]] for n in nodes]), types, ctx])
    qhat = X @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept']
    u_frozen = qhat - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']

    mem_v0 = {(t, m): [0, 0] for t in TYPE_ORDER for m in POOL}          # (S, N)
    mem_v1 = {(t, b, m): [0, 0] for t in TYPE_ORDER for b in ('short', 'long') for m in POOL}
    mem_fail = {(t, m): [0, 0] for t in TYPE_ORDER for m in POOL}
    picks_v0 = np.zeros(len(nodes), dtype=int)
    picks_v1 = np.zeros(len(nodes), dtype=int)
    calls_v1 = 0
    helped_vs_v0 = harmed_vs_v0 = 0
    for i, n in enumerate(nodes):
        t = n['node_type']
        # v0 arm: type-level memory on initial choice, frozen-utility fallback
        q0 = np.array([(1 - LAMBDA) * qhat[i, k] + LAMBDA * beta_mem(*mem_v0[(t, m)]) for k, m in enumerate(POOL)])
        p0 = int(np.argmax(q0 - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))
        q_actual = float(sub['Q'][i, p0])
        mem_v0[(t, POOL[p0])][0] += int(q_actual > 0)
        mem_v0[(t, POOL[p0])][1] += 1
        picks_v0[i] = p0
        # v1 arm: state-aware initial + failure-state fallback
        b = bucket(n)
        q1 = np.array([(1 - LAMBDA) * qhat[i, k] + LAMBDA * beta_mem(*mem_v1[(t, b, m)]) for k, m in enumerate(POOL)])
        p1 = int(np.argmax(q1 - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))
        calls_v1 += 1
        q1_actual = float(sub['Q'][i, p1])
        if q1_actual <= 0:
            # failure state: choose fallback via reroute memory, not frozen ranking
            qf = np.array([(1 - LAMBDA_FAIL) * qhat[i, k] + LAMBDA_FAIL * beta_mem(*mem_fail[(t, m)])
                           for k, m in enumerate(POOL) if k != p1])
            alt = [k for k in range(3) if k != p1]
            p1 = alt[int(np.argmax(qf))]
            calls_v1 += 1
            q1_actual = float(sub['Q'][i, p1])
            mem_fail[(t, POOL[p1])][0] += int(q1_actual > 0)
            mem_fail[(t, POOL[p1])][1] += 1
        else:
            mem_v1[(t, b, POOL[p1])][0] += int(q1_actual > 0)
            mem_v1[(t, b, POOL[p1])][1] += 1
        picks_v1[i] = p1
        if sub['Q'][i, p1] > sub['Q'][i, picks_v0[i]]:
            helped_vs_v0 += 1
        elif sub['Q'][i, p1] < sub['Q'][i, picks_v0[i]]:
            harmed_vs_v0 += 1

    def realize(picks):
        Q = sub['Q'][np.arange(len(picks)), picks]
        C = sub['C'][np.arange(len(picks)), picks].astype(float)
        L = sub['L'][np.arange(len(picks)), picks].astype(float)
        return dict(Q=float(Q.mean()), tokens=float(C.mean()), latency_s=float(L.mean()),
                    utility=float((Q - ALPHA_C * C - ALPHA_L * L).mean()))
    frozen = sub['FrozenNodeRouter'].astype(int)
    oracle = sub['NodeOracle'].astype(int)
    # dynamic-reroute reference (frozen-utility second best, from dynamic_dag_v0)
    dyn = json.loads((core.ROOT / 'static_dag_v0/dynamic_dag_v0/RESULTS.json').read_text())
    tasks = sorted({n['task_uid'] for n in nodes})
    task_of = np.array([tasks.index(n['task_uid']) for n in nodes])
    diff = sub['Q'][np.arange(len(picks_v1)), picks_v1] - sub['Q'][np.arange(len(picks_v0)), picks_v0]
    per_task = np.array([diff[task_of == t].mean() for t in range(len(tasks))])
    rng = np.random.default_rng(20260915)
    boots = rng.integers(0, len(tasks), (10000, len(tasks)))
    ci = np.quantile(per_task[boots].mean(1), [.025, .975]).tolist()
    OUT.mkdir()
    core.write(OUT / 'RESULTS.json', dict(
        experiment='State-aware Feedback v1 (zero generation)',
        design=dict(initial_memory='(type, length_bucket, model) Beta(1,1) online; lambda=0.3',
                    failure_memory='(type, model) reroute-state successes; fallback lambda=0.5; one fallback max',
                    reference='fallback no longer the frozen utility second-best'),
        arms=dict(NodeRouter=realize(frozen), FeedbackV0=realize(picks_v0), FeedbackV1=realize(picks_v1),
                  NodeOracle=realize(oracle)),
        dynamic_reroute_reference=dyn['stats']['deployable_second_only'],
        calls_multiplier_v1=calls_v1 / len(nodes),
        decision_changes_vs_v0=int((picks_v1 != picks_v0).sum()),
        helped_vs_v0=helped_vs_v0, harmed_vs_v0=harmed_vs_v0,
        v1_minus_v0=dict(Q=float(diff.mean()), ci95_task_cluster=ci)))
    print(json.dumps(dict(arms=dict(NodeRouter=realize(frozen), FeedbackV0=realize(picks_v0),
                                    FeedbackV1=realize(picks_v1), NodeOracle=realize(oracle)),
                          dynamic_ref={k: round(v, 4) for k, v in dyn['stats']['deployable_second_only'].items()
                                       if isinstance(v, float)},
                          calls_mult=round(calls_v1 / len(nodes), 3),
                          changes=int((picks_v1 != picks_v0).sum()),
                          helped=helped_vs_v0, harmed=harmed_vs_v0,
                          v1_minus_v0_ci=ci), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
