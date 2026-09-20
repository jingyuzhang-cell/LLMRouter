"""Router method development on the 900-question dev corpus (results already seen; this
corpus is DEVELOPMENT ONLY). Methods: TypePrior baseline, CapabilityRouter (absolute Q
ridge), PairwiseRouter (Bradley-Terry style pairwise margins on non-tie samples),
TwoStagePreferenceRouter (default large; switch only with evidence), plus utility and
budget variants. All selection via task-grouped 5-fold CV on the dev corpus. The chosen
policy is frozen to PREFERENCE_POLICY.json for ONE-SHOT evaluation on confirmation-200.

Features are runtime-observable ONLY: GTE question embedding, question/context lengths,
numeric counts, operation-hint keywords, table-size proxy. No gold program/facts."""
import json
import re

import numpy as np

from . import tool_aware_v1 as v
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred, close
from .capability_profiling import norm  # noqa: F401  (protocol symmetry)

DEV = CPROF
SEED = 20260918
FOLDS = 5
ALPHA = 1.0
TYPES = ['extraction', 'reasoning']
KW = ['ratio', 'percent', 'average', 'sum', 'total', 'increase', 'decrease', 'change', 'growth', 'difference']

def sha(x):
    import hashlib
    return hashlib.sha256(x.encode()).hexdigest()

def build_features(corpus, emb_map, dim):
    rows = []
    for r in corpus:
        q = r['question']; ctx = r['task'].get('context', '') if 'task' in r else r.get('context', '')
        f = []
        e = emb_map.get(q)
        f = list(e) if e is not None else [0.0] * dim
        ql = len(q)
        f.append(np.log1p(ql))
        f.append(np.log1p(len(ctx)))
        f.append(np.log1p(len(re.findall(r'\d+(?:\.\d+)?', q))))
        f.append(np.log1p(len(re.findall(r'\d+(?:\.\d+)?', ctx))))
        qlow = q.lower()
        f += [float(k in qlow) for k in KW]
        f.append(np.log1p(ctx.count(chr(10))))  # table-size proxy
        rows.append(f)
    X = np.array(rows, dtype=float)
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    return X

