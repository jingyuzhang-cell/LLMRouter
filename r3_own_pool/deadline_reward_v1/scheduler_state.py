"""M2 SchedulerState — observation API over the M1 stub engine.

Operator-authorized scope (M2 only): per-node execution status, current
model, LEGAL observations that have already occurred (D1–D6 mirrors in
detection.py), time state with the ruled口径 (task E2E = release →
termination, including queue wait and other-task interleaving — never a
bare service sum), live D_remain from the injected clock + task deadline,
budget state with B_remain COMPUTED from real spend (never a constant),
reproducible no-future snapshots, and a whitelist-guarded legal view.

NOT in M2 (later milestones): recovery policy (M4/M6), DAG closure/reuse
(M3), model reassignment (M5). Import rule (L5): stdlib + sibling modules
only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import detection

NODES = ('e1', 'e2', 'r', 'v')
PENDING, RUNNING, DONE, FAILED = 'PENDING', 'RUNNING', 'DONE', 'FAILED'

# Whitelist of the legal decision view (VERIFICATION_PLAN L2). Anything
# outside this set — gold, fault registry, future outputs, task labels —
# is rejected at construction time.
_VIEW_FIELDS = frozenset({
    'panel_clock', 'task', 'node_status', 'node_model', 'observations',
    'release_time', 'first_call_time', 'completion_time', 'elapsed_s',
    'd_remain_s', 'e2e_s', 'queue_wait_s', 'other_wait_s', 'service_sum_s',
    'switch_sum_s', 'switch_count', 'calls', 'recovery_counts',
    'budget', 'session',
})


def make_legal_view(**fields) -> Dict:
    unknown = set(fields) - _VIEW_FIELDS
    if unknown:
        raise ValueError('illegal view field(s): ' + ', '.join(sorted(unknown)))
    return dict(fields)


class _TaskState:
    def __init__(self, uid: str) -> None:
        self.uid = uid
        self.node_status: Dict[str, str] = {n: PENDING for n in NODES}
        self.node_model: Dict[str, Optional[str]] = {n: None for n in NODES}
        self.answers: Dict[str, str] = {}
        self.facts: Dict[str, List[dict]] = {}
        self.observations: List[dict] = []
        self.recovery_counts: Dict[str, int] = {
            k: 0 for k in ('e_fb', 'r_fbd', 'r_esc', 'v_fbd', 'v_esc',
                           'replay')}
        self.release_time: Optional[float] = None
        self.first_call_time: Optional[float] = None
        self.first_event_time: Optional[float] = None
        self.completion_time: Optional[float] = None
        self.service_sum = 0.0
        self.switch_sum = 0.0
        self.switch_count = 0
        self.calls = 0


class SchedulerState:
    """Observes engine events; exposes only occurred legal information."""

    def __init__(self, clock, *, task_deadlines: Dict[str, float],
                 token_allocation: float,
                 request_allocation: Optional[int] = None) -> None:
        self.clock = clock
        self.task_deadlines = dict(task_deadlines)  # uid -> absolute D
        self.token_allocation = float(token_allocation)
        self.request_allocation = request_allocation
        self.tasks: Dict[str, _TaskState] = {}
        self.tokens_spent = 0
        self.requests_spent = 0
        self.switch_indices: List[int] = []
        self.cold_start_indices: List[int] = []
        self._panel_models: Dict[str, str] = {}

    # -- engine hookup ----------------------------------------------------
    def attach(self, engine) -> None:
        engine.add_observer(self._on_event)

    def _on_event(self, ev: dict) -> None:
        kind = ev.get('event')
        if kind == 'panel_start':
            for uid in ev['tasks']:
                self.tasks.setdefault(uid, _TaskState(uid))
                self.tasks[uid].release_time = ev['t_release']
            self._panel_models = dict(ev['node_models'])
        elif kind == 'call_start':
            st = self.tasks[ev['task']]
            st.node_status[ev['node']] = RUNNING
            st.node_model[ev['node']] = ev['model']
            if st.first_call_time is None:
                st.first_call_time = ev['t_start']
            if st.first_event_time is None:
                st.first_event_time = ev['t_start']
        elif kind == 'switch':
            st = self.tasks[ev['task']]
            st.switch_sum += ev['wall_s']
            st.switch_count += 1
            if st.first_event_time is None:
                st.first_event_time = ev['t_start']
            self.switch_indices.append(ev['idx'])
            if ev.get('kind') == 'cold_start':
                self.cold_start_indices.append(ev['idx'])
        elif kind == 'call':
            self._on_call(ev)
        elif kind == 'task_summary':
            st = self.tasks[ev['task']]
            st.completion_time = ev['t_last']
            self._finalize_task(st)

    def _on_call(self, ev: dict) -> None:
        st = self.tasks[ev['task']]
        node, answer = ev['node'], ev['answer']
        st.answers[node] = answer
        st.service_sum += ev['latency_s']
        st.calls += 1
        st.node_model[node] = ev['model']
        self.tokens_spent += ev['usage']['total_tokens']
        self.requests_spent += 1
        t = ev['t_end']
        if node in ('e1', 'e2'):
            st.facts[node] = detection.parse_facts(answer)
            if detection.detect_e(answer):
                st.node_status[node] = FAILED
                st.observations.append(
                    dict(code=detection.D1, node=node, t=t))
            else:
                st.node_status[node] = DONE
        elif node == 'r':
            facts = detection.merged_facts(st.facts.get('e1', []),
                                           st.facts.get('e2', []))
            if detection.detect_r(answer, facts):
                st.node_status[node] = FAILED
                st.observations.append(
                    dict(code=detection.D3, node=node, t=t))
            else:
                st.node_status[node] = DONE
        elif node == 'v':
            facts = detection.merged_facts(st.facts.get('e1', []),
                                           st.facts.get('e2', []))
            if detection.detect_v(answer, st.answers.get('r', ''), facts):
                st.node_status[node] = FAILED
                st.observations.append(
                    dict(code=detection.D5, node=node, t=t))
            else:
                st.node_status[node] = DONE

    def _finalize_task(self, st: _TaskState) -> None:
        """Terminal D6 over final outputs (observable-only mirror)."""
        failed = detection.detect_task(
            st.facts.get('e1', []), st.facts.get('e2', []),
            st.answers.get('r', ''), st.answers.get('v', ''))
        if failed and not any(o['code'] == detection.D6
                              for o in st.observations):
            st.observations.append(
                dict(code=detection.D6, node=None,
                     t=st.completion_time))

    # -- live read API -----------------------------------------------------
    def d_remain(self, uid: str) -> float:
        """Remaining deadline, computed live from clock + task deadline."""
        return self.task_deadlines[uid] - self.clock.time()

    def elapsed(self, uid: str) -> float:
        return self.clock.time() - self.tasks[uid].release_time

    def e2e(self, uid: str) -> Optional[float]:
        st = self.tasks[uid]
        if st.completion_time is None:
            return None
        return st.completion_time - st.release_time

    def budget(self) -> Dict:
        """B_remain computed from real spend — never a stored constant."""
        return dict(
            tokens_spent=self.tokens_spent,
            requests_spent=self.requests_spent,
            token_allocation=self.token_allocation,
            request_allocation=self.request_allocation,
            b_remain_tokens=self.token_allocation - self.tokens_spent,
            b_remain_requests=(None if self.request_allocation is None
                               else self.request_allocation
                               - self.requests_spent))

    def task_view(self, uid: str) -> Dict:
        st = self.tasks[uid]
        e2e = self.e2e(uid)
        queue_wait = (None if st.first_event_time is None
                      else st.first_event_time - st.release_time)
        other_wait = (None if e2e is None or queue_wait is None else round(
            e2e - queue_wait - st.service_sum - st.switch_sum, 6))
        return make_legal_view(
            task=uid,
            panel_clock=round(self.clock.time(), 6),
            node_status=dict(st.node_status),
            node_model=dict(st.node_model),
            observations=[dict(o) for o in st.observations],
            release_time=st.release_time,
            first_call_time=st.first_call_time,
            completion_time=st.completion_time,
            elapsed_s=round(self.elapsed(uid), 6),
            d_remain_s=round(self.d_remain(uid), 6),
            e2e_s=None if e2e is None else round(e2e, 6),
            queue_wait_s=None if queue_wait is None else round(queue_wait, 6),
            other_wait_s=other_wait,
            service_sum_s=round(st.service_sum, 6),
            switch_sum_s=round(st.switch_sum, 6),
            switch_count=st.switch_count,
            calls=st.calls,
            recovery_counts=dict(st.recovery_counts))

    def legal_view(self, tag: Optional[str] = None) -> Dict:
        """Panel-wide legal view: per-task views + live budget + session
        facts. Contains ONLY already-occurred, whitelisted information."""
        return dict(
            tag=tag,
            panel_clock=round(self.clock.time(), 6),
            tasks={uid: self.task_view(uid) for uid in self.tasks},
            budget=self.budget(),
            session=dict(switch_indices=list(self.switch_indices),
                         cold_start_indices=list(self.cold_start_indices),
                         panel_models=dict(self._panel_models)))

    def snapshot(self, engine, tag: str) -> Dict:
        """Reproducible, traceable state snapshot appended to the engine
        ledger. `n_events_before` records the exact ledger prefix length,
        so replay is BY EVENT ORDER — clock ties at the snapshot instant
        can never leak a later event into the rebuild."""
        view = self.legal_view(tag=tag)
        digest = hashlib.sha256(json.dumps(view, sort_keys=True,
                                           default=str).encode()).hexdigest()
        engine._append(dict(event='state_snapshot', tag=tag,
                            n_events_before=engine.n_events,
                            content_sha256=digest,
                            panel_clock=view['panel_clock']))
        return view

    # -- replay/rebuild (no future information by construction) ----------
    @staticmethod
    def replay(events: List[dict], *, clock, task_deadlines,
               token_allocation, request_allocation=None) -> 'SchedulerState':
        """Rebuild the state from an EXACT ledger PREFIX (caller slices by
        event index, per the snapshot's n_events_before). Replaying a
        prefix is what makes snapshots provably free of future information."""
        st = SchedulerState(clock, task_deadlines=task_deadlines,
                            token_allocation=token_allocation,
                            request_allocation=request_allocation)
        for ev in events:
            if ev.get('event') in ('panel_start', 'call_start', 'call',
                                   'switch', 'task_summary'):
                st._on_event(ev)
        return st
