"""Cross-fitted off-policy estimators for the frozen randomized E4 design."""

from __future__ import annotations

import numpy as np


def validate_inputs(actions, policy_actions, rewards, q_observed, q_policy, propensity):
    arrays = [np.asarray(x) for x in (actions, policy_actions, rewards, q_observed, q_policy)]
    n = len(arrays[0])
    if any(len(x) != n for x in arrays):
        raise ValueError("all OPE arrays must have the same length")
    if not 0 < propensity <= 1:
        raise ValueError("propensity must be in (0, 1]")
    if not all(np.all(np.isfinite(x)) for x in arrays[2:]):
        raise ValueError("rewards and predictions must be finite")
    return arrays


def dr_contributions(actions, policy_actions, rewards, q_observed, q_policy, propensity=0.25):
    """Per-decision cross-fitted doubly-robust contributions."""
    a, pi, y, q_a, q_pi = validate_inputs(
        actions, policy_actions, rewards, q_observed, q_policy, propensity
    )
    matched = (a == pi).astype(float)
    return q_pi + matched / propensity * (y - q_a)


def ips_contributions(actions, policy_actions, rewards, propensity=0.25):
    a, pi, y = np.asarray(actions), np.asarray(policy_actions), np.asarray(rewards, dtype=float)
    if not (len(a) == len(pi) == len(y)) or not 0 < propensity <= 1:
        raise ValueError("invalid IPS inputs")
    return (a == pi).astype(float) * y / propensity


def snips_value(actions, policy_actions, rewards, propensity=0.25):
    a, pi, y = np.asarray(actions), np.asarray(policy_actions), np.asarray(rewards, dtype=float)
    weights = (a == pi).astype(float) / propensity
    if weights.sum() == 0:
        return float("nan")
    return float(np.sum(weights * y) / np.sum(weights))


def effective_sample_size(actions, policy_actions, propensity=0.25):
    weights = (np.asarray(actions) == np.asarray(policy_actions)).astype(float) / propensity
    return float(weights.sum() ** 2 / np.sum(weights ** 2)) if np.sum(weights ** 2) else 0.0


def aggregate_by_group(values, groups):
    values, groups = np.asarray(values, dtype=float), np.asarray(groups)
    unique = np.unique(groups)
    return unique, np.asarray([values[groups == group].mean() for group in unique])


def paired_group_bootstrap(left, right, groups, replicates=10000, seed=20260905):
    """Bootstrap the paired mean difference at the leakage-group level."""
    unique, lmeans = aggregate_by_group(left, groups)
    runique, rmeans = aggregate_by_group(right, groups)
    if not np.array_equal(unique, runique):
        raise ValueError("group mismatch")
    delta = lmeans - rmeans
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates)
    for i in range(replicates):
        draws[i] = rng.choice(delta, len(delta), replace=True).mean()
    return {
        "estimate": float(delta.mean()),
        "ci95": [float(x) for x in np.percentile(draws, [2.5, 97.5])],
        "groups": int(len(unique)),
        "replicates": int(replicates),
    }

