"""Worst-case budget guard for real-API experiment rounds.

R2 incident (2026-10-24, run r2_20261024_233337): the old pre-check
tolerance (¥0.01) was below the actual per-call cost (¥0.014), so the
last admitted call pushed the total to ¥0.1940 against a ¥0.19 cap.
Discipline fix per operator directive (2026-10-24): a call may start
ONLY if the remaining budget covers the WORST-CASE cost of that single
call, computed BEFORE dispatch; settlement is never the safety net.

Two modes:
  uniform    — constructor verifies planned_calls x worst_case <= cap
               (guarantees the plan can complete under worst costs).
  adaptive   — each may_start(prompt_chars=...) computes the bound from
               the actual prompt: worst = (prompt_chars*TOK_PER_CHAR +
               MAX_OUT_TOKENS) priced. Precise; the guard may stop early
               on unlucky cost patterns but provably never exceeds cap.

Pricing: deepseek-flash, CNY 2.13/M input, 8.52/M output
(REVERSE_ENGINEERED_RATES_V2, same as all prior rounds).

Usage:
    g = BudgetGuard(planned_calls=18, cap_cash_cny=0.30, mode='adaptive')
    stop = g.may_start(prompt_chars=len(prompt))
    if stop: raise RuntimeError(f'budget stop: {stop}')
    ... real call ...
    g.record(resp_cash)
"""
from __future__ import annotations

import time

CNY_PER_TOK_IN = 2.13e-6
CNY_PER_TOK_OUT = 8.52e-6
TOK_PER_CHAR = 0.75      # generous upper bound for Chinese + JSON mix
MAX_OUT_TOKENS = 2048    # deepseek-flash max_tokens used by the runner


def worst_case_cny(prompt_chars: int, max_out_tokens: int = MAX_OUT_TOKENS,
                   tok_per_char: float = TOK_PER_CHAR) -> float:
    """Provable single-call cost bound BEFORE dispatch."""
    tok_in_ub = prompt_chars * tok_per_char + 64   # + message boilerplate
    cost = tok_in_ub * CNY_PER_TOK_IN + max_out_tokens * CNY_PER_TOK_OUT
    return round(cost, 6)


class BudgetGuard:
    def __init__(self, planned_calls: int, cap_cash_cny: float,
                 mode: str = 'adaptive',
                 worst_case_cny: float | None = None,
                 wall_seconds: float = 1800.0):
        if mode not in ('uniform', 'adaptive'):
            raise ValueError(f'unknown mode {mode!r}')
        self.mode = mode
        self.planned_calls = planned_calls
        self.cap_cash_cny = cap_cash_cny
        self.wall_seconds = wall_seconds
        self.calls = 0
        self.spent = 0.0
        self.max_single = 0.0
        self.max_admitted_worst = 0.0
        self.start = time.monotonic()
        if mode == 'uniform':
            if not worst_case_cny or worst_case_cny <= 0:
                raise ValueError('uniform mode requires worst_case_cny')
            if planned_calls * worst_case_cny > cap_cash_cny + 1e-12:
                raise ValueError(
                    f'infeasible: {planned_calls} calls x worst '
                    f'¥{worst_case_cny:.4f} = '
                    f'¥{planned_calls * worst_case_cny:.4f} > cap '
                    f'¥{cap_cash_cny} — guard could only stop early')
            self.default_worst = worst_case_cny
        else:
            self.default_worst = None

    def may_start(self, prompt_chars: int | None = None,
                  max_out_tokens: int = MAX_OUT_TOKENS):
        """None if the next call is safely affordable, else reason."""
        if self.calls >= self.planned_calls:
            return f'calls cap ({self.planned_calls})'
        if self.mode == 'adaptive':
            if prompt_chars is None:
                raise ValueError('adaptive mode requires prompt_chars')
            worst = worst_case_cny(prompt_chars, max_out_tokens)
        else:
            worst = self.default_worst
        if self.spent + worst > self.cap_cash_cny + 1e-12:
            return (f'cash guard: spent ¥{self.spent:.4f} + worst '
                    f'¥{worst:.4f} > cap ¥{self.cap_cash_cny}')
        if time.monotonic() - self.start > self.wall_seconds:
            return 'wall clock cap'
        self.max_admitted_worst = max(self.max_admitted_worst, worst)
        return None

    def record(self, cash_cny: float):
        self.calls += 1
        self.spent += float(cash_cny)
        self.max_single = max(self.max_single, float(cash_cny))

    def snapshot(self):
        return dict(mode=self.mode, calls=self.calls,
                    spent_cny=round(self.spent, 6),
                    max_single_cny=round(self.max_single, 6),
                    max_admitted_worst_cny=round(
                        self.max_admitted_worst, 6),
                    cap_cash_cny=self.cap_cash_cny,
                    planned_calls=self.planned_calls)
