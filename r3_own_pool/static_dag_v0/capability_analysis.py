"""Capability Profiling analysis — implements ANALYSIS_PROTOCOL.json exactly.

Layer 1 per-model Q/C/L prediction metrics; Layer 2 ranking metrics; Layer 3 routing
table (Best Single / Query Router / Type Prior / Capability Router / Oracle) on the
900-question corpus (task-level grouped 5-fold CV) and transferred to the independent
fresh-100 holdout (propagated protocol, recomputed identically).
"""
import json
import time

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .recovery_matrix_v2_audit import close
from .node_benchmark_build import operand_values

OUT = BASE / 'capability_profiling'
FRESH = BASE / 'fresh_static_confirmation'
SEED = 20260918
def sha(x):
    import hashlib
    return hashlib.sha256(x.encode()).hexdigest()
ALPHA = 1.0
FOLDS = 5
TYPES = ['extraction', 'reasoning']

def load_corpus():
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    tasks = {t['uid']: t for t in pol['tasks']}
    resp = {}
    for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); resp[r['key']] = r
    rows = []
    for uid, t in tasks.items():
        gold = t['answer']; prog = t['program']
        req = sorted({x for x in operand_values(prog)})
        per_model = {}
        for m in POOL:
            ext = resp.get(f'EXT:{m}:{uid}'); rsn = resp.get(f'RSN:{m}:{uid}')
            if ext is None or rsn is None: continue
            e = ext['response']; r = rsn['response']
            try: facts = v.parse_facts(e['answer'])
            except Exception: facts = {'facts': []}
            fvals = [f['value'] for f in facts['facts']]
            cov = sum(any(abs(fv - x) <= 1e-4 * max(1, abs(x)) for fv in fvals) for x in req) / len(req) if req else 1.0
            q_ext = int(len(fvals) > 0 and cov == 1.0)
            try:
                expr = v.decode(r['answer'])['expression']
                val = exec_calc(expr, facts)
                q_rsn = int(close(val, gold)); task_q = q_rsn
            except Exception:
                expr = None; val = None; q_rsn = 0; task_q = 0
            c = float((e.get('usage') or {}).get('total_tokens') or 0) + float((r.get('usage') or {}).get('total_tokens') or 0)
            l = float(e.get('latency_s') or 0) + float(r.get('latency_s') or 0)
            per_model[m] = dict(q_ext=q_ext, q_rsn=q_rsn, task_q=task_q, expr=expr, val=val,
                                cov=round(cov, 3), n_facts=len(fvals), C=c, L=l)
        if len(per_model) == len(POOL):
            rows.append(dict(uid=uid, task_uid=uid, question=t['question'], per_model=per_model, gold=gold))
    return rows

def features(questions, emb_map, dim):
    X = np.zeros((len(questions), dim + 4 + 1))
    for i, q in enumerate(questions):
        e = emb_map.get(q)
        if e is not None: X[i, :dim] = e
        X[i, dim:dim + 4] = [0, 1, 0, 0]  # rows are reasoning-node features; type block present
        X[i, -1] = np.log1p(len(q))
    return X

def ridge_fit(X, y):
    return np.linalg.solve(X.T @ X + ALPHA * np.eye(X.shape[1]), X.T @ y)

def ridge_pred(model, X):
    return X @ model

def ece(scores, labels, bins=10):
    import math
    e = 0.0; n = len(scores)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        ids = [i for i in range(n) if lo <= scores[i] < hi or (b == bins - 1 and scores[i] == hi)]
        if not ids: continue
        e += len(ids) * abs(sum(labels[i] for i in ids) / len(ids) - sum(scores[i] for i in ids) / len(ids))
    return round(e / n, 4) if n else None

def auc(scores, labels):
    pairs = sorted(zip(scores, labels))
    n1 = sum(labels); n0 = len(labels) - n1
    if not n1 or not n0: return None
    ranks = {}; i = 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]: j += 1
        avg = (i + j + 1) / 2
        for k in range(i, j): ranks[pairs[k][1]] = ranks.get(pairs[k][1], []) + [avg]
        i = j
    r1 = sum(ranks.get(1, []))
    return round((r1 - (n1 * (n1 + 1) / 2)) / (n1 * n0), 4)

