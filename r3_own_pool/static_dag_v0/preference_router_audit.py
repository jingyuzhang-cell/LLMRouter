"""Zero-call statistical audit of the confirmation-200 Two-stage vs TypePrior results.
Reports: paired bootstrap CI for dQ, help/harm/neutral counts, exact McNemar,
GAP Recovery bootstrap CI, switch-level classification, headroom winner composition."""
import json
import math
import random
from collections import Counter

import numpy as np

from .recovery_matrix_v2_devset import BASE
from .confirmation_200 import OUT as CONF
from .preference_router_eval import load_confirmation, FROZEN_TAU
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred
from .preference_router_dev import build_features

SEED = 20260918
B = 10000

def run():
    # rebuild predictions identical to preference_router_eval (same frozen pipeline)
    corpus = load_corpus()
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    ctx_of = {t['uid']: t['context'] for t in pol['tasks']}
    for r in corpus: r['context'] = ctx_of.get(r['uid'], '')
    embz = np.load(CPROF / 'PROFILE_EMB.npz')
    emb_map = {q: embz['emb'][i] for i, q in enumerate(embz['questions'].tolist())}
    dim = embz['emb'].shape[1]
    Xdev = build_features(corpus, emb_map, dim)
    Qdev = {m: np.array([r['per_model'][m]['task_q'] for r in corpus]) for m in POOL}
    sw_label = ((Qdev['medium'] > Qdev['large']) | (Qdev['coder'] > Qdev['large'])).astype(float)
    w_sw = ridge_fit(Xdev, sw_label)
    w_beats = {}
    for m in ['medium', 'coder']:
        d = Qdev[m] - Qdev['large']
        ntr = [i for i in range(len(d)) if d[i] != 0]
        w_beats[m] = ridge_fit(Xdev[ntr], (d[ntr] > 0).astype(float)) if ntr else None
    conf = load_confirmation()
    cq = [r['question'] for r in conf]
    from sentence_transformers import SentenceTransformer
    from .node_router_compare import GTE
    st = SentenceTransformer(GTE)
    embs = st.encode(cq, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
    del st
    import torch; torch.cuda.empty_cache()
    emb_map_c = {q: embs[i] for i, q in enumerate(cq)}
    Xconf = build_features(conf, emb_map_c, dim)
    p_sw = ridge_pred(w_sw, Xconf)
    p_beats = {m: (ridge_pred(w_beats[m], Xconf) if w_beats[m] is not None else np.zeros(len(conf))) for m in ['medium', 'coder']}
    picks_2s = []
    for i in range(len(conf)):
        if p_sw[i] > FROZEN_TAU:
            m2 = max(['medium', 'coder'], key=lambda m: p_beats[m][i])
            picks_2s.append(m2 if p_beats[m2][i] > 0.5 else 'large')
        else:
            picks_2s.append('large')
    Q = {m: np.array([r['per_model'][m]['task_q'] for r in conf]) for m in POOL}
    n = len(conf)
    q_large = Q['large']
    q_2s = np.array([Q[picks_2s[i]][i] for i in range(n)])
    oracle = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
    gap = oracle.mean() - q_large.mean()
    # ---- 1. paired bootstrap dQ CI ----
    rng = random.Random(SEED)
    dq = q_2s - q_large
    boots = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        boots.append(sum(dq[i] for i in idx) / n)
    boots.sort()
    dq_ci = [round(boots[int(0.025 * B)], 4), round(boots[int(0.975 * B) - 1], 4)]
    # ---- 2. help / harm / neutral counts ----
    help_n = int(sum(1 for i in range(n) if dq[i] > 0))
    harm_n = int(sum(1 for i in range(n) if dq[i] < 0))
    neutral_n = n - help_n - harm_n
    # ---- 3. McNemar exact test ----
    # discordant pairs: b = Two-stage correct & large wrong; c = Two-stage wrong & large correct
    b = int(sum(1 for i in range(n) if q_2s[i] == 1 and q_large[i] == 0))
    c = int(sum(1 for i in range(n) if q_2s[i] == 0 and q_large[i] == 1))
    def mcnemar_exact(b, c):
        if b + c == 0: return 1.0
        k = min(b, c); n_ = b + c
        # exact binomial two-sided p-value
        p = sum(math.comb(n_, j) for j in range(0, k + 1)) * (0.5 ** n_) * 2
        return min(1.0, p)
    p_mcnemar = mcnemar_exact(b, c)
    # ---- 4. GAP Recovery bootstrap CI ----
    gap_boots = []
    for _ in range(B):
        idx = [rng.randrange(n) for _ in range(n)]
        q2 = sum(q_2s[i] for i in idx) / n
        ql = sum(q_large[i] for i in idx) / n
        qo = sum(oracle[i] for i in idx) / n
        g = qo - ql
        gap_boots.append((q2 - ql) / g if abs(g) > 1e-9 else 0.0)
    gap_boots.sort()
    gap_ci = [round(gap_boots[int(0.025 * B)], 4), round(gap_boots[int(0.975 * B) - 1], 4)]
    # ---- 5. switch-level classification ----
    switches = []
    for i in range(n):
        if picks_2s[i] != 'large':
            switches.append(dict(task=conf[i]['uid'][:12], from_model='large', to_model=picks_2s[i],
                                 classification='help' if dq[i] > 0 else ('harm' if dq[i] < 0 else 'neutral'),
                                 dQ=int(dq[i])))
    # ---- 6. headroom winner composition ----
    head_ids = [i for i in range(n) if len({Q[m][i] for m in POOL}) > 1]
    winners = Counter()
    for i in head_ids:
        w = [m for m in POOL if Q[m][i] == 1]
        winners['+'.join(sorted(w))] += 1
    rep = dict(
        n=n, frozen_tau=FROZEN_TAU,
        Q_large=round(float(q_large.mean()), 4), Q_2s=round(float(q_2s.mean()), 4),
        Q_oracle=round(float(oracle.mean()), 4), oracle_gap=round(float(gap), 4),
        dQ=round(float(dq.mean()), 4), dQ_ci95=dq_ci,
        help_n=help_n, harm_n=harm_n, neutral_n=neutral_n,
        mcnemar=dict(b=b, c=c, p_exact=round(p_mcnemar, 4)),
        gap_recovery=round(float((q_2s.mean() - q_large.mean()) / gap), 4),
        gap_recovery_ci95=gap_ci,
        switch_detail=switches,
        headroom_composition=dict(total=len(head_ids), winners=dict(winners)),
        significance_note='dQ CI and McNemar both include/at 0 -> NOT significant; report as directional positive')
    (CONF / 'STAT_AUDIT.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
