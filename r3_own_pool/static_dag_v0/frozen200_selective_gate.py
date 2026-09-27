"""P0-1: Zero-call selective-gate learnability on Frozen200 (no model calls).

Question: of the Selective Oracle headroom (101/200 = +10.8pp over Always
Single), how much is learnable from STRICTLY decision-time features?

Labels (per task x seed, from FROZEN200_RESULTS.json f30 arms):
    U = Q_D - Q_S in {+1 help, 0 neutral, -1 harm}
Primary target: P(U > 0); neutral samples excluded from classifier training,
all tasks still receive a gate decision at policy evaluation.

Features — deployable BEFORE any node executes (no gold, no `injected` flag,
no outcomes, no derivation):
    question: length, word count, numeric count, type flags
    (ratio/percent/sum/average/change/difference/total/growth)
    contexts: table chars/rows, text chars, passage count, table numeric count

Models: LogisticRegression (interpretable), HistGradientBoosting (nonlinear),
calibrated HistGB (probability model for P_help/P_harm gating).

Protocol: GroupKFold(5) by task; threshold tau chosen on TRAIN folds only by
simulating gate Q on train per-seed outcomes; test Q uses exact held-out
per-seed outcomes. Report Help Capture / Harm Avoidance / Intervention Rate /
Selective Success, baselines (Always-Single, Always-Dynamic, Random sweep,
Oracle) and Regret_oracle = Q_oracle - Q_learned.
"""
import json
import re
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path('/root/r3_own_pool')
F200 = ROOT / 'static_dag_v0/frozen200'
OUT = ROOT / 'static_dag_v0/frozen200_selective_gate'
SEEDS = [20260923, 20260924, 20260925]
TAUS = np.round(np.arange(0.05, 0.96, 0.05), 2)


def features(t):
    q = t['question'].lower()
    tab, txt = t['ctx_table'], t['ctx_text']
    nums = lambda s: len(re.findall(r'\d+\.?\d*', s))
    f = [len(t['question']), len(q.split()), nums(q),
         len(tab), len(tab.splitlines()), nums(tab),
         len(txt), nums(txt),
         1 + max([int(m) for m in re.findall(r'\[(\d+)\]', txt)] or [0])]
    for w in ['ratio', 'percent', 'sum', 'average', 'change', 'difference',
              'total', 'growth', 'increase', 'decrease']:
        f.append(1.0 * (w in q))
    return f


def load():
    pol = json.loads((F200 / 'FROZEN200_POLICY.json').read_text())
    res = json.loads((F200 / 'FROZEN200_RESULTS.json').read_text())['results']
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    X = np.array([features(t) for t in tasks], dtype=float)
    S = np.array([[res[f'f30_s{s}|single'][u]['ok'] for s in SEEDS] for u in uids], dtype=float)
    D = np.array([[res[f'f30_s{s}|dynamic'][u]['ok'] for s in SEEDS] for u in uids], dtype=float)
    C_S = np.array([[res[f'f30_s{s}|single'][u]['used'] for s in SEEDS] for u in uids])
    C_D = np.array([[res[f'f30_s{s}|dynamic'][u]['used'] for s in SEEDS] for u in uids])
    return tasks, X, S, D, C_S, C_D


def make_models():
    return {
        'logistic': make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5)),
        'hist_gb': HistGradientBoostingClassifier(max_iter=120, max_depth=3,
                                                  learning_rate=0.08, min_samples_leaf=15,
                                                  l2_regularization=1.0, random_state=0),
        'calibrated_gb': CalibratedClassifierClassifier(),
    }


def CalibratedClassifierClassifier():
    return CalibratedClassifierCV(HistGradientBoostingClassifier(max_iter=120, max_depth=3,
                                  learning_rate=0.08, min_samples_leaf=15,
                                  l2_regularization=1.0, random_state=0),
                                  method='sigmoid', cv=3)


def gate_q(p, tau, S, D):
    """Q of intervening iff p > tau (per-task probability, per-seed outcomes)."""
    act = (p > tau).astype(float)  # 1 = Dynamic, 0 = Single
    per_task = [float(np.mean([D[i, s] if act[i] else S[i, s] for s in range(len(SEEDS))]))
                for i in range(len(act))]
    return float(np.mean(per_task))


def rates(p, tau, S, D):
    U = D - S  # (n_tasks, n_seeds)
    help_m, harm_m = U > 0, U < 0
    act = p > tau
    hcr = float(act[help_m.any(1) & help_m.any(1) & np.ones(len(act), bool)].mean()) if help_m.any() else np.nan
    # help capture over task-level help (any seed) and harm avoidance analog
    help_tasks = U.max(1) > 0
    harm_tasks = U.min(1) < 0
    hcr = float(act[help_tasks].mean()) if help_tasks.any() else float('nan')
    har = float((~act[harm_tasks]).mean()) if harm_tasks.any() else float('nan')
    ir = float(act.mean())
    return dict(help_capture=hcr, harm_avoidance=har, intervention_rate=ir)


