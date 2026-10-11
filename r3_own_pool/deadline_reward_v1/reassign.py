"""M5 — dynamic node-level model reassignment: legal candidate enumeration (Z, R, pi) and faithful application through the M1 engine. Zero real model calls.

M5 scope ONLY (per the frozen mainline): the legal generation and EXECUTION of joint actions — pi assignments over the frozen per-node menus, M3-adjudicated for dependency legality, executed with M4 recovery semantics. Reward scoring, constraint filtering, and candidate SELECTION belong to M6 (policy.py) and are deliberately absent here.

Isolation: this module imports stdlib + dag_closure only — no predictor / compensator / reward / policy.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import dag_closure as dc

ARMS = ('NONE', 'LOCAL', 'FULL')
_FAIL_KIND = {'e1': 'fb', 'e2': 'fb', 'r': 'esc', 'v': 'esc'}


@dataclass
class Candidate:
    arm: str
    pi: Dict[str, str]
    judgment: object
    kinds: Dict[str, str] = field(default_factory=dict)
    row: Optional[dict] = None      # scored table row (audit; filled by M6)


def _menu_variants(nodes: List[str]):
    nodes = sorted(set(nodes))
    if not nodes:
        yield {}
        return
    menus = [sorted(dc.MENUS[n]) for n in nodes]
    for combo in itertools.product(*menus):
        yield dict(zip(nodes, combo))


def enumerate_candidates(state, uid: str,
                         node_models: Dict[str, str]) -> List[Candidate]:
    st = state.tasks[uid]
    failed = [n for n in dc.TOPO if st.node_status[n] == dc.FAILED]
    pending = [n for n in dc.TOPO if st.node_status[n] == dc.PENDING]
    out: List[Candidate] = []

    def add(arm, R, pi):
        j = state.judge(uid, R, pi, on_incomplete='complete')
        if not j.legal:
            return
        kinds = {}
        for node, new_call in j.execute:
            if node in failed:
                kinds[node] = _FAIL_KIND[node]
            elif node in R:
                kinds[node] = 'fbd'
            else:
                kinds[node] = 'plain'
        out.append(Candidate(arm=arm, pi=dict(pi), judgment=j,
                             kinds=kinds))

    # NONE family: accept / schedule-only (π over still-pending nodes)
    for pi in _menu_variants(pending):
        add('NONE', [], pi)
    if not failed:
        return out
    # LOCAL family: retry the failed nodes; closure completed BY RULE; π
    # free over the (re)execution set ∪ pending nodes — the M5 capability.
    base_R = list(failed)
    j0 = state.judge(uid, base_R, {}, on_incomplete='complete')
    free = {n for n, _ in j0.execute} | set(pending)
    for pi in _menu_variants(sorted(free)):
        add('LOCAL', base_R, pi)
    # FULL family: full-graph replay — trigger nodes take menu variants,
    # every other node re-executes on its PLANNED model (E-arm semantics).
    others = {n: node_models[n] for n in dc.TOPO if n not in failed}
    for pi_trig in _menu_variants(failed):
        add('FULL', list(dc.TOPO), {**others, **pi_trig})
    return out


def apply_decision(engine, state, task: dict, node_models: Dict[str, str],
                   chosen: Candidate) -> None:
    """Execute the chosen joint plan through the engine: per-stage batching
    (topo order), kinds by trigger family, no-cache for FAILED retries and
    FULL replays (M4 semantics)."""
    uid = task['uid']
    st = state.tasks[uid]
    pi, kinds = chosen.pi, chosen.kinds
    replay = chosen.arm == 'FULL'
    for group in (('e1', 'e2'), ('r',), ('v',)):
        jobs = []
        for node in group:
            new_call = next((nc for n, nc in chosen.judgment.execute
                             if n == node), None)
            if new_call is None:
                continue
            if st.node_status.get(node) == dc.PENDING:
                continue  # first executions run in their planned stage with
                # the chosen pi (driver schedules) — never duplicated here
            model = pi.get(node) or st.node_model.get(node) \
                or node_models[node]
            failed = st.node_status.get(node) == dc.FAILED
            jobs.append(dict(task=task, node=node,
                             kind=kinds.get(node, 'plain'), model=model,
                             no_cache=replay or failed))
        if jobs:
            engine.run_jobs(f"plan:{chosen.arm}", jobs)


