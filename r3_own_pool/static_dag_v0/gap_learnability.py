"""Three zero-call analyses to precisely characterize the Residual GAP learnability.

1. Learnability Funnel: Oracle Opportunity -> Trigger Detectable -> Alternative
   Rankable -> Actually Recovered. Shows WHERE the signal is lost.
2. Selective Routing Risk-Coverage Curve: sort by switch score, allow only top
   k% to override, report GAP Recovery and Harm at each coverage level.
3. Cross-model Propagation Matrix: E_i -> R_j for all 9 pairs (uses existing
   data where available; reports which cells need new calls).

All analyses use the combined 1600-question corpus (900 dev + 200 conf + 500 conf)."""
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
from .confirmation_200 import OUT as CONF1
from .confirmation_500 import OUT as CONF5
from .trigger_v2 import load_all_with_states, runtime_state_features

SEED = 20260918
FOLDS = 5
ALPHA_RISK = 2.0

def sha(x):
    import hashlib
    return hashlib.sha256(x.encode()).hexdigest()

def run():
    rows = load_all_with_states()
    n = len(rows)
    feat_names = sorted(rows[0]['rsf'].keys())
    X = np.array([[r['rsf'][fn] for fn in feat_names] for r in rows])
    X = (X - X.mean(0)) / (X.std(0) + 1e-9)
    Q = {m: np.array([r['per_model_q'][m] for r in rows]) for m in POOL}
    # CV predictions for trigger and preference
    fold = {r['uid']: int(sha(r['uid'] + ':trig2'), 16) % FOLDS for r in rows}
    y_help = (np.maximum(Q['medium'], Q['coder']) > Q['large']).astype(float)
    y_harm = (np.maximum(Q['medium'], Q['coder']) < Q['large']).astype(float)
    pref_med = ((Q['medium'] > Q['large']) & (Q['medium'] >= Q['coder'])).astype(float)
    g_pred = np.zeros(n); pref_pred = np.zeros(n)
    for f in range(FOLDS):
        tr = [i for i in range(n) if fold[rows[i]['uid']] != f]
        te = [i for i in range(n) if fold[rows[i]['uid']] == f]
        w_h = ridge_fit(X[tr], y_help[tr]); w_a = ridge_fit(X[tr], y_harm[tr])
        w_p = ridge_fit(X[tr], pref_med[tr])
        g_pred[te] = ridge_pred(w_h, X[te]) - ALPHA_RISK * ridge_pred(w_a, X[te])
        pref_pred[te] = ridge_pred(w_p, X[te])

    # =================== 1. LEARNABILITY FUNNEL ===================
    # Level 0: Oracle opportunity (non-large exclusive winners exist)
    nonlarge_ids = [i for i in range(n) if Q['medium'][i] > Q['large'][i] or Q['coder'][i] > Q['large'][i]]
    # Level 1: Trigger detectable (g_pred > 0 for these tasks)
    trigger_caught = [i for i in nonlarge_ids if g_pred[i] > 0]
    # Level 2: Alternative correctly ranked (stage-2 picks a model that actually beats large)
    rank_correct = []
    for i in trigger_caught:
        pick_med = pref_pred[i] > 0.5
        picked = 'medium' if pick_med else 'coder'
        if Q[picked][i] > Q['large'][i]:
            rank_correct.append(i)
    # Level 3: Actually recovered (full pipeline produces correct answer)
    actually_helped = [i for i in rank_correct if Q['medium'][i] > Q['large'][i] or Q['coder'][i] > Q['large'][i]]
    funnel = dict(
        total_tasks=n,
        L0_oracle_opportunity=len(nonlarge_ids),
        L1_trigger_detected=len(trigger_caught),
        L2_alternative_ranked_correctly=len(rank_correct),
        L3_actually_recovered=len(actually_helped),
        L0_rate=round(len(nonlarge_ids) / n, 4),
        L1_recall=round(len(trigger_caught) / max(1, len(nonlarge_ids)), 4),
        L2_precision=round(len(rank_correct) / max(1, len(trigger_caught)), 4),
        L3_rate=round(len(actually_helped) / max(1, len(nonlarge_ids)), 4),
        note='Funnel shows where signal is lost: L0->L1 is override detection (biggest loss); '
             'L1->L2 is alternative ranking (secondary loss); L2->L3 should be ~100%')

    # =================== 2. SELECTIVE ROUTING RISK-COVERAGE CURVE ===================
    sorted_by_g = sorted(range(n), key=lambda i: -g_pred[i])
    coverage_levels = [0.005, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.0]
    risk_coverage = []
    for cov in coverage_levels:
        k = max(1, int(n * cov))
        override_set = set(sorted_by_g[:k])
        picks = []
        for i in range(n):
            if i in override_set:
                picked = 'medium' if pref_pred[i] > 0.5 else 'coder'
                picks.append(picked)
            else:
                picks.append('large')
        q_sel = np.array([Q[picks[i]][i] for i in range(n)])
        dq = q_sel - Q['large']
        help_n = int(sum(1 for i in range(n) if dq[i] > 0))
        harm_n = int(sum(1 for i in range(n) if dq[i] < 0))
        oracle = np.array([max(Q[m][i] for m in POOL) for i in range(n)])
        gap = oracle.mean() - Q['large'].mean()
        gr = (q_sel.mean() - Q['large'].mean()) / gap if gap > 0 else 0
        risk_coverage.append(dict(
            coverage=round(cov * 100, 1), n_override=k,
            help=help_n, harm=harm_n, net=help_n - harm_n,
            Q=round(float(q_sel.mean()), 4), GAP_recovery=round(float(gr), 4)))

    # =================== 3. CROSS-MODEL PROPAGATION MATRIX ===================
    # For the 900 dev corpus, we have E_m -> R_m (same model). Check if we can
    # form cross pairs from existing data (E_i facts + R_j on those facts).
    # This requires running R_j on E_i's extraction output - we only have R_j on E_j.
    # So we report the same-model matrix and identify which cross-cells need new calls.
    prop_matrix = {}
    for m in POOL:
        q_vals = [r['per_model_q'][m] for r in rows]
        prop_matrix[f'E_{m}->R_{m}'] = dict(
            Q=round(float(np.mean(q_vals)), 4), n=len(q_vals))
    prop_matrix['note'] = ('Cross-model cells (E_large->R_medium etc.) require new reasoning calls '
                           'on cross-model extraction outputs; reported here as design, not results')

    rep = dict(n=n, funnel=funnel, risk_coverage=risk_coverage, propagation_matrix=prop_matrix,
               interpretation=None)
    # interpretation based on risk-coverage
    low_cov = [rc for rc in risk_coverage if rc['coverage'] <= 5.0]
    if low_cov and any(rc['net'] > 0 for rc in low_cov):
        best_low = max(low_cov, key=lambda rc: rc['net'])
        rep['interpretation'] = (
            f"Residual GAP has exploitable signal at high selectivity: at {best_low['coverage']}% coverage, "
            f"Help={best_low['help']} > Harm={best_low['harm']} (net +{best_low['net']}), "
            f"GAP Recovery={best_low['GAP_recovery']:.1%}. Signal degrades as coverage expands.")
    else:
        rep['interpretation'] = (
            "No positive net gain at any coverage level; residual GAP signal is too sparse "
            "for reliable exploitation even at maximum selectivity.")
    out = BASE / 'gap_learnability_analysis'
    out.mkdir(exist_ok=True)
    (out / 'GAP_LEARNABILITY.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
