"""Leakage-resistant routing primitives. No outcome-derived online features."""
import numpy as np
import torch
from scipy.optimize import linprog

SLOTS = ('small', 'medium', 'large', 'reasoning')
GRID = [(l, m) for l in (0., .1, .5, 1., 2., 5.) for m in (0., .1, .5, 1.)]


def rank_loss(pred, target, margin=.05):
    """Strict quality pairs, query-normalized; ties have no artificial winner."""
    diff = target[:, :, None] - target[:, None, :]
    valid = diff > 0
    violation = torch.relu(margin - (pred[:, :, None] - pred[:, None, :]))
    return ((violation * valid).sum((1, 2)) / valid.sum((1, 2)).clamp_min(1)).mean()


def scales_from_train(y):
    scales = np.ones(3)
    for k in (1, 2):
        positive = y[:, :, k][y[:, :, k] > 0]
        scales[k] = np.median(positive) if positive.size else 1.
    return scales


def utility(y, preference, scales):
    return (y / scales) @ np.array([1., -preference[0], -preference[1]])


def route(pred, preference, scales):
    return utility(pred, preference, scales).argmax(1)


def chosen(y, decisions):
    decisions = np.asarray(decisions)
    if decisions.ndim == 1:
        return y[np.arange(len(y)), decisions]
    if decisions.shape != y.shape[:2] or not np.allclose(decisions.sum(1), 1):
        raise ValueError('Invalid policy probabilities')
    return (y * decisions[:, :, None]).sum(1)


def paired_ci(delta, seed=42, repeats=2000):
    delta = np.asarray(delta)
    if not len(delta):
        raise ValueError('Empty evaluation split')
    draws = np.random.default_rng(seed).integers(len(delta), size=(repeats, len(delta)))
    return np.quantile(delta[draws].mean(1), [.025, .975]).tolist()


def zero_mixture(train_y, baseline, scales, delta=0.):
    """Train-only fixed mixture: min cost subject to quality and latency baseline."""
    means = train_y.mean(0) / scales
    solution = linprog(means[:, 1], A_ub=np.array([-means[:, 0], means[:, 2]]),
                       b_ub=[-means[baseline, 0] + delta, means[baseline, 2]],
                       A_eq=np.ones((1, len(SLOTS))), b_eq=[1.], bounds=(0, 1), method='highs')
    if not solution.success:
        raise ValueError('Fixed-mixture optimization failed: ' + solution.message)
    probabilities = np.maximum(solution.x, 0)
    return probabilities / probabilities.sum()


def select_operating_point(pred, validation_y, train_y, scales, delta=0.):
    """Validation selects cost minimum with paired Q and L confidence gates.

    Always include train-selected quality Best Single as the exact fallback.
    This is a validation criterion, never a finite-sample test guarantee.
    """
    baseline = int(train_y[:, :, 0].mean(0).argmax())
    base = validation_y[:, baseline]
    candidates = []
    for idx, pref in enumerate(GRID):
        actual = chosen(validation_y, route(pred, pref, scales))
        q_ci = paired_ci(actual[:, 0] - base[:, 0])
        l_ci = paired_ci(actual[:, 2] - base[:, 2])
        eligible = q_ci[0] >= -delta and l_ci[1] <= 0
        candidates.append(dict(grid_index=idx, quality_delta_ci95=q_ci,
                               latency_delta_ci95=l_ci, eligible=bool(eligible),
                               cost=float(actual[:, 1].mean())))
    eligible = [v for v in candidates if v['eligible'] and v['cost'] < base[:, 1].mean()]
    selected = min(eligible, key=lambda v: (v['cost'], v['grid_index'])) if eligible else None
    return dict(kind='grid' if selected else 'best_single',
                grid_index=selected['grid_index'] if selected else None,
                baseline_slot=baseline, delta=delta, candidates=candidates)


def evaluate_policy(y, decisions, train_y, pref, scales):
    actual = chosen(y, decisions)
    true_u = utility(y, pref, scales)
    baseline = int(utility(train_y, pref, scales).mean(0).argmax())
    router_u = utility(actual[:, None, :], pref, scales)[:, 0]
    gain = router_u - true_u[:, baseline]
    oracle_gap = float((true_u.max(1) - true_u[:, baseline]).mean())
    return dict(quality=float(actual[:, 0].mean()), cost=float(actual[:, 1].mean()),
                latency_ms=float(actual[:, 2].mean()), utility=float(router_u.mean()),
                best_single_slot=SLOTS[baseline], utility_gain=float(gain.mean()),
                utility_gain_ci95=paired_ci(gain), oracle_gap=oracle_gap,
                gap_recovery=float(gain.mean()/oracle_gap) if oracle_gap > 1e-12 else None)


def constrained_metrics(y, decisions, baseline, delta):
    actual = chosen(y, decisions)
    base = y[:, baseline]
    qci = paired_ci(actual[:, 0] - base[:, 0])
    cci = paired_ci(base[:, 1] - actual[:, 1])
    lci = paired_ci(actual[:, 2] - base[:, 2])
    base_cost = float(base[:, 1].mean())
    return dict(quality_delta=float((actual[:, 0]-base[:, 0]).mean()),
                quality_delta_ci95=qci, cost_saving_ci95=cci, latency_delta_ci95=lci,
                cost_saving_fraction=1-float(actual[:, 1].mean())/base_cost if base_cost > 0 else None,
                passes_quality=bool(qci[0] >= -delta), passes_cost=bool(cci[0] > 0),
                passes_latency=bool(lci[1] <= 0),
                all_three_pass=bool(qci[0] >= -delta and cci[0] > 0 and lci[1] <= 0))
