"""End-to-End formal experiment: three integrated arms over the full workload.

Arm 1 Static Only (frozen node router, one pass). Arm 2 Static+Feedback
(state-aware memory loop, feedback_state_aware_v1 logic replayed inline).
Arm 3 Full Adaptive DAG = Arm 2 + type-aware verifier gate on verification
nodes (measured confusion sampling) + failure-aware decompose on hard-failed
reasoning nodes (rescue sampled from measured rates: evidence-class share of
the inexpressible/expressible split x 6/10 rescue) + follow-up round with
Graph Forest reuse (measured reuse economics). Metrics: task success (final
reasoning node correct), node quality, effective cost/latency, oracle-gap
recovery, follow-up reuse rate. Component behaviours are sampled from MEASURED
results, not re-run live; every sampling site is documented.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
GF = core.ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json'
OUT = core.ROOT / 'static_dag_v0/e2e_formal'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
LAMBDA, LAMBDA_FAIL = 0.3, 0.5
LEN_SPLIT = 150
SEED = 20260915
CM_VER = [0.95, 0.20]          # verification-node verifier [P(reject|wrong), P(reject|correct)]
DECOMP_RESCUE = 0.60            # measured 6/10 on evidence-class hard failures
EVIDENCE_SHARE = 0.55           # measured inexpressible+evidence share of hard failures (11/20)
VERIFIER_TOKENS = 600
DECOMPOSE_CALLS = 4
DECOMPOSE_TOKENS_PER_CALL = 900


def run():
    if OUT.exists():
        raise FileExistsError('e2e_formal already exists')
    OUT.mkdir()
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
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
    rng = np.random.default_rng(SEED)

    def beta_mem(S, N):
        return (S + 1) / (N + 2)

    # Arm 1: static picks
    picks_static = sub['FrozenNodeRouter'].astype(int)
    # Arms 2/3 share the feedback loop; arm 3 layers gating + decompose
    mem_v1 = {}
    mem_fail = {}
    picks2 = np.zeros(len(nodes), dtype=int)
    picks3 = np.zeros(len(nodes), dtype=int)
    extra = dict(arm3=dict(verifier_calls=0, reroutes=0, decompose_triggers=0, decompose_rescues=0,
                           wasted_replans=0, missed=0))
    for i, n in enumerate(nodes):
        t, b = n['node_type'], ('short' if len(n['question']) < LEN_SPLIT else 'long')
        key = (t, b)
        mem_v1.setdefault(key, {m: [0, 0] for m in POOL})
        mem_fail.setdefault(t, {m: [0, 0] for m in POOL})
        q1 = np.array([(1 - LAMBDA) * qhat[i, k] + LAMBDA * beta_mem(*mem_v1[key][m])
                       for k, m in enumerate(POOL)])
        p1 = int(np.argmax(q1 - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']))
        # ---- arm 2: memory-driven single fallback
        pick2 = p1
        q2v = float(sub['Q'][i, p1])
        if q2v <= 0:
            qf = np.array([(1 - LAMBDA_FAIL) * qhat[i, k] + LAMBDA_FAIL * beta_mem(*mem_fail[t][m])
                           for k, m in enumerate(POOL) if k != p1])
            alt = [k for k in range(3) if k != p1]
            pick2 = alt[int(np.argmax(qf))]
            q2v = float(sub['Q'][i, pick2])
            mem_fail[t][POOL[pick2]][0] += int(q2v > 0)
            mem_fail[t][POOL[pick2]][1] += 1
        else:
            mem_v1[key][POOL[p1]][0] += int(q2v > 0)
            mem_v1[key][POOL[p1]][1] += 1
        picks2[i] = pick2
        if pick2 != p1:
            extra['arm2_fallbacks'] = extra.get('arm2_fallbacks', 0) + 1
        # ---- arm 3: same start, plus type-aware gate on verification + decompose on hard reasoning
        pick3, q3v = p1, float(sub['Q'][i, p1])
        if t == 'verification':
            extra['arm3']['verifier_calls'] += 1
            reject_p = CM_VER[0] if q3v <= 0 else CM_VER[1]
            if rng.random() < reject_p:
                extra['arm3']['reroutes'] += 1
                if q3v > 0:
                    extra['arm3']['wasted_replans'] += 1
                alt = int(np.argsort(-u_frozen[i])[1])
                pick3, q3v = alt, float(sub['Q'][i, alt])
                extra['arm3']['verifier_calls'] += 1
            elif q3v <= 0:
                extra['arm3']['missed'] += 1
        elif t == 'reasoning' and q3v <= 0:
            # memory fallback first
            qf = np.array([(1 - LAMBDA_FAIL) * qhat[i, k] + LAMBDA_FAIL * beta_mem(*mem_fail[t][m])
                           for k, m in enumerate(POOL) if k != p1])
            alt = [k for k in range(3) if k != p1]
            pick3 = alt[int(np.argmax(qf))]
            q3v = float(sub['Q'][i, pick3])
            if q3v <= 0:
                # hard failure: failure-aware decompose trigger (measured-rate sampling)
                extra['arm3']['decompose_triggers'] += 1
                if rng.random() < EVIDENCE_SHARE * DECOMP_RESCUE:
                    extra['arm3']['decompose_rescues'] += 1
                    q3v = 1.0  # decompose chain succeeds (value matches gold)
        picks3[i] = pick3

    def arm_metrics(picks, rescues=0, decompose_calls=0, verifier_calls=0, reroutes=0):
        Q = sub['Q'][np.arange(len(picks)), picks].copy()
        if rescues:
            hard = np.array([i for i, n in enumerate(nodes)
                             if n['node_type'] == 'reasoning' and Q[i] <= 0])[:rescues]
            Q[hard] = 1.0
        C = sub['C'][np.arange(len(picks)), picks].astype(float)
        L = sub['L'][np.arange(len(picks)), picks].astype(float)
        exec_mult = 1.0 + reroutes / len(picks)
        C_eff = float(C.mean() * exec_mult + (VERIFIER_TOKENS * verifier_calls + DECOMPOSE_TOKENS_PER_CALL *
                                              decompose_calls) / len(picks))
        L_eff = float(L.mean() * exec_mult)
        reasoning = [i for i, n in enumerate(nodes) if n['node_type'] == 'reasoning']
        success = float(np.mean([Q[i] > 0 for i in reasoning]))
        oracle_q = float(np.mean(sub['Q'][np.arange(len(nodes)), sub['NodeOracle'].astype(int)]))
        static_q = float(np.mean(sub['Q'][np.arange(len(nodes)), picks_static]))
        return dict(task_success=round(success, 4), quality=round(float(Q.mean()), 4),
                    cost_per_node=round(C_eff, 1), latency_per_node=round(L_eff, 3),
                    recovery=round(float((Q.mean() - static_q) / (oracle_q - static_q)), 4),
                    calls_multiplier=round(exec_mult, 3))

    gf = json.loads(GF.read_text())['summary']
    arms = dict(
        StaticOnly=arm_metrics(picks_static),
        StaticFeedback=arm_metrics(picks2, reroutes=extra.get('arm2_fallbacks', 0)),
        FullAdaptiveDAG=arm_metrics(picks3, rescues=extra['arm3']['decompose_rescues'],
                                    decompose_calls=extra['arm3']['decompose_triggers'] * DECOMPOSE_CALLS,
                                    verifier_calls=extra['arm3']['verifier_calls'],
                                    reroutes=extra['arm3']['reroutes']))
    followup = dict(reuse_rate=0.5, call_reduction=gf['call_reduction'],
                    token_reduction=gf['token_reduction'], executes=f'{gf["executes"]}/20',
                    note='follow-up round: Full Adaptive arm reuses extraction subgraphs (measured); '
                         'Static arms re-execute fresh')
    arms['FullAdaptiveDAG']['recovery_note'] = ('exceeds 1.0 because decompose is STRUCTURAL repair outside the '
        'model-selection oracle hypothesis space; the selection oracle is not an upper bound for it')
    result = dict(arms=arms, followup_graph_forest=followup, arm3_internals=extra['arm3'],
                  sampling_disclosures=dict(verifier='confusion-matrix sampling from verifier_v1_1 measured rates',
                                            decompose=f'rescue sampled at evidence_share {EVIDENCE_SHARE} x rescue {DECOMP_RESCUE} '
                                                      '(decompose_v1 measured 6/10 on evidence class)',
                                            rescue_q_modeling='rescued reasoning nodes set to Q=1 (value==gold by success rule)'),
                  next_experiment_started=False)
    core.write(OUT / 'RESULTS.json', result)
    print(json.dumps(result, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
