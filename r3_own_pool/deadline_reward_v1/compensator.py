"""M6 — deadline compensator: unified time accounting, no double charge.

Owns exactly one time ingredient: model-switch overhead (plus the safety
margin). Service demand belongs to the predictor; idle/gap time belongs to
the injected clock. The POLICY composes μ_E2E = μ_service + switch_overhead
once before E1 (reward doc §3.3a); B6-style single counting is asserted by
tests.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple


class DeadlineCompensator:
    def __init__(self, priors: dict) -> None:
        sw = priors['switch']
        self.stop_s = float(sw['stop_s'])
        self.start_s = dict(sw['start_s'])
        pol = priors.get('policy', {})
        self.safety_margin_s = float(pol.get('safety_margin_s', 0.0))

    def switch_overhead(self, current_model: Optional[str],
                        ordered_models: Iterable[str]) -> float:
        """Cost of the model transitions the plan's execution order needs.
        Cold start (from None) charges start only — mirroring the engine's
        switch events."""
        cost = 0.0
        cur = current_model
        for m in ordered_models:
            if m is None or m == cur:
                continue
            cost += self.start_s.get(m, 0.0) if cur is None \
                else self.stop_s + self.start_s.get(m, 0.0)
            cur = m
        return cost

    @staticmethod
    def d_remain(state, uid: str) -> float:
        """Remaining deadline, computed LIVE from clock + task deadline."""
        return state.task_deadlines[uid] - state.clock.time()

    @staticmethod
    def b_remain(state) -> Dict[str, Optional[float]]:
        """Remaining budget from real spend — never a stored constant."""
        b = state.budget()
        return dict(tokens=b['b_remain_tokens'],
                    requests=b['b_remain_requests'])
