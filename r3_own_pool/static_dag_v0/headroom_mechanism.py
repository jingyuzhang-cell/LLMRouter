"""Part 2: Headroom mechanism analysis (post-hoc, exploratory, zero model calls).
Answers: why is the residual GAP hard to learn from currently observable features?

Splits headroom tasks into S_L (large unique winner) vs S_NL (non-large exclusive winner:
medium-only + coder-only + coder+medium). Compares runtime-observable feature distributions
with median/IQR, standardized mean difference (SMD), and univariate diagnostic separability
AUC(S_L, S_NL). Also classifies all switches across conf-500 into help/harm/neutral and
compares their router signals to explain why conf-200 was 2/0 but conf-500 was 1/4."""
import json
import math
import random

import numpy as np

from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred, close
from .preference_router_dev import build_features, KW
from .confirmation_500 import OUT as CONF
from .conf500_eval import load_conf500, FROZEN_TAU

SEED = 20260918

def median_iqr(xs):
    if not xs: return None, None
    xs = sorted(xs); n = len(xs)
    med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    q1 = xs[n // 4] if n >= 4 else xs[0]
    q3 = xs[3 * n // 4] if n >= 4 else xs[-1]
    return round(med, 3), (round(q1, 3), round(q3, 3))

def smd(a, b):
    if len(a) < 2 or len(b) < 2: return None
    ma, mb = np.mean(a), np.mean(b)
    sa, sb = np.std(a, ddof=1), np.std(b, ddof=1)
    pooled = math.sqrt((sa ** 2 + sb ** 2) / 2)
    return round(float((ma - mb) / pooled), 3) if pooled > 1e-9 else 0.0

def auc_diag(pos, neg):
    """Univariate diagnostic separability AUC(pos, neg)."""
    if len(pos) < 2 or len(neg) < 2 or len(set(pos)) < 2: return None
    c = 0; t = 0
    for p in pos:
        for n in neg:
            t += 1
            if p > n: c += 1
            elif p == n: c += 0.5
    return round(c / t, 3) if t > 0 else None

def run():
    conf = load_conf500()
    n = len(conf)
    Q = {m: np.array([r['per_model'][m]['task_q'] for r in conf]) for m in POOL}
    # headroom split
    SL, SNL, ST = [], [], []
    for i, r in enumerate(conf):
        vals = {m: Q[m][i] for m in POOL}
        winners = [m for m in POOL if vals[m] == 1]
        if len(winners) == len(POOL) or len(winners) == 0: continue
        if winners == ['large']:
            SL.append(i)
        elif 'large' not in winners:
            SNL.append(i)
        else:
            ST.append(i)  # large + at least one other
    # extract runtime-observable features per task
    import re
    def feat_vec(r):
        q = r['question']; ctx = r.get('context', '')
        nums_q = re.findall(r'\d+(?:\.\d+)?', q)
        nums_c = re.findall(r'\d+(?:\.\d+)?', ctx)
        qlow = q.lower()
        return dict(
            ctx_len=len(ctx), q_len=len(q),
            n_nums_q=len(nums_q), n_nums_c=len(nums_c),
            num_density_c=len(nums_c) / max(1, len(ctx)) * 1000,
            kw_ratio=int('ratio' in qlow or 'percentage' in qlow),
            kw_avg=int('average' in qlow or 'mean' in qlow),
            kw_change=int('increase' in qlow or 'decrease' in qlow or 'change' in qlow or 'growth' in qlow),
            n_lines=ctx.count('\n'), n_pipes=ctx.count('|'),
            q_num_ratio=len(nums_q) / max(1, len(q.split())),
        )
    feats_SL = [feat_vec(conf[i]) for i in SL]
    feats_SNL = [feat_vec(conf[i]) for i in SNL]
    feat_names = list(feats_SL[0].keys()) if feats_SL else []
    # per-feature comparison
    comparison = {}
    for fn in feat_names:
        a = [f[fn] for f in feats_SNL]  # non-large winners (what we want to find)
        b = [f[fn] for f in feats_SL]   # large winners (what we want to avoid switching from)
        comparison[fn] = dict(
            SNL_median_iqr=median_iqr(a), SL_median_iqr=median_iqr(b),
            SMD_SNL_minus_SL=smd(a, b),
            diagnostic_AUC=auc_diag(a, b))
    # also compute router signals (p_sw, p_beats) for SL vs SNL
    # rebuild predictions (same frozen pipeline)
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
        ntr = [j for j in range(len(d)) if d[j] != 0]
        w_beats[m] = ridge_fit(Xdev[ntr], (d[ntr] > 0).astype(float)) if ntr else None
    from sentence_transformers import SentenceTransformer
    from .node_router_compare import GTE
    st = SentenceTransformer(GTE, device='cpu')
    cq = [r['question'] for r in conf]
    embs = st.encode(cq, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
    del st
    emb_map_c = {q: embs[i] for i, q in enumerate(cq)}
    Xconf = build_features(conf, emb_map_c, dim)
    p_sw = ridge_pred(w_sw, Xconf)
    p_beats = {m: (ridge_pred(w_beats[m], Xconf) if w_beats[m] is not None else np.zeros(n)) for m in ['medium', 'coder']}
    # router signal comparison
    for name, vals in [('p_switch', p_sw), ('p_beats_medium', p_beats['medium']), ('p_beats_coder', p_beats['coder'])]:
        a = [float(vals[i]) for i in SNL]
        b = [float(vals[i]) for i in SL]
        comparison[name] = dict(SNL_median_iqr=median_iqr(a), SL_median_iqr=median_iqr(b),
                                SMD_SNL_minus_SL=smd(a, b), diagnostic_AUC=auc_diag(a, b))
    # switch classification analysis
    picks = []
    for i in range(n):
        if p_sw[i] > FROZEN_TAU:
            m2 = max(['medium', 'coder'], key=lambda m: p_beats[m][i])
            picks.append(m2 if p_beats[m2][i] > 0.5 else 'large')
        else:
            picks.append('large')
    q_large = Q['large']
    q_2s = np.array([Q[picks[i]][i] for i in range(n)])
    switch_rows = []
    for i in range(n):
        if picks[i] != 'large':
            dq = int(q_2s[i] - q_large[i])
            cls = 'help' if dq > 0 else ('harm' if dq < 0 else 'neutral')
            switch_rows.append(dict(
                cls=cls, to=picks[i], dQ=dq,
                p_sw=round(float(p_sw[i]), 3),
                p_target=round(float(p_beats[picks[i]][i]), 3),
                ctx_len=len(conf[i].get('context', '')),
                q_len=len(conf[i]['question']),
                n_nums_q=feat_vec(conf[i])['n_nums_q'],
                actual_winner='+'.join(sorted(m for m in POOL if Q[m][i] == 1))))
    from collections import Counter
    switch_summary = Counter(s['cls'] for s in switch_rows)
    harm_sw = [s for s in switch_rows if s['cls'] == 'harm']
    help_sw = [s for s in switch_rows if s['cls'] == 'help']
    rep = dict(
        n=n, n_SL=len(SL), n_SNL=len(SNL), n_ST=len(ST),
        SNL_breakdown=dict(
            medium_only=sum(1 for i in SNL if Q['medium'][i] == 1 and Q['coder'][i] == 0),
            coder_only=sum(1 for i in SNL if Q['coder'][i] == 1 and Q['medium'][i] == 0),
            both=sum(1 for i in SNL if Q['medium'][i] == 1 and Q['coder'][i] == 1)),
        feature_comparison=comparison,
        switches=dict(total=len(switch_rows), summary=dict(switch_summary),
                      help=help_sw, harm=harm_sw),
        interpretation=None)
    # interpretation
    max_auc = max((v['diagnostic_AUC'] or 0.5 for v in comparison.values()), default=0.5)
    max_smd = max((abs(v['SMD_SNL_minus_SL'] or 0) for v in comparison.values()), default=0)
    if max_auc > 0.65 or max_smd > 0.5:
        rep['interpretation'] = ('partial structural regularity exists (max diagnostic AUC=%.3f, max |SMD|=%.3f), '
                                 'but current routing features fail to exploit it robustly' % (max_auc, max_smd))
    else:
        rep['interpretation'] = ('residual complementarity is sparse and poorly separable under currently '
                                 'observable task features (max diagnostic AUC=%.3f, max |SMD|=%.3f), explaining '
                                 'the unstable generalization of instance-level routing' % (max_auc, max_smd))
    (CONF / 'HEADROOM_MECHANISM.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(dict(n_SL=len(SL), n_SNL=len(SNL), n_ST=len(ST),
                          SNL_breakdown=rep['SNL_breakdown'],
                          feature_comparison={k: v for k, v in comparison.items()
                                              if v['diagnostic_AUC'] is not None and abs(v['SMD_SNL_minus_SL'] or 0) > 0.15},
                          all_AUCs={k: v['diagnostic_AUC'] for k, v in comparison.items()},
                          switch_summary=dict(switch_summary),
                          harm_detail=[dict(to=h['to'], p_sw=h['p_sw'], actual=h['actual_winner']) for h in harm_sw],
                          interpretation=rep['interpretation']),
                     ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
