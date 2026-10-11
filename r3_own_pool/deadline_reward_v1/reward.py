"""M6 — task-level reward: R_task and its conditional expectation.

R_task = 1(T≤D)·q − λc·C/C₀ − λt·(T−D)₊/D − λf·1(T>D)      (frozen form)

Cost口径 (operator ruling): DECISION-TIME comparison uses C_new (the
incremental cost from the decision onward — the only part any action
controls; already-spent is common to all candidates); SETTLEMENT records
the FULL episode cost C_full. Both are recorded separately and never mix.
Gold enters ONLY settlement (the scorer reads task['answer']); the policy
and predictor never see it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


def realized_rtask(*, q: float, c_full: float, T: float, D: float,
                   lam_c: float, lam_t: float, lam_f: float,
                   c0: float) -> float:
    if c0 <= 0:
        raise ValueError('C0 must be strictly positive')
    on_time = 1.0 if T <= D else 0.0
    late = max(0.0, T - D)
    return (on_time * q - lam_c * c_full / c0
            - lam_t * late / D - lam_f * (1.0 - on_time))


def expected_rtask(*, q_hat: float, d_cost: float, p_on_time: float,
                   e_late: float, d_remain: float, lam_c: float,
                   lam_t: float, lam_f: float, c0: float) -> float:
    """Ê[R_task] with C_new semantics: only the decision-controllable
    incremental cost enters (spent-so-far is identical across candidates)."""
    if c0 <= 0:
        raise ValueError('C0 must be strictly positive')
    return (p_on_time * q_hat - lam_c * d_cost / c0
            - lam_t * e_late / d_remain - lam_f * (1.0 - p_on_time))


def settle(engine, state, tasks, *, lam_c: float, lam_t: float,
           lam_f: float, c0: float, session_bonus: float = 1.0,
           session_penalty: float = 2.0) -> Dict:
    """Terminal settlement: realized R_task per task (gold HERE only),
    full-cost accounting, one session terminal term. Appends REWARDS.jsonl
    in the engine directory and returns the settlement record."""
    rewards = []
    for t in tasks:
        uid = t['uid']
        st = state.tasks[uid]
        from . import detection as det
        vv = det.json_value(st.answers.get('v', ''))
        gold = t.get('answer')
        q = 1.0 if (vv is not None and gold is not None
                    and det.close(vv, gold)) else 0.0
        T = ((st.completion_time if st.completion_time is not None
              else (st.first_event_time or st.release_time))
             - st.release_time)
        D = state.task_deadlines[uid] - st.release_time
        rec = dict(
            task=uid, q=q, c_full=st.tokens_physical, T=round(T, 6),
            D=D, degraded=getattr(st, 'degraded', False),
            r_task=round(realized_rtask(
                q=q, c_full=st.tokens_physical, T=T, D=D, lam_c=lam_c,
                lam_t=lam_t, lam_f=lam_f, c0=c0), 10))
        rewards.append(rec)
    complete = all(not getattr(state.tasks[t['uid']], 'degraded', False)
                   for t in tasks) and all(r['q'] >= 0 for r in rewards)
    terminal = session_bonus if complete else -session_penalty
    record = dict(event='settlement', rewards=rewards,
                  session_terminal=terminal,
                  mean_rtask=round(sum(r['r_task'] for r in rewards)
                                   / max(1, len(rewards)), 10),
                  params=dict(lam_c=lam_c, lam_t=lam_t, lam_f=lam_f,
                              c0=c0, stub_test_only=True))
    path = Path(engine.directory) / 'REWARDS.jsonl'
    with path.open('a') as fh:
        fh.write(json.dumps(record, sort_keys=True) + '\n')
        fh.flush()
        import os
        os.fsync(fh.fileno())
    return record