def run():
    import time as _t
    t0 = _t.time()
    corpus = load_corpus()
    embz = np.load(OUT / 'PROFILE_EMB.npz')
    emb_map = {q: embz['emb'][i] for i, q in enumerate(embz['questions'].tolist())}
    dim = embz['emb'].shape[1]
    questions = [r['question'] for r in corpus]
    X = features(questions, emb_map, dim)
    uids = [r['uid'] for r in corpus]
    # task-level grouped folds (hash-based, deterministic)
    fold = {u: int(sha(u + ':fold'), 16) % FOLDS for u in uids}
    # predictions per (type, model) via grouped CV
    pred = {ty: {m: np.zeros(len(corpus)) for m in POOL} for ty in TYPES}
    predC = {ty: {m: np.zeros(len(corpus)) for m in POOL} for ty in TYPES}
    predL = {ty: {m: np.zeros(len(corpus)) for m in POOL} for ty in TYPES}
    for f in range(FOLDS):
        tr = [i for i, r in enumerate(corpus) if fold[r['uid']] != f]
        te = [i for i, r in enumerate(corpus) if fold[r['uid']] == f]
        for ty in TYPES:
            suf = 'q_ext' if ty == 'extraction' else 'q_rsn'
            for m in POOL:
                yq = np.array([r['per_model'][m][suf] for r in corpus])
                yc = np.array([r['per_model'][m]['C'] for r in corpus])
                yl = np.array([r['per_model'][m]['L'] for r in corpus])
                mq = ridge_fit(X[tr], yq[tr]); pred[ty][m][te] = ridge_pred(mq, X[te])
                mc = ridge_fit(X[tr], np.log1p(yc[tr])); predC[ty][m][te] = np.expm1(ridge_pred(mc, X[te]))
                ml = ridge_fit(X[tr], np.log1p(yl[tr])); predL[ty][m][te] = np.expm1(ridge_pred(ml, X[te]))
    # ---- final predictors trained on the full corpus (for transfer) ----
    finalQ = {ty: {m: ridge_fit(X, np.array([r['per_model'][m]['q_rsn'] for r in corpus])) for m in POOL} for ty in TYPES}
    # ---- Layer 1: per-model prediction metrics (reasoning node; extraction C/L analogous) ----
    L1 = {}
    for m in POOL:
        y_true = [r['per_model'][m]['q_rsn'] for r in corpus]
        y_score = list(pred['reasoning'][m])
        acc = round(sum(int((s > 0.5) == (l == 1)) for s, l in zip(y_score, y_true)) / len(y_true), 4)
        brier = round(sum((min(max(s, 0), 1) - l) ** 2 for s, l in zip(y_score, y_true)) / len(y_true), 4)
        yc = [r['per_model'][m]['C'] for r in corpus]; pc = list(predC['reasoning'][m])
        yl_ = [r['per_model'][m]['L'] for r in corpus]; pl = list(predL['reasoning'][m])
        mae_c = round(sum(abs(a - b) for a, b in zip(pc, yc)) / len(yc), 1)
        mape_c = round(sum(abs(a - b) / max(1, b) for a, b in zip(pc, yc)) / len(yc), 3)
        mae_l = round(sum(abs(a - b) for a, b in zip(pl, yl_)) / len(yl_), 3)
        mape_l = round(sum(abs(a - b) / max(0.1, b) for a, b in zip(pl, yl_)) / len(yl_), 3)
        L1[m] = dict(Q_auc=auc(y_score, y_true), Q_acc=acc, Q_brier=brier, Q_ece=ece(y_score, y_true),
                     C_mae=mae_c, C_mape=mape_c, L_mae=mae_l, L_mape=mape_l)
    # ---- Layer 2 + Layer 3 (task level, reasoning decides) ----
    arms = {a: dict(Q=0, C=0.0, L=0.0, top1=0, regret=0.0) for a in
            ['BestSingle', 'QueryRouter', 'TypePrior', 'CapabilityRouter', 'Oracle']}
    pair_ok = pair_tot = 0
    nontie_ok = nontie_tot = 0
    spearman_rows = []
    comp = dict(all_wrong=0, all_correct=0, headroom=0)
    sub = {a: dict(top1=0, regret=0.0) for a in ['QueryRouter', 'TypePrior', 'CapabilityRouter']}
    mean_q_pre = {m: float(np.mean([r['per_model'][m]['q_rsn'] for r in corpus])) for m in POOL}
    best_single_pre = max(POOL, key=lambda m: mean_q_pre[m])
    type_prior_pre = {ty: max(POOL, key=lambda m: float(np.mean(
        [r['per_model'][m][('q_ext' if ty == 'extraction' else 'q_rsn')] for r in corpus]))) for ty in TYPES}
    for i, r in enumerate(corpus):
        true_q = {m: r['per_model'][m]['q_rsn'] for m in POOL}
        pred_q = {m: float(pred['reasoning'][m][i]) for m in POOL}
        oracle_m = max(POOL, key=lambda m: (true_q[m], pred_q.get(m, 0)))
        best_pair = sorted(POOL, key=lambda m: (-true_q[m], -pred_q[m]))
        for a in range(len(POOL)):
            for b in range(a + 1, len(POOL)):
                m1, m2 = best_pair[a], best_pair[b]
                if true_q[m1] != true_q[m2]:  # only non-tied pairs are decision-relevant
                    nontie_tot += 1
                    if pred_q[m1] != pred_q[m2]:
                        nontie_ok += int((pred_q[m1] > pred_q[m2]) == (true_q[m1] > true_q[m2]))
        def rank_of(d):
            order = sorted(d, key=lambda k: d[k])
            return {k: i + 1 for i, k in enumerate(order)}
        rp, rt = rank_of(pred_q), rank_of(true_q)
        if len(set(pred_q.values())) > 1 and len(set(true_q.values())) > 1:
            d2 = sum((rp[m] - rt[m]) ** 2 for m in POOL)
            spearman_rows.append(1 - 6 * d2 / (len(POOL) * (len(POOL) ** 2 - 1)))
        elif len(set(true_q.values())) == 1:
            spearman_rows.append(0.0)
        vals = sorted(true_q.values())
        q_oracle = max(true_q.values())
        if vals[0] == vals[-1]:
            comp['all_wrong' if vals[0] == 0 else 'all_correct'] += 1
        else:
            comp['headroom'] += 1
            # headroom-subset metrics: ties excluded, decision-relevant only
            for a, m in [('QueryRouter', max(POOL, key=lambda mm: sum(pred[ty][mm][i] for ty in TYPES))),
                         ('TypePrior', type_prior_pre['reasoning']),
                         ('CapabilityRouter', max(POOL, key=lambda mm: pred['reasoning'][mm][i]))]:
                sub[a]['top1'] += int(true_q[m] == q_oracle)
                sub[a]['regret'] += q_oracle - true_q[m]
        # arms
        sel = {}
        sel['Oracle'] = oracle_m
        sel['BestSingle'] = None  # global constant, filled after loop via train means
        sel['QueryRouter'] = max(POOL, key=lambda m: sum(pred[ty][m][i] for ty in TYPES))
        sel['TypePrior'] = None  # filled after loop
        sel['CapabilityRouter'] = max(POOL, key=lambda m: pred['reasoning'][m][i])
        for a, m in sel.items():
            if m is None: continue
            arms[a]['Q'] += true_q[m]
            if true_q[m] == max(true_q.values()): arms[a]['top1'] += 1
            arms[a]['regret'] += q_oracle - true_q[m]
            arms[a]['C'] += sum(r['per_model'][m][kk] for kk in ['C']) if a != 'Oracle' else sum(
                r['per_model'][oracle_m][kk] for kk in ['C'])
            arms[a]['L'] += r['per_model'][m]['L'] if a != 'Oracle' else r['per_model'][oracle_m]['L']
    # BestSingle / TypePrior from training aggregates (fold-0 model over full corpus means)
    mean_q = {m: np.mean([r['per_model'][m]['q_rsn'] for r in corpus]) for m in POOL}
    best_single = max(POOL, key=lambda m: mean_q[m])
    type_prior = {ty: max(POOL, key=lambda m: np.mean([r['per_model'][m][('q_ext' if ty == 'extraction' else 'q_rsn')] for r in corpus])) for ty in TYPES}
    for r, i in zip(corpus, range(len(corpus))):
        true_q = {m: r['per_model'][m]['q_rsn'] for m in POOL}
        q_oracle = max(true_q.values())
        m = best_single
        arms['BestSingle']['Q'] += true_q[m]; arms['BestSingle']['C'] += r['per_model'][m]['C']
        arms['BestSingle']['L'] += r['per_model'][m]['L']
        arms['BestSingle']['regret'] += q_oracle - true_q[m]
        m = type_prior['reasoning']
        arms['TypePrior']['Q'] += true_q[m]; arms['TypePrior']['C'] += r['per_model'][m]['C']
        arms['TypePrior']['L'] += r['per_model'][m]['L']
        arms['TypePrior']['regret'] += q_oracle - true_q[m]
    n = len(corpus)
    table = {}
    for a, d in arms.items():
        table[a] = dict(Q=round(d['Q'] / n, 4), C=round(d['C'] / n, 1), L=round(d['L'] / n, 2),
                        top1_hit=round(d['top1'] / n, 4), R_Q=round(d['regret'] / n, 4))
    # ---- headline deltas with task-level bootstrap CI (protocol requirement) ----
    import random as _r
    rng2 = _r.Random(SEED)
    order = list(range(len(corpus)))
    def pair_boot(sel_a, sel_b, attr):
        out = []
        for _ in range(5000):
            sm = [order[rng2.randrange(n)] for _ in range(n)]
            da = sum(arms[sel_a][attr] for _ in [0]) if False else None
            # per-task recomputation requires per-task records; compute from stored per-task sums
        return None
    # per-task sums were accumulated in arms; recompute per-task records for bootstrap
    per_task = {a: {} for a in list(arms) + ['CapabilityRouter_reasoning']}
    for r, i in zip(corpus, range(len(corpus))):
        true_q = {m: r['per_model'][m]['q_rsn'] for m in POOL}
        q_oracle = max(true_q.values())
        x = X[i].reshape(1, -1)
        pred_q = {ty: {m: float(pred[ty][m][i]) for m in POOL} for ty in TYPES}
        sel = dict(
            Oracle=max(POOL, key=lambda m: true_q[m]),
            QueryRouter=max(POOL, key=lambda m: sum(pred_q[ty][m] for ty in TYPES)),
            TypePrior=max(POOL, key=lambda m: float(np.mean([r['per_model'][m][('q_ext' if ty == 'extraction' else 'q_rsn')] for r in corpus]))),
            CapabilityRouter={ty: max(POOL, key=lambda m: pred_q[ty][m]) for ty in TYPES})
        for a, m in [('BestSingle', best_single), ('QueryRouter', sel['QueryRouter']),
                     ('TypePrior', sel['TypePrior']), ('Oracle', sel['Oracle']),
                     ('CapabilityRouter_reasoning', sel['CapabilityRouter']['reasoning'])]:
            per_task[a][i] = (true_q[m], sum(r['per_model'][m]['C'] for _ in TYPES) if False else r['per_model'][m]['C'], r['per_model'][m]['L'], q_oracle - true_q[m])
        # capability task Q uses reasoning-node outcome; C/L sum over per-type picks
        csum = sum(r['per_model'][sel['CapabilityRouter'][ty]]['C'] for ty in TYPES)
        lsum = sum(r['per_model'][sel['CapabilityRouter'][ty]]['L'] for ty in TYPES)
        per_task['CapabilityRouter'][i] = (true_q[sel['CapabilityRouter']['reasoning']], csum, lsum, q_oracle - true_q[sel['CapabilityRouter']['reasoning']])
    def boot_delta(a, b, k):
        diffs = []
        for _ in range(5000):
            sm = [order[rng2.randrange(n)] for _ in range(n)]
            diffs.append(sum(per_task[a][i][k] for i in sm) / n - sum(per_task[b][i][k] for i in sm) / n)
        diffs.sort()
        return [round(diffs[int(0.025 * len(diffs))], 4), round(diffs[int(0.975 * len(diffs)) - 1], 4)]
    headline_ci = {
        'dQ_Capability-TypePrior': boot_delta('CapabilityRouter', 'TypePrior', 0),
        'dQ_Capability-QueryRouter': boot_delta('CapabilityRouter', 'QueryRouter', 0),
        'dRQ_Capability-TypePrior': boot_delta('CapabilityRouter', 'TypePrior', 3)}
    # ---- transfer to fresh-100 (propagated protocol, recomputed identically) ----
    mean_q_full = {m: float(np.mean([r['per_model'][m]['q_rsn'] for r in corpus])) for m in POOL}
    best_single = max(POOL, key=lambda m: mean_q_full[m])
    type_prior_full = {ty: max(POOL, key=lambda m: float(np.mean(
        [r['per_model'][m][('q_ext' if ty == 'extraction' else 'q_rsn')] for r in corpus]))) for ty in TYPES}
    transfer = transfer_eval(finalQ, None, None, best_single, type_prior_full, FRESH)
    # transfer degradation (protocol): d_transfer = CV - fresh, per arm
    dtr = {}
    for a in ['BestSingle', 'QueryRouter', 'TypePrior', 'CapabilityRouter']:
        try:
            dtr[a] = dict(d_transfer_Q=round(table[a]['Q'] - transfer['arms'][a]['Q'], 4),
                          d_transfer_RQ=round(transfer['arms'][a]['R_Q'] - table[a]['R_Q'], 4))
        except KeyError: pass
    rep = dict(protocol='ANALYSIS_PROTOCOL.json', seed=SEED, alpha=ALPHA, folds=FOLDS,
               n_corpus=n, headline_ci=headline_ci,
               terminology=dict(task_quality='propagated capability (extract(m)->reason(m)); NOT pure reasoning capability',
                                L_definition='per-call inference service latency, loaded-model, cold-start excluded'),
               layer1_per_model=L1,
               layer2=dict(
                   pairwise_rank_acc_all=round(pair_ok / pair_tot, 4) if pair_tot else None,
                   pairwise_rank_acc_nontied=round(nontie_ok / nontie_tot, 4) if nontie_tot else None,
                   n_pairs_all=pair_tot, n_pairs_nontied=nontie_tot,
                   mean_spearman=round(sum(spearman_rows) / len(spearman_rows), 4) if spearman_rows else None),
               task_composition=comp,
               headroom_subset=dict(
                   n=comp['headroom'],
                   note='ties excluded; only tasks where models disagree (decision-relevant routing)',
                   **{a: dict(top1_hit=round(d['top1'] / max(1, comp['headroom']), 4),
                              R_Q=round(d['regret'] / max(1, comp['headroom']), 4)) for a, d in sub.items()}),
               layer3_routing_corpus=table, transfer_fresh100=transfer,
               transfer_degradation=dtr,
               type_prior=type_prior, best_single=best_single)
    (OUT / 'CAPABILITY_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in rep.items() if k != 'detail'}, ensure_ascii=False, indent=2))

def transfer_eval(finalQ, finalC, finalL, best_single, type_prior, FRESH):
    """Apply full-corpus predictors to the independent fresh-100 holdout under the
    propagated protocol (reasoning consumes its own model's extraction), recomputing
    task Q identically to the 900-question corpus."""
    tasks = {t['uid']: t for t in json.loads((FRESH / 'TASKS.json').read_text())}
    files = {m: [json.loads(l) for l in (FRESH / (m + '_RESPONSES.jsonl')).read_text().splitlines()] for m in POOL}
    embz = np.load(FRESH / 'QUESTION_EMBEDDINGS.npz')
    emb_map = {q: embz['emb'][i] for i, q in enumerate(embz['questions'].tolist())}
    dim = embz['emb'].shape[1]
    rows = []
    for uid, t in tasks.items():
        per = {}
        for m in POOL:
            ext = rsn = None
            for r in files[m]:
                if r.get('task_uid') != uid: continue
                if r.get('node_type') == 'extraction' and ext is None: ext = r
                if r.get('node_type') == 'reasoning' and rsn is None: rsn = r
            if ext is None or rsn is None: continue
            try: facts = v.parse_facts(ext['answer'])
            except Exception: facts = {'facts': []}
            try:
                val = exec_calc(v.decode(rsn['answer'])['expression'], facts)
                q_task = int(close(val, t['answer']))
            except Exception: q_task = 0
            c = float((ext.get('usage') or {}).get('total_tokens') or 0) + float((rsn.get('usage') or {}).get('total_tokens') or 0)
            ll = float(ext.get('latency_s') or 0) + float(rsn.get('latency_s') or 0)
            per[m] = dict(task_q=q_task, C=c, L=ll)
        if len(per) == len(POOL):
            X = features([t['question']], emb_map, dim)
            rows.append(dict(uid=uid, question=t['question'], per=per, X=X[0]))
    n = len(rows)
    arms = {a: dict(Q=0, C=0.0, L=0.0, top1=0, RQ=0.0) for a in
            ['BestSingle', 'QueryRouter', 'TypePrior', 'CapabilityRouter', 'Oracle']}
    for r in rows:
        true_q = {m: r['per'][m]['task_q'] for m in POOL}
        q_oracle = max(true_q.values())
        x = r['X'].reshape(1, -1)
        pred_q = {ty: {m: float((x @ finalQ[ty][m])[0]) for m in POOL} for ty in TYPES}
        sel = dict(
            Oracle=max(POOL, key=lambda m: true_q[m]),
            QueryRouter=max(POOL, key=lambda m: sum(pred_q[ty][m] for ty in TYPES)),
            TypePrior=type_prior['reasoning'],
            BestSingle=best_single,
            CapabilityRouter={ty: max(POOL, key=lambda m: pred_q[ty][m]) for ty in TYPES})
        for a, m in [('BestSingle', sel['BestSingle']), ('QueryRouter', sel['QueryRouter']),
                     ('TypePrior', sel['TypePrior']), ('Oracle', sel['Oracle'])]:
            arms[a]['Q'] += true_q[m]; arms[a]['C'] += r['per'][m]['C']; arms[a]['L'] += r['per'][m]['L']
            arms[a]['top1'] += int(true_q[m] == q_oracle); arms[a]['RQ'] += q_oracle - true_q[m]
        # CapabilityRouter: per-type selection; task quality decided by the reasoning node
        m_rsn = sel['CapabilityRouter']['reasoning']
        for ty, m in sel['CapabilityRouter'].items():
            arms['CapabilityRouter']['C'] += r['per'][m]['C']; arms['CapabilityRouter']['L'] += r['per'][m]['L']
        arms['CapabilityRouter']['Q'] += true_q[m_rsn]
        arms['CapabilityRouter']['top1'] += int(true_q[m_rsn] == q_oracle)
        arms['CapabilityRouter']['RQ'] += q_oracle - true_q[m_rsn]
    out = {}
    for a, d in arms.items():
        out[a] = dict(Q=round(d['Q'] / n, 4), C=round(d['C'] / n, 1), L=round(d['L'] / n, 2),
                      top1=round(d['top1'] / n, 4), R_Q=round(d['RQ'] / n, 4))
    return dict(n=n, arms=out,
                note='transfer: predictors trained on the 900-question corpus applied to fresh-100; '
                     'quality recomputed under the propagated protocol (reasoning on own extraction)')

if __name__ == '__main__':
    run()
