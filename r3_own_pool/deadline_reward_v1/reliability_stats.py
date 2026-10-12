"""Frozen statistical toolkit for the deadline-reliability experiment
(DEADLINE_RELIABILITY_PROTOCOL_V3). Zero model calls; pure statistics.

The real measurement MUST use THESE audited implementations — no
re-implementation drift between admission testing and the run.

  cp_lower_bound / cp_upper_bound — exact Clopper–Pearson bounds
  acceptance_region_poisson_binomial — exact two-sided acceptance region
      for a sum of heterogeneous Bernoullis (per-task predicted p_on),
      via exact DP (Poisson-binomial); no normal approximation anywhere
  p90_coverage — empirical coverage of a declared P90 quantile
  d_tier_on_time_verdict — realized on-time count vs the exact
      acceptance region under the ex-ante predicted probabilities
  sample_size_table — the frozen minimum-n table for CP lower bound
      >= target at perfect/near-perfect coverage

Frozen directions (operator task 1.4): one-sided LOWER bound at
alpha = 0.05 for coverage acceptance (H0: coverage < 0.90 is only
rejected when the exact lower bound reaches 0.90); two-sided exact
acceptance region for on-time calibration (tolerance expressed as the
region itself, never as a fixed band).
"""
from __future__ import annotations

from math import comb
from typing import Dict, List, Sequence, Tuple

ALPHA = 0.05
COVERAGE_TARGET = 0.90


def cp_lower_bound(x: int, n: int, alpha: float = ALPHA) -> float:
    """Exact one-sided Clopper–Pearson lower bound (quantile of
    Beta(x, n-x+1)); 0.0 when x == 0."""
    if n <= 0:
        raise ValueError('n must be positive')
    if x <= 0:
        return 0.0
    from scipy.stats import beta
    return float(beta.ppf(alpha, x, n - x + 1))


def cp_upper_bound(x: int, n: int, alpha: float = ALPHA) -> float:
    if n <= 0:
        raise ValueError('n must be positive')
    if x >= n:
        return 1.0
    from scipy.stats import beta
    return float(beta.ppf(1 - alpha, x + 1, n - x))


def poisson_binomial_pmf(probs: Sequence[float]) -> List[float]:
    """Exact pmf of a sum of independent Bernoullis with heterogeneous
    probabilities (exact DP; O(n^2), no approximation)."""
    pmf = [1.0]
    for p in probs:
        p = float(p)
        if not (0.0 <= p <= 1.0):
            raise ValueError(f'probability out of range: {p}')
        nxt = [0.0] * (len(pmf) + 1)
        for k, q in enumerate(pmf):
            nxt[k] += q * (1.0 - p)
            nxt[k + 1] += q * p
        pmf = nxt
    return pmf


def acceptance_region_poisson_binomial(probs: Sequence[float],
                                       alpha: float = ALPHA
                                       ) -> Tuple[int, int]:
    """Exact two-sided acceptance region [lo, hi] for the realized count
    of on-time tasks under the ex-ante predicted probabilities: the
    highest-probability set with total mass >= 1 - alpha (ordered by
    probability mass, ties by proximity to the mean) — the standard
    exact-test construction. Realized counts outside [lo, hi] reject
    calibration at level alpha."""
    pmf = poisson_binomial_pmf(probs)
    n = len(pmf) - 1
    order = sorted(range(n + 1), key=lambda k: (-pmf[k], abs(k - sum(probs))))
    keep = set()
    mass = 0.0
    for k in order:
        keep.add(k)
        mass += pmf[k]
        if mass >= 1.0 - alpha:
            break
    return min(keep), max(keep)


def p90_coverage(samples: Sequence[float], declared_p90: float) -> dict:
    """Empirical coverage of a declared P90 + the exact CP lower bound
    and the formal verdict (lower bound >= 0.90)."""
    if not samples:
        return dict(n=0, covered=0, coverage=None, cp_lower=None,
                    verdict='NO_SAMPLES')
    covered = sum(1 for s in samples if s <= declared_p90)
    n = len(samples)
    lb = cp_lower_bound(covered, n)
    return dict(n=n, covered=covered, coverage=covered / n,
                cp_lower=round(lb, 4),
                verdict='PASS' if lb >= COVERAGE_TARGET
                else ('CONDITIONAL' if covered / n >= COVERAGE_TARGET
                      else 'FAIL'))


def d_tier_on_time_verdict(realized_on_time: int, n_tasks: int,
                           predicted_probs: Sequence[float],
                           alpha: float = ALPHA) -> dict:
    """On-time calibration verdict at one D-tier: the realized count of
    on-time tasks must fall inside the exact Poisson-binomial acceptance
    region computed from the EX-ANTE predicted probabilities."""
    lo, hi = acceptance_region_poisson_binomial(predicted_probs, alpha)
    ok = lo <= realized_on_time <= hi
    return dict(n=n_tasks, realized=realized_on_time, region=[lo, hi],
                mean_predicted=round(sum(predicted_probs) / n_tasks, 4)
                if n_tasks else None,
                verdict='PASS' if ok else 'FAIL')


def sample_size_table(targets=(0.90,), coverages=(1.0, 0.97, 0.95, 0.93),
                      max_n: int = 400) -> Dict[float, Dict[float, int]]:
    """Minimum n such that the CP lower bound >= target at the given
    observed coverage fraction (exact search). Perfect coverage 1.0 with
    target .90 needs n=29; 0.95 needs ~110; 0.93 needs ~200 — the honest
    arithmetic that sizes the validation panel."""
    out = {}
    for target in targets:
        row = {}
        for cov in coverages:
            found = None
            for n in range(1, max_n + 1):
                x = int(cov * n + 1e-9)
                if cp_lower_bound(x, n) >= target:
                    found = n
                    break
            row[cov] = found      # None = not achievable <= max_n
        out[target] = row
    return out


def coverage_from_ledger(samples_by_cell: Dict[str, Sequence[float]],
                         declared: Dict[str, float]) -> Dict[str, dict]:
    """Per-cell P90 coverage + the frozen joint acceptance rule:
    PASS requires every cell's exact CP lower bound >= 0.90; a cell with
    point coverage >= 0.90 but a lower bound below is CONDITIONAL (n
    extension via the staged path), never a PASS."""
    cells = {c: p90_coverage(s, declared[c])
             for c, s in samples_by_cell.items() if s}
    missing = [c for c in declared if c not in cells]
    joint = ('PASS' if cells and not missing
             and all(v['verdict'] == 'PASS' for v in cells.values())
             else ('CONDITIONAL' if not missing and cells and all(
                 v['verdict'] in ('PASS', 'CONDITIONAL')
                 for v in cells.values()) else 'FAIL'))
    return dict(cells=cells, missing_cells=missing, joint_verdict=joint)


__all__ = ['ALPHA', 'COVERAGE_TARGET', 'acceptance_region_poisson_'
           'binomial', 'coverage_from_ledger', 'cp_lower_bound',
           'cp_upper_bound', 'd_tier_on_time_verdict', 'p90_coverage',
           'poisson_binomial_pmf', 'sample_size_table']
