"""TAT-QA second-domain analysis: Query vs Type Prior vs Node Router.

3-fold CV grouped by task (same protocol as the MultiHiertt ablation). Scoring
identical to the main benchmark: extraction operand recall, reasoning
expression value vs derivation value (1e-4 relative), verification verdict.
"""
import argparse
import hashlib
import json

import numpy as np
from sklearn.linear_model import Ridge

from . import core
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

OUT = core.ROOT / 'static_dag_v0/tatqa_benchmark'
EMB = core.ROOT / 'static_dag_v0/tatqa_benchmark/QUESTION_EMBEDDINGS.npz'
POOL = ['medium', 'large', 'coder']
TYPES = ['extraction', 'reasoning', 'verification']
SEED = 20260916


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def score(n, answer):
    try:
        if n['node_type'] == 'extraction':
            return float(any(close(f['value'], n['gold_operand']) for f in v.parse_facts(answer)['facts']))
        if n['node_type'] == 'reasoning':
            expr = v.decode(answer)['expression']
            return float(close(exec_calc(expr, n['gold_facts']), n['answer']))
        if n['node_type'] == 'verification':
            return float(v.decode(answer)['verdict'] == ('yes' if n['expect_accept'] else 'no'))
    except Exception:
        return 0.0
    return 0.0


def run():
    nodes = json.loads((OUT / 'NODES.json').read_text())
    tasks = {t['uid']: t for t in json.loads((OUT / 'TASKS.json').read_text())}
    Q = np.zeros((len(nodes), 3))
    ids = [n['node_id'] for n in nodes]
    for k, s in enumerate(POOL):
        rows = {r['call_key']: r for r in map(json.loads, (OUT / (s + '_RESPONSES.jsonl')).open())}
        for j, n in enumerate(nodes):
            key = n.get('shares_model_call', n['node_id'])
            r = rows.get(key)
            Q[j, k] = score(n, r['answer']) if r and r['status'] == 'delivered' else 0.0
    if not EMB.exists():
        raise FileNotFoundError('Embed first (r2_venv sentence-transformers)')
    E = np.load(EMB, allow_pickle=False)
    qmap = {q: i for i, q in enumerate(E['questions'].tolist())}
    X = np.hstack([np.array([E['emb'][qmap[n['question']]] for n in nodes]),
                   np.array([[1.0 if n['node_type'] == t else 0.0 for t in TYPES] for n in nodes]),
                   np.log1p(np.array([len(n['question']) for n in nodes])).reshape(-1, 1)])
    folds = np.array([int(hashlib.sha256(f'20260915:{n["task_uid"]}'.encode()).hexdigest()[:8], 16) % 3
                      for n in nodes])
    tasks_l = sorted({n['task_uid'] for n in nodes})
    task_of = np.array([tasks_l.index(n['task_uid']) for n in nodes])
    picks = {a: np.zeros(len(nodes), dtype=int) for a in ['QueryRouter', 'TypePrior', 'NodeRouter']}
    for f in range(3):
        tr, te = folds != f, folds == f
        hq = {m: Ridge(alpha=1.0).fit(X[tr][:, :3584], Q[tr, k]) for k, m in enumerate(POOL)}
        hn = {m: Ridge(alpha=1.0).fit(X[tr], Q[tr, k]) for k, m in enumerate(POOL)}
        best = {}
        for t in TYPES:
            mask = tr & np.array([n['node_type'] == t for n in nodes])
            if mask.any():
                best[t] = int(np.argmax(Q[mask].mean(0)))
        for i in np.flatnonzero(te):
            n = nodes[i]
            picks['QueryRouter'][i] = int(np.argmax([hq[m].predict(X[i:i+1, :3584])[0] for m in POOL]))
            picks['TypePrior'][i] = best.get(n['node_type'], 1)
            picks['NodeRouter'][i] = int(np.argmax([hn[m].predict(X[i:i+1])[0] for m in POOL]))
    def boot_ci(diff):
        rng = np.random.default_rng(SEED)
        per_task = np.array([diff[task_of == t].mean() for t in range(len(tasks_l))])
        idx = rng.integers(0, len(tasks_l), (10000, len(tasks_l)))
        return np.quantile(per_task[idx].mean(1), [.025, .975]).tolist()
    arms = {a: float(Q[np.arange(len(nodes)), p].mean()) for a, p in picks.items()}
    oracle = float(Q.max(1).mean())
    best_fixed = max(POOL, key=lambda m: Q[:, POOL.index(m)].mean())
    ci = {f'NodeRouter_minus_QueryRouter': boot_ci(Q[np.arange(len(nodes)), picks['NodeRouter']] -
                                                   Q[np.arange(len(nodes)), picks['QueryRouter']]),
          f'NodeRouter_minus_TypePrior': boot_ci(Q[np.arange(len(nodes)), picks['NodeRouter']] -
                                                 Q[np.arange(len(nodes)), picks['TypePrior']]),
          f'TypePrior_minus_QueryRouter': boot_ci(Q[np.arange(len(nodes)), picks['TypePrior']] -
                                                  Q[np.arange(len(nodes)), picks['QueryRouter']])}
    by_type = {}
    for t in TYPES:
        mask = np.array([n['node_type'] == t for n in nodes])
        per = {m: round(float(Q[mask, k].mean()), 4) for k, m in enumerate(POOL)}
        by_type[t] = dict(n=int(mask.sum()), per_model=per, oracle=round(float(Q[mask].max(1).mean()), 4),
                          gap=round(float(Q[mask].max(1).mean() - max(per.values())), 4),
                          best=max(per, key=per.get))
    result = dict(arms=arms, oracle=oracle, best_fixed=dict(model=best_fixed,
                Q=float(Q[:, POOL.index(best_fixed)].mean())), ci95=ci, by_type=by_type,
                  gap_analysis=dict(oracle_minus_best_fixed=round(oracle - Q[:, POOL.index(best_fixed)].mean(), 4)))
    core.write(OUT / 'ANALYSIS.json', result)
    print(json.dumps(result, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
