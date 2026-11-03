"""cash_guard.py — Hard cash budget enforcement (pre-call admission).

Implements: C_spent + C_worst_remaining_path ≤ C_cap BEFORE any request.
If violated → refuse action or trigger legal degradation (Flash fallback).
"""
from dataclasses import dataclass, field


@dataclass
class CashGuard:
    """Per-arm cash budget with conservative pre-call admission."""
    cap: float
    spent: float = 0.0
    call_log: list = field(default_factory=list)

    # Worst-case DS cost per node (calibrated from real peak-price ledger)
    DS_WORST = {
        'n_main': 0.0077, 'n_sup1': 0.0077, 'n_sup2': 0.0077,
        'verify': 0.0098, 'sink': 0.0165,
    }
    FLASH_COST = 0.0  # subscription

    def remaining(self) -> float:
        return self.cap - self.spent

    def worst_cost(self, node: str, model: str) -> float:
        if model == 'DS':
            return self.DS_WORST.get(node, 0.020)  # conservative default
        return self.FLASH_COST

    def can_afford_next(self, node: str, model: str) -> bool:
        """Check if a SINGLE next call fits within budget."""
        return self.spent + self.worst_cost(node, model) <= self.cap

    def can_afford_plan(self, remaining_nodes: list, pi: dict) -> bool:
        """Check if the ENTIRE remaining execution plan fits within budget.
        Prevents spending all cash on verify then having none for sink."""
        total_worst = sum(self.worst_cost(n, pi.get(n, 'Flash')) for n in remaining_nodes)
        return self.spent + total_worst <= self.cap

    def admit(self, node: str, model: str, remaining_after: list, pi: dict) -> tuple:
        """Pre-call admission check. Returns (allowed, action_or_fallback).

        If the requested model can't be afforded, falls back to Flash (free).
        If even the full remaining plan exceeds budget, degrades R (skips repair).
        """
        # Check single call
        if not self.can_afford_next(node, model):
            if model == 'DS':
                # Try Flash fallback for this node
                if self.can_afford_next(node, 'Flash'):
                    return False, ('fallback', node, 'Flash')
                return False, ('refuse', node)
            return False, ('refuse', node)

        # Check full remaining plan (including this call)
        all_remaining = [node] + remaining_after
        if not self.can_afford_plan(all_remaining, pi):
            # Plan exceeds budget → need to degrade somewhere
            if model == 'DS':
                # Try Flash for this node to save budget for downstream
                pi_copy = dict(pi)
                pi_copy[node] = 'Flash'
                if self.can_afford_plan(all_remaining, pi_copy):
                    return False, ('fallback', node, 'Flash')
            # Can't afford full plan even with Flash here → refuse repair
            return False, ('degrade_R', node)

        return True, ('proceed', node, model)

    def record(self, node: str, model: str, actual_cost: float):
        """Record actual cost after call completes."""
        self.spent += actual_cost
        self.call_log.append({
            'node': node, 'model': model,
            'worst_est': self.worst_cost(node, model),
            'actual': actual_cost,
            'cumulative': round(self.spent, 6),
            'over_budget': self.spent > self.cap,
        })

    def summary(self):
        return {
            'cap': self.cap,
            'spent': round(self.spent, 6),
            'remaining': round(self.remaining(), 6),
            'calls': len(self.call_log),
            'compliant': self.spent <= self.cap,
        }
