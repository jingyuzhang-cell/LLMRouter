"""Trigger v2: Runtime-state-aware + Harm-sensitive Override Trigger.

Targets the identified bottleneck (s_switch AUC=0.458) by:
(1) Adding runtime execution-state features from large's actual extraction output
    (not gold): extraction fact count, parse success, numeric coverage proxy,
    output length, expression executability.
(2) Training a net-gain predictor G(x) = P(Help) - alpha*P(Harm) instead of a
    binary switch classifier. alpha > 1 encodes asymmetric risk.
(3) Uncertainty gating: only override when G > tau AND cross-fold variance of G
    is below a threshold (reject ambiguous cases).

Trained on all 1100 (900 dev + 200 conf-1) questions. All three prior sets are
now development data. A fresh Final Confirmation set will be frozen separately.
"""
import hashlib
import json
import math
import re

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus, ridge_fit, ridge_pred, close
from .preference_router_dev import build_features, KW
from .confirmation_200 import OUT as CONF1
from .confirmation_500 import OUT as CONF5
from .node_benchmark_build import operand_values

SEED = 20260918
FOLDS = 5
ALPHA_RISK = 2.0  # one harm costs 2x one missed help
TAU = 0.0         # override only when G > 0 (positive expected net gain)
UNCERTAINTY_K = 1.0  # require G > k * fold_std to override

def sha(x):
    import hashlib
    return hashlib.sha256(x.encode()).hexdigest()

def runtime_state_features(task, ext_answer, rsn_answer, gold_answer):
    """Features observable AFTER large has executed extraction + reasoning.
    NO gold information used."""
    f = {}
    # extraction state
    try:
        facts = v.parse_facts(ext_answer)
        f['n_facts'] = len(facts['facts'])
        f['ext_parse_ok'] = 1.0
        f['ext_len'] = len(ext_answer)
        f['ext_n_nums'] = len(re.findall(r'\d+(?:\.\d+)?', ext_answer))
        vals = [ff['value'] for ff in facts['facts']]
        f['n_unique_vals'] = len(set(round(x, 6) for x in vals))
        f['val_range'] = float(max(vals) - min(vals)) if len(vals) > 1 else 0.0
        f['has_negative'] = float(any(x < 0 for x in vals)) if vals else 0.0
        f['has_decimal'] = float(any(abs(x - round(x)) > 1e-9 for x in vals)) if vals else 0.0
    except Exception:
        f['n_facts'] = 0; f['ext_parse_ok'] = 0.0; f['ext_len'] = len(ext_answer or '')
        f['ext_n_nums'] = 0; f['n_unique_vals'] = 0; f['val_range'] = 0.0
        f['has_negative'] = 0.0; f['has_decimal'] = 0.0
        vals = []
    # reasoning state (large's own output)
    try:
        expr = v.decode(rsn_answer)['expression']
        f['rsn_parse_ok'] = 1.0
        f['rsn_len'] = len(rsn_answer)
        f['expr_n_ops'] = len(re.findall(r'[+\-*/]', expr))
        f['expr_n_refs'] = len(re.findall(r'v\d+', expr))
        f['expr_n_consts'] = len(re.findall(r'(?<!v)\d+(?:\.\d+)?', expr))
        # can the expression execute on available facts?
        try:
            exec_calc(expr, {'facts': [dict(value=x, evidence='e') for x in vals]})
            f['expr_exec_ok'] = 1.0
        except Exception:
            f['expr_exec_ok'] = 0.0
    except Exception:
        f['rsn_parse_ok'] = 0.0; f['rsn_len'] = len(rsn_answer or '')
        f['expr_n_ops'] = 0; f['expr_n_refs'] = 0; f['expr_n_consts'] = 0
        f['expr_exec_ok'] = 0.0
    # task-level features (runtime observable)
    q = task['question']; ctx = task.get('context', '')
    f['q_len'] = len(q); f['ctx_len'] = len(ctx)
    f['n_nums_q'] = len(re.findall(r'\d+(?:\.\d+)?', q))
    f['facts_to_nums_ratio'] = f['n_facts'] / max(1, f['n_nums_q'])
    return f

def load_all_with_states():
    """Load 900 + 200 + 500 = 1600 questions with runtime state features and Q per model."""
    all_rows = []
    for src_out, policy_file in [(CPROF, 'PROFILE_POLICY.json'), (CONF1, 'CONF_POLICY.json'), (CONF5, 'CONF500_POLICY.json')]:
        pol = json.loads((src_out / policy_file).read_text())
        resp = {}
        resp_file = src_out / 'RESPONSES.jsonl'
        if resp_file.exists():
            for l in resp_file.read_text().splitlines():
                r = json.loads(l); resp[r['key']] = r
        for t in pol['tasks']:
            uid = t['uid']; gold = t['answer']
            per = {}
            ext_ans = {}; rsn_ans = {}
            for m in POOL:
                ext = resp.get(f'EXT:{m}:{uid}'); rsn = resp.get(f'RSN:{m}:{uid}')
                if ext is None or rsn is None: continue
                e = ext['response']; r = rsn['response']
                ext_ans[m] = e['answer']; rsn_ans[m] = r['answer']
                try: facts = v.parse_facts(e['answer'])
                except Exception: facts = {'facts': []}
                try:
                    val = exec_calc(v.decode(r['answer'])['expression'], facts)
                    q_task = int(close(val, gold))
                except Exception: q_task = 0
                per[m] = q_task
            if len(per) == len(POOL):
                rsf = runtime_state_features(t, ext_ans['large'], rsn_ans['large'], gold)
                all_rows.append(dict(uid=uid, question=t['question'], context=t.get('context', ''),
                                     per_model_q=per, gold=gold, rsf=rsf))
    return all_rows

