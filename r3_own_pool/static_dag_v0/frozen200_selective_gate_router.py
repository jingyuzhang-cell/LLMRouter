"""P0-1b: selective gate with ROUTER-RISK features (encoder-only, zero LLM calls).

The lexical-only arm (frozen200_selective_gate.py) found no signal (AUROC~0.5).
Before concluding 'undiagnosable', test the strongest deployable feature class:
the frozen dev router's predicted node-level Q for the frozen200 assignment
(e1/e2=large, r=medium, v=coder), computed from the frozen GTE encoder +
DEV_MODELS weights — exactly the signals available at decision time in
deployment (first paper showed they carry node-level signal).

Same protocol as the lexical arm: GroupKFold(5) by task, tau chosen on train
folds, exact per-seed test outcomes.
"""
import json
from pathlib import Path

import numpy as np

from .frozen200_selective_gate import (SEEDS, TAUS, _folds, features, gate_q,
                                       make_models, rates)

F200 = Path('/root/r3_own_pool/static_dag_v0/frozen200')
OUT = F200.parent / 'frozen200_selective_gate'
POOL = ['medium', 'large', 'coder']
TYPES = ['extraction', 'transformation', 'reasoning', 'verification']
ASSIGN = {'extraction': 'large', 'reasoning': 'medium', 'verification': 'coder'}


def router_features():
    pol = json.loads((F200 / 'FROZEN200_POLICY.json').read_text())
    emb = np.load(OUT / 'QUESTION_EMBEDDINGS.npz')['emb']
    dev = np.load(F200.parent / 'fresh_static_confirmation/DEV_MODELS.npz')
    rows = []
    for t, xq in zip(pol['tasks'], emb):
        xq = np.asarray(xq)
        qr = dev['QueryRouter_coef'] @ xq + dev['QueryRouter_intercept']  # Q̂ per model
        xg = np.log1p(len(t['question']))
        node_q = {}
        for ty in TYPES:
            x = np.concatenate([xq, [1.0 * (ty == k) for k in TYPES], [xg]])
            node_q[ty] = dev['NodeRouter_coef'] @ x + dev['NodeRouter_intercept']
        vals = [node_q[ty][POOL.index(m)] for ty, m in ASSIGN.items()]
        rows.append([qr.mean(), qr[POOL.index('medium')], qr[POOL.index('large')],
                     qr[POOL.index('coder')], qr.std()] + vals +
                    [float(np.mean(vals)), float(np.std(vals)),
                     float(node_q['extraction'][POOL.index('medium')]),
                     float(node_q['reasoning'][POOL.index('large')])])
    return np.array(rows, dtype=float)


def run():
    pol = json.loads((F200 / 'FROZEN200_POLICY.json').read_text())
    res = json.loads((F200 / 'FROZEN200_RESULTS.json').read_text())['results']
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    X_lex = np.array([features(t) for t in tasks], dtype=float)
    X_rt = router_features()
    S = np.array([[res[f'f30_s{s}|single'][u]['ok'] for s in SEEDS] for u in uids], float)
    D = np.array([[res[f'f30_s{s}|dynamic'][u]['ok'] for s in SEEDS] for u in uids], float)
    U = D - S
    n = len(tasks)
    from sklearn.metrics import roc_auc_score
    out = {}
    for feat_name, X in [('router_only', X_rt), ('lexical+router', np.hstack([X_lex, X_rt]))]:
        Xs = np.repeat(X, len(SEEDS), 0)
        ys = (U > 0).T.reshape(-1).astype(int)
        keep = (U != 0).T.reshape(-1)
        grp = np.repeat(np.arange(n), len(SEEDS))
        for name in ['logistic', 'hist_gb', 'calibrated_gb']:
            fold_q, fold_auroc, fold_rates = [], [], []
            for tr_t, te_t in _folds(n):
                tr_s = np.isin(grp, tr_t) & keep
                te_s = np.isin(grp, te_t) & keep
                model = make_models()[name]
                model.fit(Xs[tr_s], ys[tr_s])
                p_tr = model.predict_proba(X[tr_t])[:, 1]
                p_te = model.predict_proba(X[te_t])[:, 1]
                best_tau, best_q = 0.5, -1
                for tau in TAUS:
                    q = gate_q(p_tr, tau, S[tr_t], D[tr_t])
                    if q > best_q:
                        best_q, best_tau = q, tau
                fold_q.append(gate_q(p_te, best_tau, S[te_t], D[te_t]))
                fold_rates.append(rates(p_te, best_tau, S[te_t], D[te_t]))
                if len(set(ys[te_s])) == 2:
                    fold_auroc.append(roc_auc_score(ys[te_s], model.predict_proba(Xs[te_s])[:, 1]))
            key = f'{feat_name}|{name}'
            out[key] = dict(q_mean=float(np.mean(fold_q)), q_std=float(np.std(fold_q)),
                            auroc_mean=float(np.mean(fold_auroc)) if fold_auroc else None,
                            rates_mean={k: float(np.nanmean([r[k] for r in fold_rates]))
                                        for k in ['help_capture', 'harm_avoidance',
                                                  'intervention_rate']})
    oracle = float(np.maximum(S, D).mean())
    result = dict(features='router risk: QueryRouter Qhat(mean/per-model/std) + '
                            'NodeRouter Qhat at frozen assignment (e=large,r=medium,v=coder) '
                            '+ node min/std/cross-checks; encoder-only, zero LLM calls',
                  baselines=dict(always_single=float(S.mean()), always_dynamic=float(D.mean()),
                                 oracle_selective=oracle),
                  models=out,
                  regret_oracle={k: oracle - v['q_mean'] for k, v in out.items()})
    (OUT / 'RESULTS_ROUTER.json').write_text(json.dumps(result, indent=1))
    print(json.dumps(dict(models={k: dict(q=round(v['q_mean'], 4),
                                           auroc=round(v['auroc_mean'], 3) if v['auroc_mean'] else None,
                                           rates={kk: round(vv, 3) for kk, vv in v['rates_mean'].items()})
                                  for k, v in out.items()},
                          regret_oracle={k: round(v, 4) for k, v in result['regret_oracle'].items()}), indent=1))


if __name__ == '__main__':
    run()
