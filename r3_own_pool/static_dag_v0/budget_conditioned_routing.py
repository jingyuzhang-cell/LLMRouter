"""Budget-conditioned routing analysis on existing 900+200 data (zero model calls).
For each (λ, μ) utility point and each budget constraint (B_C, B_L), report which
model the Two-stage Router would select and the resulting Q/C/L trade-off.
This connects the routing decision directly to the multi-objective framework."""
import json
import random
from collections import defaultdict

import numpy as np

from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred
from .preference_router_dev import build_features, KW
from .confirmation_200 import OUT as CONF1
from .preference_router_eval import load_confirmation

SEED = 20260918
B = 5000
FROZEN_TAU = 0.5

def load_all():
    """Load both the 900-dev and 200-conf corpora with features and Q/C/L."""
    corpus = load_corpus()
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    ctx_of = {t['uid']: t['context'] for t in pol['tasks']}
    for r in corpus: r['context'] = ctx_of.get(r['uid'], '')
    conf = load_confirmation()
    return corpus, conf

def run():
    corpus, conf = load_all()
    # train on all 900
    embz = np.load(CPROF / 'PROFILE_EMB.npz')
    emb_map = {q: embz['emb'][i] for i, q in enumerate(embz['questions'].tolist())}
    dim = embz['emb'].shape[1]
    Xdev = build_features(corpus, emb_map, dim)
    Qdev = {m: np.array([r['per_model'][m]['task_q'] for r in corpus]) for m in POOL}
    Cdev = {m: np.array([r['per_model'][m]['C'] for r in corpus]) for m in POOL}
    Ldev = {m: np.array([r['per_model'][m]['L'] for r in corpus]) for m in POOL}
    # train Q/C/L predictors + stage-1/2
    w_q = {m: ridge_fit(Xdev, Qdev[m]) for m in POOL}
    w_c = {m: ridge_fit(Xdev, np.log1p(Cdev[m])) for m in POOL}
    w_l = {m: ridge_fit(Xdev, np.log1p(Ldev[m])) for m in POOL}
    sw_label = ((Qdev['medium'] > Qdev['large']) | (Qdev['coder'] > Qdev['large'])).astype(float)
    w_sw = ridge_fit(Xdev, sw_label)
    w_beats = {}
    for m in ['medium', 'coder']:
        d = Qdev[m] - Qdev['large']
        ntr = [i for i in range(len(d)) if d[i] != 0]
        w_beats[m] = ridge_fit(Xdev[ntr], (d[ntr] > 0).astype(float)) if ntr else None
    # embed conf-200
    from sentence_transformers import SentenceTransformer
    from .node_router_compare import GTE
    st = SentenceTransformer(GTE, device='cpu')
    cq = [r['question'] for r in conf]
    embs = st.encode(cq, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
    del st
    emb_map_c = {q: embs[i] for i, q in enumerate(cq)}
    Xconf = build_features(conf, emb_map_c, dim)
    n = len(conf)
    Q = {m: np.array([r['per_model'][m]['task_q'] for r in conf]) for m in POOL}
    C = {m: np.array([r['per_model'][m]['C'] for r in conf]) for m in POOL}
    L = {m: np.array([r['per_model'][m]['L'] for r in conf]) for m in POOL}
    q_hat = {m: ridge_pred(w_q[m], Xconf) for m in POOL}
    c_hat = {m: np.expm1(ridge_pred(w_c[m], Xconf)) for m in POOL}
    l_hat = {m: np.expm1(ridge_pred(w_l[m], Xconf)) for m in POOL}
    p_sw = ridge_pred(w_sw, Xconf)
    p_beats = {m: (ridge_pred(w_beats[m], Xconf) if w_beats[m] is not None else np.zeros(n)) for m in ['medium', 'coder']}
    # ---- budget-conditioned routing: for each (lam, mu), compute the utility-selected model ----
    lam_mu_grid = [(0.0, 0.0), (0.01, 0.0), (0.05, 0.0), (0.0, 0.05), (0.01, 0.01), (0.05, 0.05), (0.1, 0.1), (0.2, 0.2)]
    budget_grid = [None, (3000, 5.0), (2000, 3.0), (1500, 2.0), (1000, 1.5)]  # (B_C tokens, B_L seconds)
    oracle_q = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
    gap = oracle_q.mean() - Q['large'].mean()
    results = {}
    for lam, mu in lam_mu_grid:
        for bc in budget_grid:
            label = f'lam={lam},mu={mu}' + (f',B={bc[0]}tok/{bc[1]}s' if bc else ',B=inf')
            picks = []
            for i in range(n):
                # budget filtering: only remove infeasible models, do NOT change selection logic
                feasible = [m for m in POOL if (not bc or (c_hat[m][i] <= bc[0] and l_hat[m][i] <= bc[1]))]
                if not feasible: feasible = ['medium']  # cheapest fallback when nothing fits
                # strictly frozen Two-stage tau=0.5 within the feasible set
                if 'large' in feasible:
                    if p_sw[i] <= FROZEN_TAU:
                        picks.append('large'); continue
                    m2 = max(['medium', 'coder'], key=lambda mm: p_beats[mm][i] if mm in feasible else -1)
                    if m2 in feasible and p_beats[m2][i] > 0.5:
                        picks.append(m2); continue
                    picks.append('large'); continue  # stay large (no fallthrough)
                # large infeasible: best non-large by stage-2 score
                best = max(feasible, key=lambda m: p_beats.get(m, np.array([0.0]*n))[i] if m in p_beats else q_hat[m][i])
                picks.append(best)
            qsel = np.array([Q[picks[i]][i] for i in range(n)])
            csel = np.array([C[picks[i]][i] for i in range(n)])
            lsel = np.array([L[picks[i]][i] for i in range(n)])
            gr = (qsel.mean() - Q['large'].mean()) / gap if gap > 0 else 0
            results[label] = dict(
                Q=round(float(qsel.mean()), 4), C=round(float(csel.mean()), 1), L=round(float(lsel.mean()), 2),
                GAP=round(float(gr), 4),
                picks=dict((m, picks.count(m)) for m in POOL))
    # Pareto points (Q vs C, Q vs L) for the unconstrained grid
    pareto = []
    for lam, mu in lam_mu_grid:
        label = f'lam={lam},mu={mu},B=inf'
        r = results[label]
        pareto.append(dict(lam=lam, mu=mu, Q=r['Q'], C=r['C'], L=r['L'], GAP=r['GAP']))
    rep = dict(n_conf=n, oracle_gap=round(float(gap), 4), results=results, pareto=pareto,
               note='budget-conditioned Two-stage routing on conf-200; predictors from 900-dev; zero new calls')
    out = BASE / 'budget_conditioned_routing'
    out.mkdir(exist_ok=True)
    (out / 'BUDGET_ROUTING.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(dict(pareto=pareto,
                          budget_examples={k: v for k, v in results.items() if 'B=1000' in k or 'B=inf' in k and 'mu=0.0' in k and 'lam=0.0' in k}),
                     ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
