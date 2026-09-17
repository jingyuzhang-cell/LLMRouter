"""Verifier sensitivity sweep: system gain as a function of detection quality.

Zero generation. Replays the Full-Adaptive policy on the 493-node conditional
table (same machinery as system_verifier_impact / type_aware_gate_ablation),
sweeping the verifier's error-recall over {0.27 (measured), 0.40, 0.60, 0.80,
0.95} with the measured false-alarm rate fixed at 0.20, and separately the
false-alarm rate over {0.05, 0.20, 0.40} at measured recall. Output: the
detection-quality -> system-gain curve for the paper's central finding.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/verifier_sensitivity'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
LAMBDA, LAMBDA_FAIL = 0.3, 0.5
LEN_SPLIT = 150
SEED = 20260915
MEASURED = dict(recall=0.273, fa=0.167)


def run():
    if OUT.exists():
        raise FileExistsError('verifier_sensitivity already exists')
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
    qhat = X @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept']

    def replay(recall, fa):
        rng = np.random.default_rng(SEED)
        picks = np.zeros(len(nodes), dtype=int)
        reroutes = wasted = missed = 0
        for i, n in enumerate(nodes):
            t = n['node_type']
            q1 = qhat[i] - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
            pick = int(np.argmax(q1))
            q_val = float(sub['Q'][i, pick])
            if t in ('reasoning', 'verification'):
                p_reject = recall if q_val <= 0 else fa
                if rng.random() < p_reject:
                    reroutes += 1
                    if q_val > 0:
                        wasted += 1
                    alt = int(np.argsort(-q1)[1])
                    pick, q_val = alt, float(sub['Q'][i, alt])
                elif q_val <= 0:
                    missed += 1
            picks[i] = pick
        Q = sub['Q'][np.arange(len(picks)), picks]
        return float(Q.mean()), reroutes, wasted, missed

    static_q = float(np.mean(sub['Q'][np.arange(len(nodes)), sub['FrozenNodeRouter'].astype(int)]))
    oracle_q = float(sub['Q'].max(1).mean())
    sweep = dict(by_recall={}, by_false_alarm={})
    for r in (0.273, 0.40, 0.60, 0.80, 0.95):
        q, rer, w, m = replay(r, MEASURED['fa'])
        sweep['by_recall'][f'recall={r}'] = dict(Q=round(q, 4), recovery=round((q - static_q) / (oracle_q - static_q), 3),
                                                 reroutes=rer, wasted=w, missed=m)
    for f in (0.05, 0.167, 0.40):
        q, rer, w, m = replay(MEASURED['recall'], f)
        sweep['by_false_alarm'][f'fa={f}'] = dict(Q=round(q, 4), recovery=round((q - static_q) / (oracle_q - static_q), 3),
                                                  reroutes=rer, wasted=w, missed=m)
    core.write(OUT / 'RESULTS.json', dict(sweep=sweep, static_q=round(static_q, 4),
                                          oracle_q=round(oracle_q, 4), measured_point=MEASURED,
                                          policy='feedback-fallback reroute gated by verifier; one fallback; '
                                                 'confusion-matrix replay on the 493-node table'))
    print(json.dumps(sweep, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
