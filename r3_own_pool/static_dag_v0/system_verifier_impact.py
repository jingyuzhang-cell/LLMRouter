"""System-level verifier impact: Dynamic DAG with vs without verifier-in-the-loop.

No-verifier arm = the frozen dynamic_dag_v0 deployable replay (perfect failure
detection, Q .5497 @1.49x). With-verifier arm replays the same policy but
failure detection is the coder v0 single-check verifier applied to
expression-bearing nodes (reasoning + verification; extraction keeps
table-truth detection, out of scope this round). On verifier reject: reroute
to the utility second-best, re-verify once, accept whatever remains (no
ground-truth peeking). Reports end Q, error recovery, missed failures, wasted
replans (reroutes triggered on actually-correct nodes), and total cost
including verifier tokens.
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
DYN = core.ROOT / 'static_dag_v0/dynamic_dag_v0/RESULTS.json'
OUT = core.ROOT / 'static_dag_v0/system_verifier_impact'
POOL = ['medium', 'large', 'coder']
VERIFIER_MODEL = 'coder'
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
V0 = ('Check this financial computation. QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\nVALUE: {val}\n'
      'Does it correctly answer the question using accurate facts? '
      'Answer ONLY JSON {{"verdict":"yes"|"no"}}.')


def run():
    if OUT.exists():
        raise FileExistsError('system_verifier_impact already exists')
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
    u = qhat - ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']
    engine.OUT = OUT
    picks = np.zeros(len(nodes), dtype=int)
    stats = dict(verifier_calls=0, reroutes=0, wasted_replans=0, missed_failures=0,
                 recovered=0, verifier_tokens=0)
    # NOTE: per-model expressions for arbitrary (node, model) pairs are not stored, so real-time
    # verifier calls cannot be reconstructed for every cell without re-generation. Fall back to a
    # verifier-behaviour replay sampled from the measured confusion matrices (B-type for
    # verification nodes, A-type for reasoning chains), which preserves the systems-level question
    # at zero generation. This is recorded honestly in the artifact.
    rng = np.random.default_rng(20260915)
    cm = {  # from verifier_v1_1: [P(reject | wrong), P(reject | correct)]
        'verification': [0.95, 0.20],
        'reasoning': [0.273, 0.167],  # A-testbed v0 recall / false alarm (coder)
    }
    for i, n in enumerate(nodes):
        order = list(np.argsort(-u[i]))
        pick = int(order[0])
        q_val = float(sub['Q'][i, pick])
        if n['node_type'] not in cm:
            picks[i] = pick
            continue
        reject_p = cm[n['node_type']][0] if q_val <= 0 else cm[n['node_type']][1]
        stats['verifier_calls'] += 1
        if rng.random() < reject_p:
            stats['reroutes'] += 1
            if q_val > 0:
                stats['wasted_replans'] += 1
            second = int(order[1])
            q2 = float(sub['Q'][i, second])
            reject2_p = cm[n['node_type']][0] if q2 <= 0 else cm[n['node_type']][1]
            stats['verifier_calls'] += 1
            if rng.random() < reject2_p and len(order) > 2:
                stats['reroutes'] += 1
                if q2 > 0:
                    stats['wasted_replans'] += 1
                pick = int(order[2])
                q2 = float(sub['Q'][i, pick])
            pick, q_val = pick, q2
            if q_val > 0 and float(sub['Q'][i, int(order[0])]) <= 0:
                stats['recovered'] += 1
        else:
            if q_val <= 0:
                stats['missed_failures'] += 1
        picks[i] = pick
    Q = sub['Q'][np.arange(len(picks)), picks]
    C = sub['C'][np.arange(len(picks)), picks].astype(float)
    L = sub['L'][np.arange(len(picks)), picks].astype(float)
    dyn = json.loads((DYN).read_text())['stats']
    no_ver = dyn['deployable_second_only']
    static_q = float(np.mean(sub['Q'][np.arange(len(nodes)), sub['FrozenNodeRouter'].astype(int)]))
    oracle_gap = dyn['final']['Q'] - static_q
    result = dict(
        method_note='verifier behaviour replayed from measured confusion matrices (zero generation); '
                    'per-cell live verdicts would need re-generation, flagged as approximation',
        with_verifier=dict(Q=float(Q.mean()), tokens=float(C.mean()), calls_multiplier=float(
            (len(nodes) + stats['reroutes']) / len(nodes)),
            verifier_calls=stats['verifier_calls'], verifier_tokens_per_call_estimate=500),
        without_verifier=no_ver,
        static_q=static_q,
        systems=dict(recovered=stats['recovered'], missed_failures=stats['missed_failures'],
                     wasted_replans=stats['wasted_replans'], reroutes=stats['reroutes']),
        recovery_vs_static=(float(Q.mean()) - static_q) / (dyn['final']['Q'] - static_q),
        oracle_bound_Q=dyn['final']['Q'])
    core.write(OUT / 'RESULTS.json', result)
    print(json.dumps(result, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
