"""M1 stub execution engine (deadline_reward_v1) — zero real model calls.

Scope is exactly the operator-authorized M1 (MAINLINE_FREEZE / README):
a per-call event loop on an INJECTED CLOCK, per-task real wall tracking,
first-class model-switch records, and an append-only TASK_LEDGER.jsonl,
executing the PLANNED stages (A -> R1 -> V1) of the 4-node DYNAMICDAG with
production's cross-task model batching semantics.

Deliberately NOT in M1 (later milestones, separately authorized):
SchedulerState API (M2), closure/reuse (M3), recovery execution (M4),
model reassignment (M5), policy/reward (M6).

Import-graph rule (VERIFICATION_PLAN L5): this module imports stdlib only.
Production semantics are MIRRORED (fault30_run.eval_config stage structure,
run_stage sorted-model batching at fault30_run.py:159-164) and verified
against independently generated production references by the test suite
(T3-lite, NONE arm) — never imported here.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

STAGES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ('A', ('e1', 'e2')),
    ('R1', ('r',)),
    ('V1', ('v',)),
)


class InjectedClock:
    """Deterministic monotonic-style clock; the ONLY time authority."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def time(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        if dt < 0:
            raise ValueError('clock must not go backwards')
        self.now += float(dt)


class StubModelServer:
    """Scripted model server. The ONLY thing the engine ever calls.

    Answers come from an (node, kind) map supplied by the test driver.
    Usage/latency come from declared synthetic PRIORS entries, drawn
    deterministically per (seed, node, kind, model, uid, attempt).
    """

    def __init__(self, answers: Dict[Tuple[str, str], str],
                 priors: dict, seed: str = 'm1') -> None:
        self.answers = answers
        self.priors = priors
        self.seed = seed
        self.invocations = 0  # Z1 sentinel: engine is the only caller

    def profile(self, key: str) -> dict:
        prof = self.priors['profiles'].get(key)
        if prof is None:
            prof = self.priors.get(key)  # top-level entries (e.g. v3_compat)
        if prof is None:
            raise KeyError('no PRIORS profile: ' + key)
        return prof

    def draw(self, node: str, kind: str, model: str, uid: str,
             attempt: int, profile_key: Optional[str] = None) -> dict:
        self.invocations += 1
        prof = self.profile(profile_key or f'{node}|{model}')
        rng = random.Random('|'.join((self.seed, node, kind, model,
                                      uid, str(attempt))))
        family = prof['family']
        if family == 'deterministic':
            lat = float(prof['latency_s'])
            total = int(prof['total_tokens'])
        elif family == 'normal':
            lat = max(0.01, round(rng.gauss(float(prof['lat_mean_s']),
                                            float(prof['lat_std_s'])), 6))
            total = int(prof['prompt_tokens']) + int(prof['completion_tokens'])
        else:
            raise ValueError('undeclared family: ' + family)
        answer = (self.answers.get((uid, node, kind))
                  if hasattr(self.answers, 'get') else None) \
            or self.answers[(node, kind)]
        usage = dict(prompt_tokens=int(prof.get('prompt_tokens', total)),
                     completion_tokens=int(prof.get('completion_tokens', 0)) or
                     (total - int(prof.get('prompt_tokens', total))),
                     total_tokens=total)
        return dict(status='delivered', answer=answer, usage=usage,
                    latency_s=lat)


@dataclass
class TaskState:
    uid: str
    t_first: Optional[float] = None
    t_last: Optional[float] = None
    service_sum: float = 0.0
    switch_sum: float = 0.0
    switch_count: int = 0
    calls: int = 0
    answers: Dict[str, str] = field(default_factory=dict)


class LedgerCorruptionError(Exception):
    """A corrupted line anywhere except an unfinished TAIL write."""