def run():
    corpus = load_corpus()
    # attach context for feature building
    pol = json.loads((DEV / 'PROFILE_POLICY.json').read_text())
    ctx_of = {t['uid']: t['context'] for t in pol['tasks']}
    for r in corpus: r['context'] = ctx_of.get(r['uid'], '')
    embz = np.load(DEV / 'PROFILE_EMB.npz')
    emb_map = {q: embz['emb'][i] for i, q in enumerate(embz['questions'].tolist())}
    dim = embz['emb'].shape[1]
    X = build_features(corpus, emb_map, dim)
    uids = [r['uid'] for r in corpus]
    fold = {u: int(sha(u + ':fold'), 16) % FOLDS for u in uids}
    n = len(corpus)
    Q = {m: np.array([r['per_model'][m]['task_q'] for r in corpus]) for m in POOL}
    C = {m: np.array([r['per_model'][m]['C'] for r in corpus]) for m in POOL}
    # ---- CV: per-fold training of (a) absolute Q ridge, (b) pairwise margins, (c) stage-1/2 preference ----
    qhat = {m: np.zeros(n) for m in POOL}
    pair_score = {m: np.zeros(n) for m in POOL}   # Bradley-Terry: sum of margins vs others
    p_beats_large = {m: np.zeros(n) for m in POOL}  # stage-2: P(m > large)
    p_switch = np.zeros(n)                          # stage-1: P(exists m in {med,coder} beats large)
    for f in range(FOLDS):
        tr = [i for i in range(n) if fold[uids[i]] != f]
        te = [i for i in range(n) if fold[uids[i]] == f]
        # (a) absolute
        for m in POOL:
            w = ridge_fit(X[tr], Q[m][tr]); qhat[m][te] = ridge_pred(w, X[te])
        # (b) pairwise margins on non-tie samples (train), scored on test
        for m in POOL:
            s = np.zeros(len(te))
            for o in POOL:
                if o == m: continue
                d = Q[m] - Q[o]
                ntr = [i for i in tr if d[i] != 0]
                if not ntr: continue
                w = ridge_fit(X[ntr], (d[ntr] > 0).astype(float))
                s += ridge_pred(w, X[te])
            pair_score[m][te] = s
        # (c) preference stage 1/2 vs large
        for m in ['medium', 'coder']:
            d = (Q[m] > Q['large']).astype(float)
            diff = Q[m] - Q['large']
            ntr = [i for i in tr if diff[i] != 0]
            w = ridge_fit(X[ntr], d[ntr]) if ntr else None
            p_beats_large[m][te] = ridge_pred(w, X[te]) if w is not None else 0.0
        sw = ((Q['medium'] > Q['large']) | (Q['coder'] > Q['large'])).astype(float)
        w = ridge_fit(X[tr], sw[tr])
        p_switch[te] = ridge_pred(w, X[te])
    # ---- policies as functions of per-question scores ----
    def sel_typeprior(i):
        return 'large'
    def sel_capability(i, lam=0.0, mu=0.0):
        if lam == 0 and mu == 0:
            return max(POOL, key=lambda m: qhat[m][i])
        return max(POOL, key=lambda m: qhat[m][i] - lam * C[m][i] / 1000.0 - mu * 0.0)
    def sel_pairwise(i):
        return max(POOL, key=lambda m: pair_score[m][i])
    def sel_twostage(i, tau):
        if p_switch[i] > tau:
            m2 = max(['medium', 'coder'], key=lambda m: p_beats_large[m][i])
            if p_beats_large[m2][i] > 0.5: return m2
        return 'large'
    def sel_utility(i, lam, mu):
        Lp = {m: C[m][i] for m in POOL}
        return max(POOL, key=lambda m: pair_score[m][i] - lam * Lp[m] / 1000.0)
    # ---- dev-CV evaluation with the frozen metric suite ----
    best_single = max(POOL, key=lambda m: Q[m].mean())
    oracle = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
    gap = oracle.mean() - Q[best_single].mean()
    def evaluate(name, sel):
        picks = [sel(i) for i in range(n)]
        qsel = np.array([Q[picks[i]][i] for i in range(n)])
        should_switch = np.array([(Q['medium'][i] > Q['large'][i]) or (Q['coder'][i] > Q['large'][i]) for i in range(n)])
        did_switch = np.array([picks[i] != 'large' for i in range(n)])
        switch_benefit = int(((did_switch) & (qsel > Q['large'])).sum())
        harm = int(((did_switch) & (qsel < Q['large'])).sum())
        head = [i for i in range(n) if len({Q[m][i] for m in POOL}) > 1]
        head_top1 = float(np.mean([Q[picks[i]][i] == max(Q[m][i] for m in POOL) for i in head])) if head else None
        return dict(
            Q=round(float(qsel.mean()), 4),
            GAP_recovery=round(float((qsel.mean() - Q[best_single].mean()) / gap), 4) if gap > 0 else None,
            headroom_n=len(head), headroom_top1=round(head_top1, 4) if head_top1 is not None else None,
            switch_precision=round(switch_benefit / max(1, int(did_switch.sum())), 4),
            switch_recall=round(int((did_switch & should_switch).sum()) / max(1, int(should_switch.sum())), 4),
            harm_rate=round(harm / n, 4),
            switches=int(did_switch.sum()))
    results = {}
    results['TypePrior'] = evaluate('TypePrior', sel_typeprior)
    results['CapabilityRouter'] = evaluate('CapabilityRouter', sel_capability)
    results['PairwiseRouter'] = evaluate('PairwiseRouter', sel_pairwise)
    for tau in [0.3, 0.4, 0.5, 0.6]:
        results[f'TwoStage_tau{tau}'] = evaluate(f'TwoStage_tau{tau}', lambda i, t=tau: sel_twostage(i, t))
    for lam, mu in [(0.05, 0.05), (0.1, 0.1)]:
        results[f'Utility_lam{lam}'] = evaluate(f'Utility_lam{lam}', lambda i, l=lam: sel_utility(i, l, l))
    # selection rule (frozen): highest CV GAP_recovery with harm_rate <= 0.01 and switches>0; else TypePrior
    cands = {k: v for k, v in results.items() if k != 'TypePrior' and v['harm_rate'] <= 0.01 and v['switches'] > 0}
    chosen = max(cands, key=lambda k: results[k]['GAP_recovery']) if cands else 'TypePrior'
    if results[chosen]['GAP_recovery'] <= results['TypePrior']['GAP_recovery']: chosen = 'TypePrior'
    policy = dict(chosen=chosen, dev_results=results, best_single=best_single,
                  oracle_gap=round(float(gap), 4),
                  tau=None if 'tau' not in chosen else float(chosen.split('tau')[1]),
                  feature_set='GTE emb + lengths + numeric counts + op keywords + newline proxy (runtime-observable only)',
                  dev_only='all numbers are grouped-CV on the 900-question DEV corpus; one-shot on confirmation-200 pending')
    (DEV / 'PREFERENCE_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    print(json.dumps(policy, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
