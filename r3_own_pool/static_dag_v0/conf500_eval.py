"""ONE-SHOT evaluation of frozen Two-stage tau=0.5 on confirmation-500.
Six core metrics: Q_Large, Q_Two-stage, Q_Oracle, GAP Recovery, Help/Harm, non-large winner recall.
Plus paired bootstrap CI and McNemar exact test."""
import json
import math
import random

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred, close
from .preference_router_dev import build_features
from .confirmation_500 import OUT as CONF

FROZEN_TAU = 0.5
SEED = 20260918
B = 10000

def load_conf500():
    pol = json.loads((CONF / 'CONF500_POLICY.json').read_text())
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
            rows.append(dict(uid=uid, question=t['question'], per_model=per, gold=gold, context=t['context']))
    return rows

def run():
    # train on all 900 dev (frozen pipeline)
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
    # embed conf-500 on CPU
    conf = load_conf500()
    from sentence_transformers import SentenceTransformer
    from .node_router_compare import GTE
    st = SentenceTransformer(GTE, device='cpu')
    cq = [r['question'] for r in conf]
    embs = st.encode(cq, normalize_embeddings=True, batch_size=8, show_progress_bar=False)
    del st
    emb_map_c = {q: embs[i] for i, q in enumerate(cq)}
    Xconf = build_features(conf, emb_map_c, dim)
    p_sw = ridge_pred(w_sw, Xconf)
    p_beats = {m: (ridge_pred(w_beats[m], Xconf) if w_beats[m] is not None else np.zeros(len(conf))) for m in ['medium', 'coder']}
    picks = []
    for i in range(len(conf)):
        if p_sw[i] > FROZEN_TAU:
            m2 = max(['medium', 'coder'], key=lambda m: p_beats[m][i])
            picks.append(m2 if p_beats[m2][i] > 0.5 else 'large')
        else:
            picks.append('large')
    # compute metrics
    n = len(conf)
    Q = {m: np.array([r['per_model'][m]['task_q'] for r in conf]) for m in POOL}
    q_large = Q['large']; q_2s = np.array([Q[picks[i]][i] for i in range(n)])
    oracle = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
    gap = oracle.mean() - q_large.mean()
    dq = q_2s - q_large
    # bootstrap
    rng = random.Random(SEED)
    boots = sorted(sum(dq[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    dq_ci = [round(boots[int(0.025 * B)], 4), round(boots[int(0.975 * B) - 1], 4)]
    gap_boots = sorted(
        (sum(q_2s[j] for j in idx) / n - sum(q_large[j] for j in idx) / n) /
        max(1e-9, sum(oracle[j] for j in idx) / n - sum(q_large[j] for j in idx) / n)
        for idx in ([rng.randrange(n) for _ in range(n)] for _ in range(B)))
    gap_ci = [round(gap_boots[int(0.025 * B)], 4), round(gap_boots[int(0.975 * B) - 1], 4)]
    # help/harm
    help_n = int(sum(1 for i in range(n) if dq[i] > 0))
    harm_n = int(sum(1 for i in range(n) if dq[i] < 0))
    # McNemar
    b = int(sum(1 for i in range(n) if q_2s[i] == 1 and q_large[i] == 0))
    c = int(sum(1 for i in range(n) if q_2s[i] == 0 and q_large[i] == 1))
    p_m = min(1.0, sum(math.comb(b + c, j) for j in range(0, min(b, c) + 1)) * (0.5 ** (b + c)) * 2) if b + c > 0 else 1.0
    # composition
    comp = dict(all_wrong=int(sum(1 for i in range(n) if all(Q[m][i] == 0 for m in POOL))),
                all_correct=int(sum(1 for i in range(n) if all(Q[m][i] == 1 for m in POOL))),
                headroom=int(sum(1 for i in range(n) if len({Q[m][i] for m in POOL}) > 1)))
    # non-large winner recall
    from collections import Counter
    head_ids = [i for i in range(n) if len({Q[m][i] for m in POOL}) > 1]
    winners = Counter()
    nonlarge_ids = []
    for i in head_ids:
        w = [m for m in POOL if Q[m][i] == 1]
        winners['+'.join(sorted(w))] += 1
        if 'large' not in w: nonlarge_ids.append(i)
    caught = sum(1 for i in nonlarge_ids if picks[i] != 'large' and Q[picks[i]][i] == 1)
    # switches
    switches = []
    for i in range(n):
        if picks[i] != 'large':
            switches.append(dict(to=picks[i], classification='help' if dq[i] > 0 else ('harm' if dq[i] < 0 else 'neutral')))
    rep = dict(
        n=n, frozen_tau=FROZEN_TAU,
        Q_large=round(float(q_large.mean()), 4), Q_2s=round(float(q_2s.mean()), 4),
        Q_oracle=round(float(oracle.mean()), 4), oracle_gap=round(float(gap), 4),
        GAP_recovery=round(float((q_2s.mean() - q_large.mean()) / gap), 4) if gap > 0 else None,
        GAP_recovery_ci95=gap_ci,
        dQ=round(float(dq.mean()), 4), dQ_ci95=dq_ci,
        help=help_n, harm=harm_n, neutral=n - help_n - harm_n,
        mcnemar=dict(b=b, c=c, p_exact=round(p_m, 4)),
        task_composition=comp, headroom_winners=dict(winners),
        nonlarge_winner=dict(total=len(nonlarge_ids), caught=caught,
                             recall=round(caught / max(1, len(nonlarge_ids)), 4)),
        switches=switches,
        note='one-shot conf-500; stage-1/2 trained on all 900 dev; propagated protocol')
    (CONF / 'CONF500_RESULTS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in rep.items() if k != 'switches'}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
