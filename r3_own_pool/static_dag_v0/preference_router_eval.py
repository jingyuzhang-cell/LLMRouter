"""ONE-SHOT evaluation of the frozen Two-stage τ=0.5 router on the independent
confirmation-200 set. Stage-1/2 models trained on ALL 900 dev questions (not CV).
No policy modifications. Reports Q, GAP Recovery, Headroom Top-1, Switch P/R, Harm."""
import json
import re

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred, close
from .preference_router_dev import KW, build_features
from .confirmation_200 import OUT as CONF

FROZEN_TAU = 0.5

def load_confirmation():
    pol = json.loads((CONF / 'CONF_POLICY.json').read_text())
    tasks = {t['uid']: t for t in pol['tasks']}
    resp = {}
    for l in (CONF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); resp[r['key']] = r
    rows = []
    for uid, t in tasks.items():
        gold = t['answer']
        per = {}
        for m in POOL:
            ext = resp.get(f'EXT:{m}:{uid}'); rsn = resp.get(f'RSN:{m}:{uid}')
            if ext is None or rsn is None: continue
            e = ext['response']; r = rsn['response']
            try: facts = v.parse_facts(e['answer'])
            except Exception: facts = {'facts': []}
            try:
                val = exec_calc(v.decode(r['answer'])['expression'], facts)
                q_task = int(close(val, gold))
            except Exception: q_task = 0
            per[m] = dict(task_q=q_task,
                          C=float((e.get('usage') or {}).get('total_tokens') or 0) + float((r.get('usage') or {}).get('total_tokens') or 0),
                          L=float(e.get('latency_s') or 0) + float(r.get('latency_s') or 0))
        if len(per) == len(POOL):
            rows.append(dict(uid=uid, task_uid=uid, question=t['question'], per_model=per, gold=gold, context=t['context']))
    return rows

