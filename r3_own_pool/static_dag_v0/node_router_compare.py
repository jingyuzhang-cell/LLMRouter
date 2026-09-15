"""5-arm router comparison on the node capability benchmark (zero generation).

Arms: Always Large / Query Router / Static Capability Router / Node Router /
Node Oracle, frozen pool {medium, large, coder} (R1 shadow excluded). 3-fold
CV grouped by task_uid. Node Router features are deployment-observable only:
question GTE embedding + node-type one-hot + log context tokens; gold programs
and answers never enter features. Selection utility uses predicted Q with
train-fold mean cost/latency profiles; realized Q/tokens/latency are measured
from the collected table. Reports paired task-level bootstrap CIs and the
oracle-gap recovery metric.
"""
import argparse
import hashlib
import json

import numpy as np
from sklearn.linear_model import Ridge

from . import core
from . import tool_aware_v1 as v
from .node_gap_audit_full import score

OUT = v.OUT / 'node_benchmark'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
POOL = ['medium', 'large', 'coder']
TYPES = ['extraction', 'transformation', 'reasoning', 'verification']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
SEED = 20260915
N_BOOT = 10000
GTE = '/root/autodl-tmp/models/gte-Qwen2-7B-instruct-fp16'


def encode():
    from sentence_transformers import SentenceTransformer
    nodes = json.loads((OUT / 'NODES.json').read_text())
    questions = sorted({n['question'] for n in nodes})
    model = SentenceTransformer(GTE)
    emb = model.encode(questions, batch_size=8, normalize_embeddings=True,
                       convert_to_numpy=True, show_progress_bar=False)
    np.savez_compressed(OUT / 'QUESTION_EMBEDDINGS.npz', questions=np.array(questions), emb=emb)
    print('embedded', len(questions), 'questions')


def fold_of(uid):
    return int(hashlib.sha256(f'{SEED}:{uid}'.encode()).hexdigest()[:8], 16) % 3


def build_dataset():
    nodes = json.loads((OUT / 'NODES.json').read_text())
    emb_map = {q: e for q, e in zip(*[np.load(OUT / 'QUESTION_EMBEDDINGS.npz')[k] for k in ('questions', 'emb')])}
    rows_by_slot = {s: {} for s in SLOTS}
    for s in SLOTS:
        for r in core.lines(OUT / (s + '_RESPONSES.jsonl')):
            for nid in r['node_ids']:
                rows_by_slot[s][nid] = r
    data = []
    for n in nodes:
        rec = dict(node_id=n['node_id'], task_uid=n['task_uid'], node_type=n['node_type'],
                   question=n['question'], emb=emb_map[n['question']], fold=fold_of(n['task_uid']))
        for s in SLOTS:
            r = rows_by_slot[s].get(n['node_id'])
            ok = r is not None and r['status'] == 'delivered' and r.get('answer')
            rec[f'Q_{s}'] = score(n, r['answer']) if ok else 0.0
            rec[f'C_{s}'] = (r.get('usage') or {}).get('total_tokens') if ok else 0
            rec[f'L_{s}'] = r.get('latency_s') if ok else 0.0
        data.append(rec)
    return data


def utility(Q, C, L):
    return Q - ALPHA_C * C - ALPHA_L * L


