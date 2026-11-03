"""feedback_joint_controller — A+B+C unified: feedback-aware joint
Q/C/L constrained controller for DAG dynamic scheduling (v fjc-v1).

Replaces the naive "pick GLM if q > flash_q" with:
  A. Joint utility: U(a) = w_Q * Q̂ - w_C * Ĉ/C_max - w_L * L̂/D_remaining
  B. Budget from task constraints (not artificial)
  C. Node-type-level capability profiles updated from real feedback

The controller:
  1. Maintains per-(node_type, model) capability estimates with uncertainty
  2. On anomaly, enumerates legal (Z, R, π) candidates
  3. Scores each candidate by joint utility (A) under real constraints (B)
  4. Selects argmax; feedback updates capability estimates (C)
  5. Logs the decision rationale (including "kept same action because
     it remains optimal under updated estimates")

Zero model calls in this module — the controller plans; the runner executes.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---- C: Node-type-level capability profiles with uncertainty --------------

@dataclass
class CapabilityEstimate:
    """Per (node_type, model): quality, cost, latency, reliability.
    Updated from real execution feedback with Bayesian shrinkage."""
    n_obs: int = 0
    q_sum: float = 0.0        # quality observations
    c_sum: float = 0.0        # cost (tokens) observations
    l_sum: float = 0.0        # latency observations
    r_sum: int = 0            # reliability (contract pass) observations
    r_n: int = 0              # total reliability observations
    # Prior (from frozen profile or cold start)
    prior_q: float = 0.5
    prior_c: float = 800.0
    prior_l: float = 5.0
    prior_r: float = 0.9

    @property
    def q_hat(self) -> float:
        """Posterior mean quality with shrinkage toward prior."""
        alpha = 2.0  # prior strength
        return (self.q_sum + alpha * self.prior_q) / (self.n_obs + alpha)

    @property
    def c_hat(self) -> float:
        return (self.c_sum + 2.0 * self.prior_c) / (self.n_obs + 2.0)

    @property
    def l_hat(self) -> float:
        return (self.l_sum + 2.0 * self.prior_l) / (self.n_obs + 2.0)

    @property
    def r_hat(self) -> float:
        return (self.r_sum + 2.0 * self.prior_r) / (self.r_n + 2.0)

    @property
    def q_se(self) -> float:
        """Standard error of quality estimate (for uncertainty-aware)."""
        if self.n_obs < 2:
            return 0.15  # high uncertainty with few observations
        mean = self.q_sum / self.n_obs
        var = sum((self.q_sum / self.n_obs - x)**2
                  for x in [self.q_sum / self.n_obs] * self.n_obs) / (self.n_obs - 1)
        # Simplified: use coefficient of variation
        return max(0.05, 0.3 / math.sqrt(self.n_obs))

    def update(self, q: float, c: float, l: float, reliable: bool):
        self.n_obs += 1
        self.q_sum += q
        self.c_sum += c
        self.l_sum += l
        self.r_n += 1
        self.r_sum += int(reliable)


class CapabilityProfile:
    """Collection of per-(node_type, model) estimates + update from feedback."""

    def __init__(self, frozen: Dict = None):
        self.estimates: Dict[Tuple[str, str], CapabilityEstimate] = {}
        if frozen:
            for (nt, m), params in frozen.items():
                self.estimates[(nt, m)] = CapabilityEstimate(**params)

    def q_hat(self, node_type: str, model: str) -> float:
        e = self.estimates.get((node_type, model))
        if e is None:
            return 0.5
        return e.q_hat

    def c_hat(self, node_type: str, model: str) -> float:
        e = self.estimates.get((node_type, model))
        if e is None:
            return 800.0
        return e.c_hat

    def l_hat(self, node_type: str, model: str) -> float:
        e = self.estimates.get((node_type, model))
        if e is None:
            return 5.0
        return e.l_hat

    def r_hat(self, node_type: str, model: str) -> float:
        e = self.estimates.get((node_type, model))
        if e is None:
            return 0.9
        return e.r_hat

    def update_from_execution(self, node_type: str, model: str,
                               quality: float, tokens: float,
                               latency: float, contract_ok: bool):
        key = (node_type, model)
        if key not in self.estimates:
            self.estimates[key] = CapabilityEstimate()
        self.estimates[key].update(quality, tokens, latency, contract_ok)

    def summary(self) -> Dict:
        return {f"{nt}|{m}": dict(
            n_obs=e.n_obs, q_hat=round(e.q_hat, 3), c_hat=round(e.c_hat),
            l_hat=round(e.l_hat, 1), r_hat=round(e.r_hat, 2))
            for (nt, m), e in self.estimates.items()}


# ---- A: Joint Q/C/L utility optimization -----------------------------------

@dataclass
class Constraints:
    """Real task constraints (from task contract, not artificial)."""
    budget_tokens: float = 5000.0
    deadline_s: float = 140.0
    budget_cash: float = 0.0  # subscription = 0 marginal

@dataclass
class JointWeights:
    """Frozen joint utility weights (do NOT tune post-hoc)."""
    w_Q: float = 1.0   # quality weight
    w_C: float = 0.5   # cost penalty weight (token budget fraction)
    w_L: float = 0.5   # latency penalty weight (deadline fraction)


def plan_utility(profile: CapabilityProfile,
                 weights: JointWeights,
                 constraints: Constraints,
                 remaining_nodes: List[Tuple[str, str]],  # (node_id, node_type)
                 pi: Dict[str, str],                      # node_id -> model
                 spent_tokens: float = 0.0,
                 spent_latency: float = 0.0,
                 spent_cash: float = 0.0) -> Tuple[float, Dict]:
    """Joint utility of executing remaining_nodes under assignment pi.

    Returns (utility, detail) where detail explains the decision.
    """
    q_total = 0.0
    c_total = spent_tokens
    l_total = spent_latency
    cash_total = spent_cash

    for nid, ntype in remaining_nodes:
        m = pi.get(nid, 'glm53flash')
        m_key = m.replace('glm53flash', 'flash')
        # Expected quality weighted by reliability
        q = profile.q_hat(ntype, m_key) * profile.r_hat(ntype, m_key)
        q_total += q
        # Incremental cost
        c_total += profile.c_hat(ntype, m_key)
        # Incremental latency
        l_total += profile.l_hat(ntype, m_key)

    n = max(1, len(remaining_nodes))
    q_avg = q_total / n
    c_frac = c_total / max(1, constraints.budget_tokens)
    l_frac = l_total / max(1, constraints.deadline_s)

    utility = (weights.w_Q * q_avg
               - weights.w_C * c_frac
               - weights.w_L * min(1.0, l_frac))

    # Feasibility check
    feasible = (c_total <= constraints.budget_tokens
                and l_total <= constraints.deadline_s
                and cash_total <= constraints.budget_cash + 1e-9)
    if not feasible:
        utility = -9.0

    detail = dict(
        q_avg=round(q_avg, 3), c_total=round(c_total), l_total=round(l_total, 1),
        c_frac=round(c_frac, 3), l_frac=round(l_frac, 3),
        utility=round(utility, 4), feasible=feasible)
    return utility, detail


def optimize_pi(profile: CapabilityProfile,
                weights: JointWeights,
                constraints: Constraints,
                remaining_nodes: List[Tuple[str, str]],
                spent: Dict = None) -> Tuple[Dict[str, str], Dict]:
    """Joint optimization: try all model assignments for remaining nodes.
    For small DAGs (≤6 remaining nodes × 2 models), exhaustive is feasible.
    """
    spent = spent or dict(tokens=0.0, latency=0.0, cash=0.0)
    models = ['glm53', 'flash']
    best_pi, best_u, best_detail = None, -99, None

    if len(remaining_nodes) <= 6:
        # Exhaustive: 2^n combinations (max 64 for 6 nodes)
        import itertools
        for combo in itertools.product(models, repeat=len(remaining_nodes)):
            pi = {nid: m for (nid, _), m in zip(remaining_nodes, combo)}
            u, detail = plan_utility(profile, weights, constraints,
                                     remaining_nodes, pi,
                                     spent_tokens=spent.get('tokens',0),
                                     spent_latency=spent.get('latency',0),
                                     spent_cash=spent.get('cash',0))
            if u > best_u:
                best_u, best_pi, best_detail = u, pi, detail
    else:
        # Greedy fallback for larger DAGs
        pi = {}
        for nid, ntype in remaining_nodes:
            best_m, best_mu = None, -99
            for m in models:
                pi[nid] = m
                u, _ = plan_utility(profile, weights, constraints,
                                    remaining_nodes, pi,
                                    spent_tokens=spent.get('tokens',0),
                                    spent_latency=spent.get('latency',0),
                                    spent_cash=spent.get('cash',0))
                if u > best_mu:
                    best_mu, best_m = u, m
            pi[nid] = best_m
        best_pi = pi
        best_u, best_detail = plan_utility(profile, weights, constraints,
                                           remaining_nodes, pi,
                                           spent_tokens=spent.get('tokens',0),
                                           spent_latency=spent.get('latency',0),
                                           spent_cash=spent.get('cash',0))

    return best_pi, best_detail


# ---- Full controller: anomaly → enumerate (Z,R,π) → joint optimize --------

def decide(profile: CapabilityProfile,
           weights: JointWeights,
           constraints: Constraints,
           remaining_nodes: List[Tuple[str, str]],
           failed_nodes: Set[str],
           spent: Dict,
           z_candidates: List[Tuple[str, any]] = None) -> Dict:
    """Full joint decision: enumerate (Z, R, π) candidates, pick argmax U."""
    z_candidates = z_candidates or [('IDENTITY', None)]
    best = dict(utility=-99, z='IDENTITY', R=set(), pi={}, detail={})

    for z_name, z_spec in z_candidates:
        # R candidates: subsets of failed closure
        import itertools
        failed_list = sorted(failed_nodes)
        for r_size in range(len(failed_list) + 1):
            for R in itertools.combinations(failed_list, r_size):
                R_set = set(R)
                # Remaining = nodes not yet done and not in R (they'll re-execute)
                exec_nodes = [(nid, nt) for nid, nt in remaining_nodes
                              if nid in R_set or nid not in failed_nodes]
                pi, detail = optimize_pi(profile, weights, constraints,
                                         exec_nodes, spent)
                if detail['utility'] > best['utility']:
                    best = dict(utility=detail['utility'], z=z_name,
                                R=R_set, pi=pi, detail=detail)

    best['decision_rationale'] = (
        f"Chose {best['z']} with R={sorted(best['R'])} because "
        f"utility={best['utility']:.4f} (Q̂={best['detail'].get('q_avg', '?')}, "
        f"C={best['detail'].get('c_total', '?')}/{constraints.budget_tokens}, "
        f"L={best['detail'].get('l_total', '?')}/{constraints.deadline_s:.0f}s)")
    return best


# ---- Demo: frozen vs feedback profiles now produce different decisions -----

if __name__ == '__main__':
    # Frozen profile (original estimates)
    frozen = CapabilityProfile({
        ('index', 'glm53'): dict(prior_q=0.85, prior_c=643, prior_l=4.1),
        ('index', 'flash'): dict(prior_q=0.62, prior_c=1063, prior_l=5.2),
        ('extracts', 'glm53'): dict(prior_q=0.85, prior_c=2783, prior_l=6.2),
        ('extracts', 'flash'): dict(prior_q=0.62, prior_c=1063, prior_l=6.7),
        ('timeline', 'glm53'): dict(prior_q=0.75, prior_c=882, prior_l=4.1),
        ('timeline', 'flash'): dict(prior_q=0.60, prior_c=1063, prior_l=3.7),
        ('entity_facts', 'glm53'): dict(prior_q=0.80, prior_c=882, prior_l=6.0),
        ('entity_facts', 'flash'): dict(prior_q=0.58, prior_c=1063, prior_l=6.8),
        ('factcheck', 'glm53'): dict(prior_q=0.83, prior_c=1362, prior_l=4.3),
        ('factcheck', 'flash'): dict(prior_q=0.80, prior_c=1063, prior_l=5.2),
        ('report', 'glm53'): dict(prior_q=0.85, prior_c=1051, prior_l=4.8),
        ('report', 'flash'): dict(prior_q=0.60, prior_c=1063, prior_l=6.7),
    })

    # Feedback profile: updated from Stage-B/C real data
    # Key changes: Flash report quality drops (cite=0.00), Flash cost 1.5x
    feedback = CapabilityProfile({
        ('index', 'glm53'): dict(prior_q=0.85, prior_c=643, prior_l=4.1),
        ('index', 'flash'): dict(prior_q=0.65, prior_c=1595, prior_l=6.2),
        ('extracts', 'glm53'): dict(prior_q=0.85, prior_c=2783, prior_l=6.2),
        ('extracts', 'flash'): dict(prior_q=0.65, prior_c=1595, prior_l=8.0),
        ('timeline', 'glm53'): dict(prior_q=0.75, prior_c=882, prior_l=4.1),
        ('timeline', 'flash'): dict(prior_q=0.58, prior_c=1595, prior_l=4.4),
        ('entity_facts', 'glm53'): dict(prior_q=0.80, prior_c=882, prior_l=6.0),
        ('entity_facts', 'flash'): dict(prior_q=0.55, prior_c=1595, prior_l=8.2),
        ('factcheck', 'glm53'): dict(prior_q=0.83, prior_c=1362, prior_l=4.3),
        ('factcheck', 'flash'): dict(prior_q=0.72, prior_c=1595, prior_l=6.2),
        ('report', 'glm53'): dict(prior_q=0.85, prior_c=1051, prior_l=4.8),
        ('report', 'flash'): dict(prior_q=0.50, prior_c=1595, prior_l=8.0),
    })

    weights = JointWeights(w_Q=1.0, w_C=0.5, w_L=0.5)
    constraints = Constraints(budget_tokens=8000, deadline_s=140.0)
    nodes = [('f3', 'timeline'), ('f4', 'entity_facts'),
             ('f5', 'factcheck'), ('f6', 'report')]
    spent = dict(tokens=2000, latency=30.0, cash=0.0)

    for name, prof in [('FROZEN', frozen), ('FEEDBACK', feedback)]:
        pi, detail = optimize_pi(prof, weights, constraints, nodes, spent)
        print(f"\n{name}:")
        print(f"  π = {pi}")
        print(f"  detail = {detail}")
        # Show per-node utility comparison
        for nid, nt in nodes:
            for m in ('glm53', 'flash'):
                e = prof.estimates.get((nt, m))
                if e:
                    print(f"    {nid}({nt}) {m}: q̂={e.q_hat:.3f} "
                          f"ĉ={e.c_hat:.0f} l̂={e.l_hat:.1f}")