def run():
    OUT.mkdir(exist_ok=False)
    tasks, X, S, D, C_S, C_D = load()
    U = D - S
    n = len(tasks)
    per_seed = {s: dict(single=float(S[:, k].mean()), dynamic=float(D[:, k].mean()))
                for k, s in enumerate(SEEDS)}
    overall = dict(single=float(S.mean()), dynamic=float(D.mean()),
                   oracle=float(np.mean(np.maximum(S, D), axis=None
                                        ) if False else float(np.maximum(S, D).mean())),
                   help=int((U > 0).sum()), harm=int((U < 0).sum()), neutral=int((U == 0).sum()))
    groups = np.repeat(np.arange(n), 1)
    # sample-level expansion: each task contributes 3 seed samples for training
    Xs = np.repeat(X, len(SEEDS), axis=0)
    ys = (U > 0).T.reshape(-1).astype(int)
    keep = (U != 0).T.reshape(-1)
    grp = np.repeat(np.arange(n), len(SEEDS))
    results = {}
    rng = np.random.default_rng(0)
    for name in ['logistic', 'hist_gb', 'calibrated_gb']:
        fold_q, fold_rates, fold_auroc, fold_tau = [], [], [], []
        for tr_tasks, te_tasks in _folds(n):
            tr_s = np.isin(grp, tr_tasks) & keep
            te_s = np.isin(grp, te_tasks) & keep
            model = make_models()[name]
            model.fit(Xs[tr_s], ys[tr_s])
            p_tr = np.array([model.predict_proba(X[i:i + 1])[0, 1] for i in tr_tasks])
            p_te = np.array([model.predict_proba(X[i:i + 1])[0, 1] for i in te_tasks])
            taus = [t for t in TAUS]
            best_tau, best_q = 0.5, -1
            for t in taus:
                q = gate_q(p_tr, t, S[tr_tasks], D[tr_tasks])
                if q > best_q:
                    best_q, best_tau = q, t
            fold_q.append(gate_q(p_te, best_tau, S[te_tasks], D[te_tasks]))
            fold_rates.append(rates(p_te, best_tau, S[te_tasks], D[te_tasks]))
            fold_tau.append(best_tau)
            if len(set(ys[te_s])) == 2:
                fold_auroc.append(float(roc_auc_score(ys[te_s], model.predict_proba(Xs[te_s])[:, 1])))
        results[name] = dict(
            q_mean=float(np.mean(fold_q)), q_std=float(np.std(fold_q)),
            auroc_mean=float(np.mean(fold_auroc)) if fold_auroc else None,
            tau_chosen=[float(t) for t in fold_tau],
            rates_mean={k: float(np.nanmean([r[k] for r in fold_rates]))
                        for k in ['help_capture', 'harm_avoidance', 'intervention_rate']})
    # baselines
    q_single, q_dyn = overall['single'], overall['dynamic']
    random_curve = [gate_q(np.array([0.5] * n), 10.0, S, D)]  # placeholder
    rand = {f'intervene_{int(r * 100)}pct': float(r * q_dyn + (1 - r) * q_single)
            for r in [0.25, 0.5, 0.75]}
    out = dict(panel=dict(n_tasks=n, seeds=SEEDS, per_seed=per_seed, overall=overall),
               baselines=dict(always_single=q_single, always_dynamic=q_dyn,
                              random=rand, oracle_selective=overall['oracle']),
               models=results,
               regret_oracle={m: overall['oracle'] - r['q_mean'] for m, r in results.items()},
               features='question len/words/nums + type flags; table chars/rows/nums; '
                        'text chars/nums; passage count — all pre-execution, no gold, '
                        'no injected flag, no outcomes',
               protocol='GroupKFold(5) by task; tau chosen on train folds only; '
                        'neutral (U=0) excluded from training only')
    (OUT / 'RESULTS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(baselines=out['baselines'], models={m: dict(
        q_mean=round(r['q_mean'], 4), q_std=round(r['q_std'], 4),
        auroc=round(r['auroc_mean'], 3) if r['auroc_mean'] else None,
        rates=r['rates_mean']) for m, r in results.items()},
        regret_oracle=out['regret_oracle']), indent=1))


def _folds(n, k=5):
    gkf = GroupKFold(n_splits=k)
    idx = np.arange(n)
    for tr, te in gkf.split(idx, groups=idx):
        yield tr, te


if __name__ == '__main__':
    run()