def run():
    if (OUT / 'ROUTER_COMPARISON.json').exists():
        raise FileExistsError('Router comparison already exists')
    if not (OUT / 'QUESTION_EMBEDDINGS.npz').exists():
        raise FileNotFoundError('Run encode first')
    data = build_dataset()
    types = np.array([[1.0 if d['node_type'] == t else 0.0 for t in TYPES] for d in data])
    ctx = np.log1p(np.array([len(d['question']) for d in data], dtype=float)).reshape(-1, 1)
    picks = {arm: np.zeros(len(data), dtype=int) for arm in
             ['AlwaysLarge', 'QueryRouter', 'StaticCapability', 'NodeRouter', 'NodeOracle']}
    for fold in range(3):
        tr = np.array([d['fold'] != fold for d in data])
        te = ~tr
        d_tr = [d for d, t in zip(data, tr) if t]
        mean_C = {s: float(np.mean([d[f'C_{s}'] for d in d_tr])) for s in POOL}
        mean_L = {s: float(np.mean([d[f'L_{s}'] for d in d_tr])) for s in POOL}
        profile_u = {s: float(np.mean([d[f'Q_{s}'] for d in d_tr])) - ALPHA_C * mean_C[s] - ALPHA_L * mean_L[s]
                     for s in POOL}
        best_fixed = max(POOL, key=profile_u.get)
        picks['AlwaysLarge'][te] = POOL.index('large')
        picks['StaticCapability'][te] = POOL.index(best_fixed)
        emb = np.array([d['emb'] for d in data])
        f_node = np.hstack([emb, types, ctx])
        f_query = emb
        heads = {}
        for feats, tag in [(f_query, 'query'), (f_node, 'node')]:
            heads[tag] = {s: Ridge(alpha=1.0).fit(feats[tr], np.array([d[f'Q_{s}'] for d in data])[tr]) for s in POOL}
        for i in np.flatnonzero(te):
            qu = {s: heads['query'][s].predict(f_query[i:i + 1])[0] - ALPHA_C * mean_C[s] - ALPHA_L * mean_L[s]
                  for s in POOL}
            picks['QueryRouter'][i] = POOL.index(max(qu, key=qu.get))
            nu = {s: heads['node'][s].predict(f_node[i:i + 1])[0] - ALPHA_C * mean_C[s] - ALPHA_L * mean_L[s]
                  for s in POOL}
            picks['NodeRouter'][i] = POOL.index(max(nu, key=nu.get))
            ou = {si: utility(data[i][f'Q_{s}'], data[i][f'C_{s}'], data[i][f'L_{s}']) for si, s in enumerate(POOL)}
            picks['NodeOracle'][i] = max(ou, key=ou.get)
    realized = {}
    for arm, p in picks.items():
        Q = np.array([d[f'Q_{POOL[m]}'] for d, m in zip(data, p)])
        C = np.array([d[f'C_{POOL[m]}'] for d, m in zip(data, p)], dtype=float)
        L = np.array([d[f'L_{POOL[m]}'] for d, m in zip(data, p)], dtype=float)
        realized[arm] = dict(Q=float(Q.mean()), tokens=float(C.mean()), latency_s=float(L.mean()),
                             utility=float(utility(Q, C, L).mean()), Q_per_node=Q.tolist(),
                             U_per_node=utility(Q, C, L).tolist(),
                             selection_counts={s: int(sum(POOL[pi] == s for pi in p)) for s in POOL})
    tasks = sorted({d['task_uid'] for d in data})
    task_of = np.array([tasks.index(d['task_uid']) for d in data])
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(tasks), (N_BOOT, len(tasks)))
    contrasts = {}
    for a, b in [('NodeRouter', 'QueryRouter'), ('NodeRouter', 'AlwaysLarge'),
                 ('NodeRouter', 'StaticCapability')]:
        for metric in ['U_per_node', 'Q_per_node']:
            diff = np.array(realized[a][metric]) - np.array(realized[b][metric])
            per_task = np.array([diff[task_of == t].mean() for t in range(len(tasks))])
            contrasts[f'{a}_minus_{b}_{metric[0]}'] = dict(
                mean=float(per_task.mean()),
                ci95=np.quantile(per_task[idx].mean(1), [.025, .975]).tolist())
    bf_utility = realized[max(['AlwaysLarge', 'StaticCapability'], key=lambda a: realized[a]['utility'])]['utility']
    recovery = {arm: float((realized[arm]['utility'] - bf_utility) /
                           (realized['NodeOracle']['utility'] - bf_utility))
                for arm in ['AlwaysLarge', 'QueryRouter', 'StaticCapability', 'NodeRouter']}
    by_type = {}
    for t in TYPES:
        mask = np.array([d['node_type'] == t for d in data])
        by_type[t] = {arm: float(np.mean(np.array(realized[arm]['Q_per_node'])[mask])) for arm in realized}
    core.write(OUT / 'ROUTER_COMPARISON.json', dict(
        arms={a: {k: v for k, v in r.items() if not k.endswith('per_node')} for a, r in realized.items()},
        contrasts=contrasts, recovery_vs_best_fixed=recovery, quality_by_type=by_type,
        best_fixed_note='recovery denominator uses the better of AlwaysLarge/StaticCapability',
        gates=dict(gate2='NodeRouter>QueryRouter on utility CI95 lower>0, or equal quality at lower cost',
                   gate3='recovery fraction of oracle utility gap')))
    print(json.dumps(dict(arms={a: {k: round(v, 4) for k, v in r.items() if k in ('Q', 'tokens', 'latency_s', 'utility')}
                                for a, r in realized.items()}, recovery=recovery), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['encode', 'run'])
    args = ap.parse_args()
    encode() if args.stage == 'encode' else run()


if __name__ == '__main__':
    main()