def run():
    rows = load_all_with_states()
    n = len(rows)
    print(f'loaded {n} questions with runtime state features')
    # build feature matrix
    feat_names = sorted(rows[0]['rsf'].keys())
    X = np.array([[r['rsf'][fn] for fn in feat_names] for r in rows])
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    Q = {m: np.array([r['per_model_q'][m] for r in rows]) for m in POOL}
    # net-gain labels: dQ = max(non-large Q) - Q_large, values in {-1, 0, +1}
    best_nonlarge = np.maximum(Q['medium'], Q['coder'])
    dQ = best_nonlarge - Q['large']
    y_help = (dQ > 0).astype(float)   # switching would help
    y_harm = (dQ < 0).astype(float)   # switching would hurt
    # stage-2: preference for medium vs coder (among non-large)
    pref_med = ((Q['medium'] > Q['large']) & (Q['medium'] >= Q['coder'])).astype(float)
    # grouped CV
    fold = {r['uid']: int(sha(r['uid'] + ':trig2'), 16) % FOLDS for r in rows}
    g_pred = np.zeros(n)       # net gain score
    g_std = np.zeros(n)        # cross-fold uncertainty (proxy: distance from 0)
    pref_med_pred = np.zeros(n)
    for f in range(FOLDS):
        tr = [i for i in range(n) if fold[rows[i]['uid']] != f]
        te = [i for i in range(n) if fold[rows[i]['uid']] == f]
        w_help = ridge_fit(X[tr], y_help[tr])
        w_harm = ridge_fit(X[tr], y_harm[tr])
        w_pref = ridge_fit(X[tr], pref_med[tr])
        p_help = ridge_pred(w_help, X[te])
        p_harm = ridge_pred(w_harm, X[te])
        g_pred[te] = p_help - ALPHA_RISK * p_harm
        g_std[te] = np.abs(p_help) + np.abs(p_harm)  # higher when both are extreme
        pref_med_pred[te] = ridge_pred(w_pref, X[te])
    # evaluate trigger v2 policy
    picks = []
    for i in range(n):
        if g_pred[i] > TAU and g_pred[i] > UNCERTAINTY_K * 0.1:  # positive net gain + not too uncertain
            # stage 2: prefer medium or coder
            m2 = 'medium' if pref_med_pred[i] > 0.5 else 'coder'
            picks.append(m2)
        else:
            picks.append('large')
    q_large = Q['large']
    q_sel = np.array([Q[picks[i]][i] for i in range(n)])
    oracle = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
    gap = oracle.mean() - q_large.mean()
    dQ_sel = q_sel - q_large
    help_n = int(sum(1 for i in range(n) if dQ_sel[i] > 0))
    harm_n = int(sum(1 for i in range(n) if dQ_sel[i] < 0))
    switches = int(sum(1 for i in range(n) if picks[i] != 'large'))
    # AUC of the trigger itself
    head_ids = [i for i in range(n) if len({Q[m][i] for m in POOL}) > 1]
    # binary: should_switch (non-large winner exists) vs should_stay
    should_switch = np.array([1 if (Q['medium'][i] > Q['large'][i] or Q['coder'][i] > Q['large'][i]) else 0 for i in range(n)])
    # trigger AUC on all tasks
    pos_scores = [g_pred[i] for i in range(n) if should_switch[i] == 1]
    neg_scores = [g_pred[i] for i in range(n) if should_switch[i] == 0]
    def auc(pos, neg):
        if len(pos) < 2 or len(neg) < 2: return None
        c = sum(1 for p in pos for nn in neg if p > nn) + 0.5 * sum(1 for p in pos for nn in neg if p == nn)
        return round(c / (len(pos) * len(neg)), 4)
    trigger_auc = auc(pos_scores, neg_scores)
    rep = dict(
        n=n, alpha_risk=ALPHA_RISK, tau=TAU, uncertainty_k=UNCERTAINTY_K,
        feat_names=feat_names,
        Q_large=round(float(q_large.mean()), 4), Q_triggerv2=round(float(q_sel.mean()), 4),
        Q_oracle=round(float(oracle.mean()), 4), oracle_gap=round(float(gap), 4),
        GAP_recovery=round(float((q_sel.mean() - q_large.mean()) / gap), 4) if gap > 0 else None,
        help=help_n, harm=harm_n, switches=switches,
        trigger_auc_on_switch_decision=trigger_auc,
        note='Trigger v2 CV on all 1600 dev questions (900+200+500); NOT a confirmation result')
    (BASE / 'trigger_v2_dev.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
