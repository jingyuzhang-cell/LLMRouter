"""M7-3B Work Package 1: F-prime — executable V1.0 policy (ZERO model calls).

INDEPENDENT implementation of the historical V1.0 rules, transcribed from the
only authoritative artifact: m6_replay_harness.v1_decide (the M6-5 replay
policy). It does NOT filter V1.1 candidates — it computes actions directly.

Historical V1.0 rule set (confirmed from code, line-referenced):
  Z_1  contract + persistent + hetero-parent node      -> SPLIT_VERIFY
       (historical code used a static corpus map; the RULE is structural:
        >=2 distinct parent kinds. Generalization disclosed, not invented.)
  R_1  persistent + attempt >= 1                       -> EARLY_EXIT
       (NO one-retry ladder — that ladder is the V1.1 refinement R_1'.)
  PI_2 gap >= 0.15 + model != strongest                 -> RETRY_SWITCH_STRONG
       (NO systematic-signature gate, NO attempt ladder — both are V1.1
        refinements. Fires on ANY failure incl. transport and unknown
        fall-through, exactly as the historical code does.)
  else RETRY_SAME
  Unknown-signature: V1.0 has NO conservative channel — persistence 'unknown'
  falls through to the retry-family + PI gate (confirmed from code; the
  conservative channel is an M7-2-era engine addition, documented as a third
  behavioral difference, not silently dropped).

Pre-registered difference set vs F (V1.1):
  D1  R: EARLY_EXIT@attempt>=1          vs ladder (one retry) then exit@>=2
  D2  pi: switch on any fault+gap+weak  vs systematic signature + attempt>=2
  D3  unknown signature: retry(+maybe switch) vs conservative channel/stop
  D4  MULTI-FAULT node selection (operator registration): V1.0 is an
      event-by-event policy with no multi-fault arbitration; V10.decide
      deterministically serves the LOWEST node_id faulted node first.
      F (V1.1) generates candidates per node and selects from the Pareto
      frontier, which may target a DIFFERENT node. C1-C6 single-fault
      trajectory tests DO NOT cover D4; EP4 comparisons must exclude
      multi-fault states or stratify by this difference.
  Everything else (Z_1 timing, persistence-table input, scoring of nothing)
  is identical BY CONSTRUCTION from the same historical source.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import m7_decision_engine as E


@dataclass(frozen=True)
class V10Decision:
    """Minimal decision record mirroring JointDecision's driver-facing fields."""
    chosen: str
    z: str                                   # IDENTITY | SPLIT_VERIFY
    r: Tuple[str, Tuple[str, ...]]           # (action, targets)
    pi: Tuple[str, Tuple[str, ...]]          # (action, targets)
    rationale: str
    assignments: Tuple[Tuple[str, str], ...]
    split_of: Optional[str] = None
    policy: str = 'V1.0'

    def hash_hex(self) -> str:
        import hashlib, json
        payload = json.dumps({'chosen': self.chosen, 'z': self.z,
                              'r': list(self.r), 'pi': list(self.pi),
                              'assignments': [list(a) for a in self.assignments],
                              'split_of': self.split_of}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _hetero_parents(node: E.Node, state: E.EngineState) -> bool:
    kinds = {state.node(p).kind for p in node.parents}
    return len(kinds) >= 2


def v10_action(node: E.Node, state: E.EngineState):
    """The historical v1_decide, structurally generalized. Returns
    (dimension, action) exactly in the historical vocabulary."""
    pers = dict(state.persistence_table).get(node.last_failure_type, 'unknown')
    kind = node.kind
    # Z_1 — historical first branch
    if node.last_failure_type == 'contract' and pers == 'persistent' \
            and _hetero_parents(node, state):
        return ('Z', 'SPLIT_VERIFY')
    # R_1 — historical second branch (NO ladder)
    if pers == 'persistent' and node.attempts >= 1:
        return ('R', 'EARLY_EXIT')
    # PI_2 — historical third branch (no signature gate, no attempt gate)
    gap = state.profile(kind, 'glm53') - state.profile(kind, node.model)
    if gap >= state.params.gap_threshold and node.model != 'glm53':
        return ('R+pi', 'RETRY_SWITCH_STRONG')
    return ('R', 'RETRY_SAME')


def v10_decide(state: E.EngineState) -> V10Decision:
    """V1.0 policy decision on the shared EngineState. Deterministic."""
    faulted = sorted([n for n in state.nodes if n.status == 'failed'],
                     key=lambda n: n.node_id)
    ready = sorted([n for n in state.nodes if n.status == 'pending'
                    and all(state.node(p).status == 'done'
                            for p in n.parents)],
                   key=lambda n: n.node_id)
    assigns = [(n.node_id, n.model) for n in ready]
    split_of = None

    if not faulted:
        return V10Decision(chosen='normal_execution', z='IDENTITY',
                           r=('NONE', ()), pi=('KEEP', ()),
                           rationale='no faulted nodes',
                           assignments=tuple(assigns))

    node = faulted[0]                        # deterministic: lowest node_id
    dim, act = v10_action(node, state)
    nid = node.node_id
    if act == 'SPLIT_VERIFY':
        split_of = nid
        chosen, r, pi = 'split_verify', ('RETRY_ON_CHILDREN', ()), ('KEEP', ())
        rationale = ('V1.0 Z_1: contract@persistent+hetero-parents -> '
                     'SPLIT_VERIFY (identical to V1.1 by construction)')
    elif act == 'EARLY_EXIT':
        chosen, r, pi = 'early_exit', ('EARLY_EXIT', (nid,)), ('KEEP', ())
        rationale = ('V1.0 R_1: persistent -> EARLY_EXIT at attempt>=1, '
                     'NO one-retry ladder [DIFFERENCE D1 vs V1.1]')
    elif act == 'RETRY_SWITCH_STRONG':
        chosen = 'retry_switch'
        strong = E.switch_target_model(node, state)
        r, pi = ('RETRY_SAME', (nid,)), ('SWITCH_STRONG', (nid,))
        assigns.append((nid, strong))
        rationale = ('V1.0 PI_2: gap+weak -> switch on ANY fault, no '
                     'signature/attempt gate [DIFFERENCE D2 vs V1.1]'
                     + ('; unknown signature falls through (no conservative '
                        'channel in V1.0) [DIFFERENCE D3]'
                        if node.last_failure_type is None else ''))
    else:
        chosen, r, pi = 'retry_same', ('RETRY_SAME', (nid,)), ('KEEP', ())
        assigns.append((nid, node.model))
        rationale = ('V1.0 default: same-model retry'
                     + ('; unknown signature falls through (no conservative '
                        'channel in V1.0) [DIFFERENCE D3]'
                        if node.last_failure_type is None else ''))

    return V10Decision(chosen=chosen, z='SPLIT_VERIFY' if split_of else 'IDENTITY',
                       r=r, pi=pi, rationale=rationale,
                       assignments=tuple(sorted(assigns)), split_of=split_of)