def load_ledger(path: Path) -> Tuple[List[dict], bool]:
    """Append-only loader (M2 hardening per operator ruling).

    Tolerated: the FINAL line failing to parse when the file lacks a
    trailing newline — the crash-mid-append signature (R-F7). Rejected
    (raises LedgerCorruptionError): any parse failure elsewhere — a
    corrupted middle line means the ledger is damaged, never silently
    skipped."""
    raw = Path(path).read_text()
    lines = raw.splitlines()
    events: List[dict] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1 and not raw.endswith('\n'):
                return events, True
            raise LedgerCorruptionError(
                f'corrupt ledger line {i + 1} (not a tail-torn write)')
    return events, False


class StubEngine:
    """Planned-stage executor with production-mirrored batching."""

    def __init__(self, directory, server: StubModelServer,
                 clock: InjectedClock, *, seed: str = 'm1',
                 topo: str = 'DYNAMICDAG', fam: str = 'HETEROGENEOUS',
                 profile_key: Optional[str] = None) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.directory / 'TASK_LEDGER.jsonl'
        if self.ledger_path.exists():
            raise ValueError('existing TASK_LEDGER: explicit reconciliation '
                             'required (no silent resume)')
        self.server = server
        self.clock = clock
        self.seed = seed
        self.topo = topo
        self.fam = fam
        self.profile_key = profile_key
        self.current_model: Optional[str] = None
        self.switch_idx = 0
        self._last_switch_idx: Optional[int] = None
        self._last_switch_t0: Optional[float] = None
        self.observers: List[Callable[[dict], None]] = []
        self.tokens_total = 0
        self.requests_total = 0
        self.n_events = 0
        self._switch_indices: List[int] = []
        self._cold_start_indices: List[int] = []
        self.attempts: Dict[Tuple[str, str, str], int] = {}
        self.tasks: Dict[str, TaskState] = {}
        self._append(dict(event='meta', seed=seed, topo=topo, fam=fam,
                          priors_sha256=hashlib.sha256(
                              json.dumps(server.priors,
                                         sort_keys=True).encode()
                          ).hexdigest(),
                          profile_key=profile_key,
                          zero_real_calls=True))

    def add_observer(self, fn: Callable[[dict], None]) -> None:
        """M2 hook: called with every appended event, after the fsync.
        Observer exceptions propagate — a broken observer is a failure,
        never silently ignored."""
        self.observers.append(fn)

    def _append(self, obj: dict) -> None:
        with self.ledger_path.open('a') as fh:
            fh.write(json.dumps(obj, sort_keys=True) + '\n')
            fh.flush()
            import os as _os
            _os.fsync(fh.fileno())
        self.n_events += 1
        for fn in self.observers:
            fn(obj)  # observer failures are engine failures — fail loud

    def _switch(self, to_model: str, uid: str, key: str) -> Optional[int]:
        if to_model == self.current_model:
            return None
        sw = self.server.priors['switch']
        t0 = self.clock.time()
        if self.current_model is None:
            # cold start of the first model: real cost, but no stop overhead
            cost = float(sw['start_s'][to_model])
        else:
            cost = float(sw['stop_s']) + float(sw['start_s'][to_model])
        self.clock.advance(cost)
        self.switch_idx += 1
        rec = dict(event='switch', idx=self.switch_idx, kind=(
            'cold_start' if self.current_model is None else 'switch'), **{
            'from': self.current_model, 'to': to_model, 'task': uid,
            'key_ref': key, 't_start': t0, 't_end': self.clock.time(),
            'wall_s': cost})
        self._append(rec)
        self.current_model = to_model
        self._switch_indices.append(self.switch_idx)
        if rec['kind'] == 'cold_start':
            self._cold_start_indices.append(self.switch_idx)
        st = self.tasks[uid]
        st.switch_sum += cost
        st.switch_count += 1
        self._last_switch_idx = self.switch_idx
        self._last_switch_t0 = t0
        return self.switch_idx

    def _call(self, stage: str, task: dict, node: str, kind: str,
              model: str) -> dict:
        uid = task['uid']
        if uid not in self.tasks:
            self.tasks[uid] = TaskState(uid=uid)
        st = self.tasks[uid]
        key = f'm1:{self.topo}:{self.fam}:{node}:{kind}:{uid}'
        self.attempts[(uid, node, kind)] = \
            self.attempts.get((uid, node, kind), 0) + 1
        attempt = self.attempts[(uid, node, kind)]
        sw_idx = self._switch(model, uid, key)
        t0 = self.clock.time()
        self._append(dict(event='call_start', key=key, stage=stage,
                          node=node, kind=kind, model=model, task=uid,
                          t_start=t0, switch_before=sw_idx))
        resp = self.server.draw(node, kind, model, uid, attempt,
                                profile_key=self.profile_key)
        self.clock.advance(resp['latency_s'])
        self.tokens_total += resp['usage']['total_tokens']
        self.requests_total += 1
        rec = dict(event='call', key=key, stage=stage, node=node, kind=kind,
                   model=model, task=uid, attempt=attempt,
                   answer_sha256=hashlib.sha256(
                       resp['answer'].encode()).hexdigest(),
                   answer=resp['answer'], usage=resp['usage'],
                   latency_s=resp['latency_s'],
                   t_start=t0, t_end=self.clock.time(),
                   switch_before=sw_idx)
        self._append(rec)
        # Per-task wall starts at the switch attributed to this task's first
        # call (cold start included) — the honest E2E span on the clock.
        if st.t_first is None:
            if sw_idx is not None and self._last_switch_idx == sw_idx:
                st.t_first = self._last_switch_t0
            else:
                st.t_first = t0
        st.t_last = self.clock.time()
        st.service_sum += resp['latency_s']
        st.calls += 1
        st.answers[node] = resp['answer']
        return rec

    def _run_stage(self, stage: str, jobs: List[dict]) -> None:
        """Production run_stage mirror (fault30_run.py:159-164): jobs of one
        dependency stage, batched by model in SORTED model order, task/list
        order preserved within each model group."""
        for model in sorted({j['model'] for j in jobs}):
            for j in jobs:
                if j['model'] == model:
                    self._call(stage, j['task'], j['node'], j['kind'],
                               j['model'])

    def run_panel(self, tasks: List[dict],
                  node_models: Dict[str, str]) -> List[dict]:
        if not tasks or len({t['uid'] for t in tasks}) != len(tasks):
            raise ValueError('nonempty unique-uid task panel required')
        for uid in node_models:
            if uid not in ('e1', 'e2', 'r', 'v'):
                raise ValueError('unknown node: ' + uid)
        self._append(dict(event='panel_start',
                          tasks=[t['uid'] for t in tasks],
                          t_release=self.clock.time(),
                          node_models=node_models))
        for stage, nodes in STAGES:
            jobs = [dict(task=t, node=nd, kind='plain', model=node_models[nd])
                    for t in tasks for nd in nodes
                    if nd in node_models]
            self._run_stage(stage, jobs)
        summaries = []
        for t in tasks:
            st = self.tasks[t['uid']]
            summary = dict(event='task_summary', task=st.uid,
                           t_first=st.t_first, t_last=st.t_last,
                           wall_inclusive_s=(st.t_last - st.t_first)
                           if st.t_first is not None else 0.0,
                           service_sum_s=round(st.service_sum, 6),
                           switch_sum_s=round(st.switch_sum, 6),
                           switch_count=st.switch_count, calls=st.calls)
            self._append(summary)
            summaries.append(summary)
        # Session-level record (operator ruling on cold-start billing):
        # switch/cold-start costs are counted ONCE in the switch events;
        # this summary only REFERENCES their indices — never re-sums them.
        self._append(dict(
            event='session_summary', tasks=len(tasks),
            calls=self.requests_total, requests=self.requests_total,
            tokens_total=self.tokens_total,
            switch_indices=list(self._switch_indices),
            cold_start_indices=list(self._cold_start_indices)))
        return summaries
