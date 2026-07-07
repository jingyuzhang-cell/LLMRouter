"""Lightweight batch schedulers for LLM routing experiments.

The schedulers in this package optimize a batch-level model assignment under
budget, latency, quality, reliability, and load-balance constraints. They are
kept independent from the HTTP server so experiments can reuse them without
pulling in FastAPI or provider clients.
"""

from .constraints import BatchConstraints
from .solver import SchedulerType, solve_batch_assignment

__all__ = ["BatchConstraints", "SchedulerType", "solve_batch_assignment"]
