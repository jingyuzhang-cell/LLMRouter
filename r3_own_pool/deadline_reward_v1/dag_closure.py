"""M3 — DAG dependency closure & cache-reuse adjudication (zero real calls).

Purpose (operator M3 authorization): for any future joint action
a = (Z, R, π), decide BEFORE execution whether the plan is dependency-
legal, which completed nodes' cached outputs stay valid, which are
invalidated, and which re-executions are identity-unchanged cache hits.
This module ADJUDICATES; it never executes, never scores, and implements
no recovery policy (M4) and no model selection (M5).

DAG (mirrors the audited production constants — parity-tested):
    e1 (table facts) ─┐
                      ├→ r (join expression) → v (verify)
    e2 (text facts) ──┘

Reuse/invalidation semantics follow the FROZEN production cache identity
(model, prompt_sha256, task, node, scope) — smoke_runner.py:114. In this
module identity is tracked as (model, input_signature): a completed node's
cached output may be reused iff its model binding is unchanged AND every
parent's output identity is unchanged. Answer TEXT equality is NEVER a
reuse criterion ("不得仅凭文本相同擅自复用").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Optional, Tuple

NODES: Tuple[str, ...] = ('e1', 'e2', 'r', 'v')
PARENTS: Dict[str, Tuple[str, ...]] = {
    'e1': (), 'e2': (), 'r': ('e1', 'e2'), 'v': ('r',)}
CLOSURE: Dict[str, Tuple[str, ...]] = {
    'e1': ('r', 'v'), 'e2': ('r', 'v'), 'r': ('v',), 'v': ()}
TOPO: Tuple[str, ...] = ('e1', 'e2', 'r', 'v')  # a valid topological order
MODELS = frozenset({'medium', 'large', 'coder'})  # audited model universe

PENDING, RUNNING, DONE, FAILED = 'PENDING', 'RUNNING', 'DONE', 'FAILED'


@dataclass(frozen=True)
class PlanJudgment:
    legal: bool
    execute: Tuple[Tuple[str, bool], ...]  # (node, new_call) in topo order
    reuse: Tuple[str, ...]                  # DONE nodes reusing cached output
    invalidated: Tuple[str, ...]            # completed nodes losing validity
    reasons: Tuple[str, ...]                # rejections / audit notes


def descendants(nodes: Iterable[str]) -> FrozenSet[str]:
    out: set = set()
    stack = list(nodes)
    while stack:
        n = stack.pop()
        for ch in CLOSURE[n]:
            if ch not in out:
                out.add(ch)
                stack.append(ch)
    return frozenset(out)


def evaluate_plan(*, node_status: Dict[str, str],
                  node_model: Dict[str, Optional[str]],
                  exec_identity: Dict[str, Optional[Tuple[str, str]]],
                  R: Iterable[str], pi: Dict[str, str],
                  on_incomplete: str = 'reject') -> PlanJudgment:
    """Adjudicate a candidate (R, π) against one task's current state.

    node_status: node → PENDING/RUNNING/DONE/FAILED
    node_model:  node → currently bound model (None until first call)
    exec_identity: node → (model, input_signature) at its LAST execution;
                   None if never executed (PENDING / fresh).
    R: proposed re-execution set. π: proposed model assignment; its domain
    must be R ∪ PENDING (DONE nodes are immutable unless re-executed;
    RUNNING nodes are immutable, period).
    on_incomplete: 'reject' — a plan whose upstream change invalidates a
    completed downstream node NOT in R is illegal; 'complete' — the closure
    rule itself completes R (recorded in reasons; never silently)."""

    reasons: list = []
    R = frozenset(R)

    # ---- structural legality -------------------------------------------
    for n in R:
        if n not in NODES:
            return _reject('unknown_node:' + n)
        if node_status.get(n) == RUNNING:
            return _reject('running_in_R:' + n)  # rule 6: no mid-flight R
    for n, m in pi.items():
        if n not in NODES:
            return _reject('unknown_node:' + n)
        if m not in MODELS:
            return _reject('unknown_model:' + str(m))
        if node_status.get(n) == RUNNING:
            return _reject('running_node_immutable:' + n)  # rule 6
        if n not in R and node_status.get(n) in (DONE, FAILED):
            # rule 5: changing a finished node's model requires re-execution
            return _reject('done_node_model_change_without_reexec:' + n)

    # ---- topological change propagation ---------------------------------
    # changed[n] means: after this plan, n's output (if executed) or n's
    # CACHED output (if reused) differs from what dependents consumed.
    # For a reused node, staleness = any parent changed — the frozen cache
    # identity was computed with the parents' OLD outputs.
    execute: Dict[str, bool] = {}   # node -> new_call?
    changed: Dict[str, bool] = {}
    for n in TOPO:
        parents_changed = any(changed.get(p, False) for p in PARENTS[n])
        status = node_status.get(n, PENDING)
        in_R = n in R
        will_execute = in_R or status == PENDING
        if will_execute:
            ident = exec_identity.get(n)
            new_model = pi.get(n) or node_model.get(n)
            if ident is None:
                fresh = True        # never executed: a genuinely new call
                model_changed = True
            else:
                model_changed = new_model != ident[0]
                fresh = False
            # identity-unchanged cache hit: same model, same (unchanged)
            # inputs, previously executed — the frozen (model, sha, task,
            # node, scope) identity matches; the re-execution is a no-op
            # cache read.
            identity_changed = fresh or model_changed or parents_changed
            changed[n] = identity_changed
            execute[n] = identity_changed
            if in_R and not identity_changed:
                reasons.append('reexec_identity_unchanged_cache_hit:' + n)
            if model_changed and not fresh:
                reasons.append('model_change:' + n)
        else:
            changed[n] = parents_changed  # staleness of the cached output

    # ---- invalidations among completed nodes -----------------------------
    invalidated = tuple(n for n in TOPO
                        if changed[n] and n not in R
                        and node_status.get(n) in (DONE, FAILED))
    if invalidated:
        if on_incomplete == 'reject':
            return PlanJudgment(
                legal=False, execute=(), reuse=(),
                invalidated=invalidated,
                reasons=reasons + ['incomplete_closure_missing:'
                                   + ','.join(invalidated)])
        if on_incomplete != 'complete':
            raise ValueError('on_incomplete must be reject|complete')
        for n in invalidated:
            execute[n] = True
        reasons.append('closure_completed:' + ','.join(invalidated))

    exec_tuple = tuple((n, execute[n]) for n in TOPO if n in execute)
    reuse = tuple(n for n in TOPO
                  if node_status.get(n) in (DONE, FAILED)
                  and n not in execute)
    return PlanJudgment(legal=True, execute=exec_tuple, reuse=reuse,
                        invalidated=invalidated,
                        reasons=tuple(reasons))


def _reject(reason: str) -> PlanJudgment:
    return PlanJudgment(legal=False, execute=(), reuse=(), invalidated=(),
                        reasons=(reason,))


def input_signature(uid: str, node: str, parent_answers: Dict[str, str]) -> str:
    """Stable signature of a node's INPUT identity (mirror of the prompt-
    dependency structure audited in fault30_run.eval_config): e-nodes
    depend on static task context; r on both e outputs; v on r's output.
    Used by SchedulerState to track exec_identity at call time."""
    import hashlib
    import json
    material = [uid, node] + [parent_answers.get(p) for p in PARENTS[node]]
    return hashlib.sha256(json.dumps(material, sort_keys=True,
                                     default=str).encode()).hexdigest()