def run():
    # ---- train stage-1/2 on ALL 900 dev ----
    corpus = load_corpus()
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    ctx_of = {t['uid']: t['context'] for t in pol['tasks']}
    for r in corpus: r['context'] = ctx_of.get(r['uid'], '')
    embz = np.load(CPROF / 'PROFILE_EMB.npz')
    emb_map = {q: embz['emb'][i] for i, q in enumerate(embz['questions'].tolist())}
    dim = embz['emb'].shape[1]
    Xdev = build_features(corpus, emb_map, dim)
    Qdev = {m: np.array([r['per_model'][m]['task_q'] for r in corpus]) for m in POOL}
    # stage 1: P(exists non-large beats large)
    sw_label = ((Qdev['medium'] > Qdev['large']) | (Qdev['coder'] > Qdev['large'])).astype(float)
    w_sw = ridge_fit(Xdev, sw_label)
    # stage 2: P(m > large) for m in {medium, coder}
    w_beats = {}
    for m in ['medium', 'coder']:
        d = Qdev[m] - Qdev['large']
        ntr = [i for i in range(len(d)) if d[i] != 0]
        w_beats[m] = ridge_fit(Xdev[ntr], (d[ntr] > 0).astype(float)) if ntr else None
    # absolute Q ridge (for CapabilityRouter arm)
    w_q = {m: ridge_fit(Xdev, Qdev[m]) for m in POOL}
    # pairwise margins (for PairwiseRouter arm)
    w_pair = {}
    for m in POOL:
        for o in POOL:
            if o == m: continue
            d = Qdev[m] - Qdev[o]
            ntr = [i for i in range(len(d)) if d[i] != 0]
            w_pair[(m, o)] = ridge_fit(Xdev[ntr], (d[ntr] > 0).astype(float)) if ntr else None
    # ---- confirmation-200 evaluation ----
    conf = load_confirmation()
    conf_emb = np.load(CPROF / 'PROFILE_EMB.npz')  # check if conf questions are in dev emb
    # build conf embeddings via the same GTE (may need fresh encode)
    conf_questions = [r['question'] for r in conf]
    if not all(q in emb_map for q in conf_questions):
        from sentence_transformers import SentenceTransformer
        from .node_router_compare import GTE
        st = SentenceTransformer(GTE)
        embs = st.encode(conf_questions, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
        del st
        import torch; torch.cuda.empty_cache()
        emb_map_c = {q: embs[i] for i, q in enumerate(conf_questions)}
    else:
        emb_map_c = emb_map
    Xconf = build_features(conf, emb_map_c, dim)
    Q = {m: np.array([r['per_model'][m]['task_q'] for r in conf]) for m in POOL}
    n = len(conf)
    oracle = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
    gap = oracle.mean() - Q['large'].mean()
    # predictions
    p_sw = ridge_pred(w_sw, Xconf)
    p_beats = {m: (ridge_pred(w_beats[m], Xconf) if w_beats[m] is not None else np.zeros(n)) for m in ['medium', 'coder']}
    q_hat = {m: ridge_pred(w_q[m], Xconf) for m in POOL}
    pair_sc = {m: np.zeros(n) for m in POOL}
    for m in POOL:
        for o in POOL:
            if o == m or w_pair.get((m, o)) is None: continue
            pair_sc[m] += ridge_pred(w_pair[(m, o)], Xconf)
    def evaluate(name, picks):
        qsel = np.array([Q[picks[i]][i] for i in range(n)])
        should_sw = np.array([(Q['medium'][i] > Q['large'][i]) or (Q['coder'][i] > Q['large'][i]) for i in range(n)])
        did_sw = np.array([picks[i] != 'large' for i in range(n)])
        benefit = int((did_sw & (qsel > Q['large'])).sum())
        harm = int((did_sw & (qsel < Q['large'])).sum())
        head = [i for i in range(n) if len({Q[m][i] for m in POOL}) > 1]
        head_top1 = float(np.mean([Q[picks[i]][i] == max(Q[m][i] for m in POOL) for i in head])) if head else None
        return dict(Q=round(float(qsel.mean()), 4),
                    GAP_recovery=round(float((qsel.mean() - Q['large'].mean()) / gap), 4) if gap > 0 else None,
                    headroom_n=len(head), headroom_top1=round(head_top1, 4) if head_top1 is not None else None,
                    switch_precision=round(benefit / max(1, int(did_sw.sum())), 4),
                    switch_recall=round(int((did_sw & should_sw).sum()) / max(1, int(should_sw.sum())), 4),
                    harm_rate=round(harm / n, 4), switches=int(did_sw.sum()))
    picks_tp = ['large'] * n
    picks_cap = [max(POOL, key=lambda m: q_hat[m][i]) for i in range(n)]
    picks_pw = [max(POOL, key=lambda m: pair_sc[m][i]) for i in range(n)]
    picks_2s = []
    for i in range(n):
        if p_sw[i] > FROZEN_TAU:
            m2 = max(['medium', 'coder'], key=lambda m: p_beats[m][i])
            picks_2s.append(m2 if p_beats[m2][i] > 0.5 else 'large')
        else:
            picks_2s.append('large')
    results = dict(
        TypePrior=evaluate('TypePrior', picks_tp),
        CapabilityRouter=evaluate('CapabilityRouter', picks_cap),
        PairwiseRouter=evaluate('PairwiseRouter', picks_pw),
        TwoStage_tau0_5=evaluate('TwoStage', picks_2s),
        Oracle=dict(Q=round(float(oracle.mean()), 4), GAP_recovery=1.0,
                    headroom_n=sum(1 for i in range(n) if len({Q[m][i] for m in POOL}) > 1),
                    headroom_top1=1.0, switches=0, harm_rate=0.0,
                    switch_precision=None, switch_recall=None))
    # composition
    comp = dict(all_wrong=int(sum(1 for i in range(n) if all(Q[m][i] == 0 for m in POOL))),
                all_correct=int(sum(1 for i in range(n) if all(Q[m][i] == 1 for m in POOL))),
                headroom=int(sum(1 for i in range(n) if len({Q[m][i] for m in POOL}) > 1)))
    rep = dict(frozen_tau=FROZEN_TAU, n=n, task_composition=comp,
               oracle_gap=round(float(gap), 4), results=results,
               note='one-shot: stage-1/2 trained on all 900 dev, applied once to confirmation-200')
    (CONF / 'CONF_RESULTS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
