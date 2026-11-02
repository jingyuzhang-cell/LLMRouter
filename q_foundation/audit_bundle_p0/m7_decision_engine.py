"""M7-2D: Mechanism-Conditioned Joint Decision Engine (ZERO model calls).

Pure-function decision core: decide(state) -> JointDecision. Deterministic
(frozen value objects, sorted iteration, no randomness, no wall-clock reads).
Every decision records: fault classification view, legal candidates,
per-candidate predictions with SEPARATE interaction terms, constraint filter
results (GROSS token/latency reservation), Pareto regime, and the chosen
joint action a_t = (Z_t, R_t, pi_t).

Calibration constants come from the frozen corpus (M6-4/M6-5/M7-1) and are
carried WITH sample sizes; V1.1 rules stay PRELIMINARY by construction.

Acceptance mapping (operator's nine criteria):
  #1 determinism        — frozen dataclasses, sorted iteration, decide() twice identical
  #2 no illegal DAG     — apply_split() builds children from the faulted node's own
                          parents; acyclicity re-verified on every transform
  #3 no re-execution    — assignments exclude status='done' nodes (asserted)
  #4 constraints        — GROSS budget reservation + deadline + slot legality in
                          filter (net dc_hat is reporting-only, never gates)
  #5 unknown faults     — conservative channel; never Z / pi / persistent-exit
  #6 INCOMPLETE != Q=0  — quality estimates are None until COMPLETE-able
  #7 separate effects   — prediction.interaction records per-pair terms; NO_EVIDENCE
                          terms are explicit zeros, never silently additive
  #8 Pareto incomparable— frontier returned with regime; chosen is marked as a
                          stated-preference recommendation, forced_unique=False
  #9 prediction audit   — every prediction carries calibrated point + n + level,
                          consumable by the replay error table
"""
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------ types ---

SYSTEMATIC = ('contract', 'parse')
TRANSIENT_CAP = 2                 # design choice (R_2); flagged CANDIDATE
PI_GAP_THRESHOLD = 0.15

CAL = {
    'p_recover_split_merge_persistent': {'point': 1.00, 'n': 6, 'level': 'A/LOW_N'},
    'p_recover_retry_persistent':       {'point': 0.03, 'n': 17, 'level': 'A'},
    'p_recover_retry_transient':        {'point': 0.76, 'n': 29, 'level': 'A'},
    'split_structure_cost_tok':         {'point': 2800, 'n': 2, 'level': 'A/LOW_N'},
    'wasted_persistent_retry_tok':      {'point': 2200, 'n': 12, 'level': 'A'},
    'switch_dq_factor':                 {'point': 0.76, 'n': 1, 'level': 'A/SINGLE_CELL'},
    'switch_dc_tok_per_node':           {'point': -300, 'n': 0, 'level': 'B/prior'},
    'switch_dl_s_per_node':             {'point': -2.0, 'n': 0, 'level': 'B/prior'},
}


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    parents: Tuple[str, ...]
    model: str
    status: str                       # pending | running | done | failed
    attempts: int
    last_failure_type: Optional[str]  # None = none recorded OR unknown signature
    failure_signature_seen: bool = False   # False + failed = UNKNOWN signature


@dataclass(frozen=True)
class EngineParams:
    gap_threshold: float = PI_GAP_THRESHOLD
    transient_retry_cap: int = TRANSIENT_CAP
    reserve_per_call_tok: int = 2500          # calibrated GROSS reservation
    reserve_latency_s_per_call: float = 12.0
    stated_preference: bool = True            # (B, D) preference stated via state


@dataclass(frozen=True)
class EngineState:
    task_id: str
    dag_version: int
    nodes: Tuple[Node, ...]
    edges: Tuple[Tuple[str, str], ...]        # (parent, child)
    budget_remaining: int
    deadline_remaining_s: float
    slots_total: Tuple[Tuple[str, int], ...]  # sorted (model, capacity)
    slots_in_use: Tuple[Tuple[str, int], ...]
    persistence_table: Tuple[Tuple[str, str], ...]   # (failure_type, verdict)
    profile_q: Tuple[Tuple[str, Tuple[Tuple[str, float], ...]], ...]
    params: EngineParams = EngineParams()

    def node(self, nid) -> Node:
        return next(n for n in self.nodes if n.node_id == nid)

    def children_of(self, nid) -> Tuple[str, ...]:
        return tuple(sorted(c for p, c in self.edges if p == nid))

    def profile(self, kind, model) -> float:
        row = dict(self.profile_q).get(kind, ())
        return float(dict(row).get(model, 0.5))


# ------------------------------------------------- A.2 fault classification --

def classify(node: Node, state: EngineState) -> dict:
    """Fault-mechanism view inferred FROM FACTS at decision time. Unknown
    signatures are never forced into a class (acceptance #5)."""
    if node.status != 'failed':
        return {'layer': 'none', 'persistence': 'none', 'rate': None, 'n': 0,
                'confidence': 'HIGH', 'signature': None}
    if not node.failure_signature_seen or node.last_failure_type is None:
        return {'layer': 'unknown', 'persistence': 'unknown', 'rate': None,
                'n': 0, 'confidence': 'NONE', 'signature': None}
    sig = node.last_failure_type
    table = dict(state.persistence_table)
    verdict = table.get(sig, 'unknown')
    parent_kinds = tuple(sorted({state.node(p).kind for p in node.parents}))
    if sig == 'contract':
        layer = 'merge_interface' if len(parent_kinds) >= 2 else 'node_logic'
        rate = 0.03 if layer == 'merge_interface' else 0.25
        n = 16 if layer == 'merge_interface' else 4
        conf = 'HIGH' if layer == 'merge_interface' else 'LOW'
    elif sig in SYSTEMATIC:
        layer, rate, n, conf = 'node_logic', None, 10, 'MED'
    else:
        layer, rate, n, conf = 'runtime/transport', 0.76, 29, 'HIGH'
    return {'layer': layer, 'persistence': verdict, 'rate': rate, 'n': n,
            'confidence': conf, 'signature': sig}


# ------------------------------------------------------- B.1 legality gates --

def split_legal(node: Node, state: EngineState) -> Tuple[bool, List[str]]:
    """Z legality: policy conditions, each reported."""
    why = []
    view = classify(node, state)
    if view['layer'] != 'merge_interface':
        why.append(f"layer={view['layer']} != merge_interface")
    parent_kinds = tuple(sorted({state.node(p).kind for p in node.parents}))
    if len(parent_kinds) < 2:
        why.append(f"parents homogeneous kinds {parent_kinds}")
    if view['persistence'] not in ('persistent',):
        why.append(f"persistence={view['persistence']}")
    # upstream logic fault? parents must be healthy (M3 inheritance boundary)
    if any(state.node(p).status != 'done' for p in node.parents):
        why.append('upstream parent not done (fault-inheritance risk)')
    if view['signature'] is None:
        why.append('unknown signature')
    return (len(why) == 0), why


def pi_switch_legal(node: Node, state: EngineState) -> Tuple[bool, List[str]]:
    """pi legality: systematic signature + real gap + weak model + unexecuted
    + PI_2-prime attempt ladder (switch only AFTER one same-config retry has
    failed, attempt>=2 — M6-5 Phase E; defect found by M7-3A trajectory
    deduction: engine fired switch at attempt 1, deviating from policy)."""
    why = []
    view = classify(node, state)
    if view['signature'] not in SYSTEMATIC:
        why.append(f"signature {view['signature']} not systematic")
    if node.status == 'done':
        why.append('node already done (never re-execute)')
    if node.attempts < 2:
        why.append(f'PI_2-prime ladder: switch only after one same-config '
                   f'retry failed (attempts={node.attempts} < 2)')
    gap = state.profile(node.kind, 'glm53') - state.profile(node.kind, node.model)
    if gap < state.params.gap_threshold:
        why.append(f"gap {gap:.2f} < {state.params.gap_threshold}")
    if node.model == 'glm53':
        why.append('already strongest assigned')
    return (len(why) == 0), why


def switch_target_model(node: Node, state: EngineState) -> str:
    models = ('glm53', 'glm53flash')
    return max(models, key=lambda m: (state.profile(node.kind, m), m))


# ---------------------------------------------------------- B.2 candidates ---

@dataclass(frozen=True)
class Candidate:
    name: str
    z: str                                  # IDENTITY | SPLIT_VERIFY
    r: Tuple[str, Tuple[str, ...]]          # (action, target nodes)
    pi: Tuple[str, Tuple[str, ...]]         # (action, target nodes)
    p_recover: Optional[float]
    dq_hat: Optional[float]                 # None until COMPLETE-able (acc #6)
    dc_hat: int                             # NET reporting delta (never gates)
    dl_hat: float
    reserve_calls: int                      # GROSS calls for constraint gating
    cal: Tuple[Tuple[str, str], ...] = ()   # (param, "point/n/level") audit trail
    interaction: Tuple[Tuple[str, str], ...] = ()  # per-pair, NO_EVIDENCE explicit
    rationale: str = ''


def _cal(key):
    c = CAL[key]
    return c['point'], f"{c['point']}/n={c['n']}/{c['level']}"


def generate_candidates(state: EngineState, faulted: List[Node]) -> List[Candidate]:
    """Joint action candidates a_t=(Z,R,pi) per policy table. Deterministic
    order: sorted by name."""
    out = []
    p = state.params
    for node in faulted:
        view = classify(node, state)
        nid = node.node_id
        sig_pers = view['persistence']

        # ---- conservative channel (unknown) — acceptance #5
        if view['layer'] == 'unknown':
            if node.attempts >= 2:
                out.append(Candidate(
                    name=f'stop_unclassified:{nid}', z='IDENTITY',
                    r=('EARLY_EXIT', (nid,)), pi=('KEEP', ()),
                    p_recover=0.0, dq_hat=None, dc_hat=0, dl_hat=0,
                    reserve_calls=0,
                    cal=(('p_recover', 'unknown-unclassified-after-retry/n=0/NONE'),),
                    interaction=(('Z*R', 'N/A'), ('Z*pi', 'N/A'), ('R*pi', 'N/A')),
                    rationale='still unclassified after conservative retry: '
                              'stop with stopped_unclassified audit trail (C.6)'))
            else:
                out.append(Candidate(
                    name=f'conservative:{nid}', z='IDENTITY',
                    r=('ONE_CONSERVATIVE_RETRY', (nid,)), pi=('KEEP', ()),
                    p_recover=None, dq_hat=None,
                    dc_hat=p.reserve_per_call_tok,
                    dl_hat=p.reserve_latency_s_per_call, reserve_calls=1,
                    cal=(('p_recover', 'unknown/unclassified/n=0/NONE'),),
                    interaction=(('Z*R', 'N/A'), ('Z*pi', 'N/A'), ('R*pi', 'N/A')),
                    rationale='unknown signature: one conservative retry, no Z, '
                              'no pi, stop on second failure (policy C.6)'))
            continue

        ok_split, _ = split_legal(node, state)
        ok_pi, _ = pi_switch_legal(node, state)
        gap = state.profile(node.kind, 'glm53') - state.profile(node.kind, node.model)

        if ok_split:
            # J_2 / J_4: SPLIT + retry-on-children (+pi on children if gap)
            pr_split, cal_s = _cal('p_recover_split_merge_persistent')
            cost_split, cal_c = _cal('split_structure_cost_tok')
            waste, cal_w = _cal('wasted_persistent_retry_tok')
            k_no_z = 1 if sig_pers == 'persistent' else p.transient_retry_cap
            inter = (('Z*R', 'JOINT_MODELED: recovery modeled on split+children '
                             'as a whole, not U(Z)+U(R)'),
                     ('Z*pi', 'NO_EVIDENCE:0'),
                     ('R*pi', 'NO_EVIDENCE:0'))
            rationale = (f'dC_Z = +{cost_split} (new structure) - {k_no_z}x{waste} '
                         f'(avoided futile retries on no-Z path); H1-type negative / '
                         f'R9B-type positive depending on no-Z arm behaviour')
            out.append(Candidate(
                name=f'split_retry:{nid}', z='SPLIT_VERIFY',
                r=('RETRY_ON_CHILDREN', ()), pi=('KEEP', ()),
                p_recover=pr_split, dq_hat=None,
                dc_hat=cost_split - k_no_z * waste,
                dl_hat=2 * p.reserve_latency_s_per_call,
                reserve_calls=2,
                cal=(('p_recover', cal_s), ('dc_split', cal_c), ('dc_waste', cal_w)),
                interaction=inter, rationale=rationale))
            if ok_pi:
                out.append(Candidate(
                    name=f'split_retry_switch:{nid}', z='SPLIT_VERIFY',
                    r=('RETRY_ON_CHILDREN', ()), pi=('SWITCH_STRONG', ()),
                    p_recover=pr_split,
                    dq_hat=round(gap * CAL['switch_dq_factor']['point'], 4),
                    dc_hat=cost_split - k_no_z * waste
                           + CAL['switch_dc_tok_per_node']['point'],
                    dl_hat=2 * p.reserve_latency_s_per_call
                           + CAL['switch_dl_s_per_node']['point'],
                    reserve_calls=2,
                    cal=(('p_recover', cal_s), ('dc_split', cal_c),
                         ('dc_waste', cal_w),
                         ('switch_dq', f"gap{gap:.2f}x0.76/n=1/SINGLE_CELL")),
                    interaction=inter,
                    rationale=rationale + ' + pi on children (UNVALIDATED '
                                          'positive-benefit, n=1)'))

        # ---- R ladder (persistent: one same-config retry then exit = R_1')
        if sig_pers == 'persistent':
            pr, cal_r = _cal('p_recover_retry_persistent')
            if node.attempts < 2:      # ladder exhausted at attempts>=2: exit only
                out.append(Candidate(
                    name=f'ladder_exit:{nid}', z='IDENTITY',
                    r=('ONE_RETRY_THEN_EXIT', (nid,)), pi=('KEEP', ()),
                    p_recover=pr, dq_hat=None,
                    dc_hat=p.reserve_per_call_tok, dl_hat=p.reserve_latency_s_per_call,
                    reserve_calls=1, cal=(('p_recover', cal_r),),
                    interaction=(('Z*R', 'N/A: no Z'), ('Z*pi', 'N/A'), ('R*pi', 'N/A')),
                    rationale='R_1 prime: exactly one same-config retry (R6 n4 '
                              'counterexample forbids immediate exit), then exit'))
                if ok_pi:
                    out.append(Candidate(
                        name=f'ladder_switch:{nid}', z='IDENTITY',
                        r=('ONE_RETRY_THEN_EXIT', (nid,)),
                        pi=('SWITCH_STRONG', (nid,)),
                        p_recover=pr,
                        dq_hat=round(gap * CAL['switch_dq_factor']['point'], 4),
                        dc_hat=p.reserve_per_call_tok
                               + CAL['switch_dc_tok_per_node']['point'],
                        dl_hat=p.reserve_latency_s_per_call
                               + CAL['switch_dl_s_per_node']['point'],
                        reserve_calls=1,
                        cal=(('p_recover', cal_r),
                             ('switch_dq', f"gap{gap:.2f}x0.76/n=1/SINGLE_CELL")),
                        interaction=(('Z*R', 'N/A'), ('Z*pi', 'N/A'),
                                     ('R*pi', 'NO_EVIDENCE:0')),
                        rationale='J_3: ladder + switch (pi sensitivity UNVALIDATED)'))
        else:
            # ---- transient: bounded same-model retry (R_2)
            # P0/E5 (+audit clarification) — SEMANTICS: `attempts` = number of
            # executions that already happened on this node (the initial
            # execution is attempts=1). `transient_retry_cap` = MAXIMUM TOTAL
            # RETRIES allowed AFTER the first failure (not total executions).
            # With cap=2: attempts=1 -> 2 retries left; attempts=2 -> 1 (the
            # last allowed retry); attempts>=3 -> budget exhausted, NO retry
            # candidate at all (exit only). remaining can never go negative.
            remaining = p.transient_retry_cap - (node.attempts - 1)
            if remaining > 0:
                cap = remaining
                pr, cal_t = _cal('p_recover_retry_transient')
                out.append(Candidate(
                    name=f'retry_same:{nid}', z='IDENTITY',
                    r=('RETRY_SAME', (nid,)), pi=('KEEP', ()),
                    p_recover=pr, dq_hat=None,
                    dc_hat=p.reserve_per_call_tok * cap,
                    dl_hat=p.reserve_latency_s_per_call * cap,
                    reserve_calls=cap, cal=(('p_recover', cal_t),),
                    interaction=(('Z*R', 'N/A'), ('Z*pi', 'N/A'), ('R*pi', 'N/A')),
                    rationale=f'transient: same-model retry, remaining={cap} '
                              f'(cap is CANDIDATE, corpus showed unbounded-retry gap)'))
                if ok_pi:  # systematic transient (parse) on weak model after ladder
                    out.append(Candidate(
                        name=f'retry_switch:{nid}', z='IDENTITY',
                        r=('RETRY_SAME', (nid,)), pi=('SWITCH_STRONG', (nid,)),
                        p_recover=pr,
                        dq_hat=round(gap * CAL['switch_dq_factor']['point'], 4),
                        dc_hat=p.reserve_per_call_tok * cap
                               + CAL['switch_dc_tok_per_node']['point'],
                        dl_hat=p.reserve_latency_s_per_call * cap
                               + CAL['switch_dl_s_per_node']['point'],
                        reserve_calls=cap,
                        cal=(('p_recover', cal_t),
                             ('switch_dq', f"gap{gap:.2f}x0.76/n=1/SINGLE_CELL")),
                        interaction=(('Z*R', 'N/A'), ('Z*pi', 'N/A'),
                                     ('R*pi', 'NO_EVIDENCE:0')),
                        rationale='systematic signature on weak model: retry + switch '
                                  '(PI_2-prime ladder)'))

        # ---- fail-fast / stop
        out.append(Candidate(
            name=f'exit_node:{nid}', z='IDENTITY',
            r=('EARLY_EXIT', (nid,)), pi=('KEEP', ()),
            p_recover=0.0, dq_hat=None, dc_hat=0, dl_hat=0, reserve_calls=0,
            interaction=(('Z*R', 'N/A'), ('Z*pi', 'N/A'), ('R*pi', 'N/A')),
            rationale='stop the node, keep the audit trail (stopped-classified)'))
    return sorted(out, key=lambda c: c.name)


# --------------------------------------------------- C.3 filter & selection --

def _candidate_node(c: Candidate) -> str:
    """Target faulted node of a candidate (names are f'<action>:{nid}')."""
    return c.name.rsplit(':', 1)[-1]


def _model_demand(c: Candidate, state: 'EngineState',
                  ready: List[Node]) -> Dict[str, int]:
    """Per-model planned assignments of a candidate (ready set + candidate
    actions), for the slot-availability check (P0/E2)."""
    demand: Dict[str, int] = {}
    for n in ready:
        demand[n.model] = demand.get(n.model, 0) + 1
    if c.z == 'SPLIT_VERIFY':
        node = state.node(_candidate_node(c))
        # E7: children keep the faulted node's model unless pi authorizes a
        # switch — split NEVER implicitly reassigns models
        child_model = (switch_target_model(node, state)
                       if c.pi[0] == 'SWITCH_STRONG' else node.model)
        demand[child_model] = demand.get(child_model, 0) + 2
    else:
        for nid in c.r[1]:
            node = state.node(nid)
            model = (switch_target_model(node, state)
                     if c.pi[0] == 'SWITCH_STRONG' and nid in c.pi[1]
                     else node.model)
            demand[model] = demand.get(model, 0) + 1
    return demand


def constraint_filter(cands: List[Candidate], state: EngineState,
                      n_ready_calls: int,
                      ready: Optional[List[Node]] = None) -> Tuple[List[Candidate], List[dict]]:
    """GROSS budget reservation + deadline + slots. Rejections recorded.
    dc_hat is a NET reporting delta and never gates feasibility.
    P0 fixes: E2 — slot check now compares per-model PLANNED demand against
    free slots (total - in_use), not merely whether over-subscription
    already exists."""
    p = state.params
    kept, rejected = [], []
    total_slots = dict(state.slots_total)
    in_use = dict(state.slots_in_use)
    rdy = ready if ready is not None else []
    for c in sorted(cands, key=lambda x: x.name):
        calls = c.reserve_calls + n_ready_calls
        reserve_tok = calls * p.reserve_per_call_tok
        reserve_lat = calls * p.reserve_latency_s_per_call
        why = []
        if reserve_tok > state.budget_remaining:
            why.append(f'budget: gross reserve {reserve_tok} > remaining '
                       f'{state.budget_remaining}')
        if reserve_lat > state.deadline_remaining_s:
            why.append(f'deadline: reserve {reserve_lat:.0f}s > remaining '
                       f'{state.deadline_remaining_s:.0f}s')
        demand = _model_demand(c, state, rdy)
        for m in sorted(demand):
            free = total_slots.get(m, 0) - in_use.get(m, 0)
            if demand[m] > free:
                why.append(f'slots: model {m} planned {demand[m]} > free {free}')
        for m in sorted(total_slots):
            if total_slots[m] - in_use.get(m, 0) < 0:
                why.append(f'slots: model {m} over-subscribed')
        if why:
            rejected.append({'candidate': c.name, 'reasons': why})
        else:
            kept.append(c)
    return kept, rejected


def _cand_dominates(a: Candidate, b: Candidate) -> bool:
    """P0/E6: quality (dq_hat) and reliability (p_recover) are SEPARATE axes.
    Dominance requires: quality-axis comparable and >= (both None = equal;
    one None vs one defined = INCOMPARABLE -> no dominance), reliability >=,
    cost <=, latency <=, with at least one strict.
    dq_hat None = quality unquantified until COMPLETE (M6-3 rule #6) — it is
    never treated as zero."""
    qa, qb = a.dq_hat, b.dq_hat
    if (qa is None) != (qb is None):
        return False                      # incomparable on the quality axis
    q_ok = True if (qa is None and qb is None) else qa >= qb
    q_strict = (qa is not None and qb is not None and qa > qb)
    pa = -1.0 if a.p_recover is None else a.p_recover
    pb = -1.0 if b.p_recover is None else b.p_recover
    return (q_ok and pa >= pb and a.dc_hat <= b.dc_hat and a.dl_hat <= b.dl_hat
            and (q_strict or pa > pb or a.dc_hat < b.dc_hat or a.dl_hat < b.dl_hat))


def pareto_frontier(cands: List[Candidate]) -> List[Candidate]:
    ordered = sorted(cands, key=lambda x: x.name)
    return [c for c in ordered
            if not any(_cand_dominates(o, c) for o in ordered if o is not c)]


def detect_regime(front: List[Candidate], all_kept: List[Candidate]) -> str:
    if not front:
        return 'empty'
    if len(front) == 1 and all(_cand_dominates(front[0], o)
                               for o in all_kept if o is not front[0]):
        return 'single_arm_dominance'
    if len({c.p_recover for c in front}) > 1 and any(c.p_recover == 0.0 for c in front):
        return 'priced_recovery'
    if len(front) > 1:
        return 'quality_tradeoff'
    return 'single_quality_point'


# ------------------------------------------------------------- the decision --

@dataclass(frozen=True)
class JointDecision:
    state_hash: str
    fault_views: Tuple[Tuple[str, str], ...]      # (node, "layer/persistence/conf")
    candidates: Tuple[Candidate, ...]
    rejected: Tuple[dict, ...]
    frontier: Tuple[str, ...]
    regime: str
    chosen: Optional[str]
    forced_unique: bool
    rationale: str
    assignments: Tuple[Tuple[str, str], ...]      # (node, model) to execute now
    split_of: Optional[str] = None                # node to split (executor applies)

    def hash_hex(self) -> str:
        import hashlib, json
        payload = json.dumps({
            'chosen': self.chosen, 'regime': self.regime,
            'frontier': list(self.frontier),
            'assignments': [list(a) for a in self.assignments],
            'split_of': self.split_of,
            'candidates': [c.name for c in self.candidates]}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _state_hash(state: EngineState) -> str:
    import hashlib
    return hashlib.sha256(repr(state).encode()).hexdigest()[:16]


def decide(state: EngineState) -> JointDecision:
    """Pure decision function. Normal execution when no faulted nodes.
    P0 fixes: E1 — the no-fault path passes the SAME gross constraint checks
    (budget/deadline/slots) as the faulted path; E3 — split_of comes from
    the CHOSEN candidate's target node, never from faulted[0]."""
    faulted = sorted([n for n in state.nodes if n.status == 'failed'],
                     key=lambda n: n.node_id)
    ready = sorted([n for n in state.nodes if n.status == 'pending'
                    and all(state.node(par).status == 'done'
                            for par in n.parents)],
                   key=lambda n: n.node_id)
    n_ready = len(ready)
    p = state.params

    if not faulted:
        # E1: normal execution is constraint-gated exactly like recovery
        why = []
        reserve_tok = n_ready * p.reserve_per_call_tok
        reserve_lat = n_ready * p.reserve_latency_s_per_call
        if reserve_tok > state.budget_remaining:
            why.append(f'budget: gross reserve {reserve_tok} > remaining '
                       f'{state.budget_remaining}')
        if reserve_lat > state.deadline_remaining_s:
            why.append(f'deadline: reserve {reserve_lat:.0f}s > remaining '
                       f'{state.deadline_remaining_s:.0f}s')
        demand: Dict[str, int] = {}
        for n in ready:
            demand[n.model] = demand.get(n.model, 0) + 1
        for m in sorted(demand):
            free = dict(state.slots_total).get(m, 0) - dict(state.slots_in_use).get(m, 0)
            if demand[m] > free:
                why.append(f'slots: model {m} planned {demand[m]} > free {free}')
        if why or n_ready == 0:
            return JointDecision(
                state_hash=_state_hash(state), fault_views=(), candidates=(),
                rejected=({'candidate': 'normal_execution', 'reasons': why},) if why else (),
                frontier=('normal_execution',) if not why else (),
                regime='no_fault',
                chosen='normal_execution' if not why else None,
                forced_unique=True,
                rationale='no faulted nodes: execute ready set under current pi'
                if not why else
                'normal execution blocked by constraints: '
                + '; '.join(why) + ' (stop with audit trail)',
                assignments=())
        assigns = tuple((n.node_id, n.model) for n in ready)   # done never included (#3)
        return JointDecision(
            state_hash=_state_hash(state), fault_views=(), candidates=(),
            rejected=(), frontier=('normal_execution',),
            regime='no_fault', chosen='normal_execution', forced_unique=True,
            rationale='no faulted nodes: execute ready set under current pi',
            assignments=assigns)

    cands = generate_candidates(state, faulted)
    kept, rejected = constraint_filter(cands, state, n_ready, ready)
    front = pareto_frontier(kept) if kept else []
    regime = detect_regime(front, kept)

    # selection: stated preference. P0/E6 (+audit clarification): reliability
    # (p_recover) is the primary feasible axis; ties break on COST then
    # latency then name. Quantified quality (dq_hat, n=1 UNVALIDATED
    # calibration) is RECORDED and REPORTED per candidate but does NOT enter
    # the ranking: an unquantified quality estimate is incomparable, and
    # mapping None to a numeric rank would systematically favour whichever
    # candidates happen to carry a (single-cell) estimate. Promotion of dq
    # into selection requires replicated node-level Q evidence (M1 gap).
    # If frontier >1 the choice is a RECOMMENDATION under the stated
    # preference (acceptance #8).
    if kept:
        chosen_c = max(sorted(kept, key=lambda c: c.name),
                       key=lambda c: (-1.0 if c.p_recover is None else c.p_recover,
                                      -c.dc_hat, -c.dl_hat, c.name))
    else:
        chosen_c = None
    forced_unique = bool(regime == 'single_arm_dominance' or len(front) <= 1)

    assigns: List[Tuple[str, str]] = []
    split_of = None
    if chosen_c is not None:
        for n in ready:
            model = n.model
            if chosen_c.pi[0] == 'SWITCH_STRONG' and n.node_id in chosen_c.pi[1]:
                model = switch_target_model(n, state)
            assigns.append((n.node_id, model))
        if chosen_c.z == 'SPLIT_VERIFY':
            # E3: split target is the CHOSEN candidate's node
            split_of = _candidate_node(chosen_c)
        elif chosen_c.r[0] in ('RETRY_SAME', 'ONE_RETRY_THEN_EXIT',
                               'ONE_CONSERVATIVE_RETRY'):
            for nid in chosen_c.r[1]:
                node = state.node(nid)
                if node.status == 'done':
                    raise AssertionError('re-execution of done node')   # #3
                model = node.model
                if chosen_c.pi[0] == 'SWITCH_STRONG' and nid in chosen_c.pi[1]:
                    model = switch_target_model(node, state)
                assigns.append((nid, model))

    views = []
    for n in faulted:
        v = classify(n, state)
        views.append((n.node_id,
                      f"{v['layer']}/{v['persistence']}/{v['confidence']}"))
    return JointDecision(
        state_hash=_state_hash(state), fault_views=tuple(views),
        candidates=tuple(sorted(cands, key=lambda c: c.name)),
        rejected=tuple(sorted(rejected, key=lambda r: r['candidate'])),
        frontier=tuple(c.name for c in front), regime=regime,
        chosen=chosen_c.name if chosen_c else None,
        forced_unique=forced_unique,
        rationale=chosen_c.rationale if chosen_c else
                  'all candidates rejected by constraints: stop with audit trail',
        assignments=tuple(sorted(assigns)), split_of=split_of)


# ---------------------------------------------------- executor-side Z transform

def apply_split(state: EngineState, node_id: str,
                switch_children: bool = False) -> EngineState:
    """Build per-lineage children: child_i consumes exactly one parent
    lineage; downstream edges of the faulted node attach to ALL children
    (H1 G5 semantics). P0 fixes:
      E4 — removes BOTH in-edges and out-edges of the faulted node;
           downstream parents are UNIONed (other original parents such as an
           independent p3 are PRESERVED, never overwritten);
           structural integrity asserted (no dangling edges, parents/edges
           consistent, acyclic).
      E7 — children keep the faulted node's model by default; a model switch
           requires explicit authorization (switch_children=True, set only
           when the chosen candidate's pi is SWITCH_STRONG). Split NEVER
           implicitly reassigns models."""
    node = state.node(node_id)
    assert split_legal(node, state)[0], 'split not legal'
    suffix = ['_a', '_b', '_c', '_d']
    children = []
    child_model = switch_target_model(node, state) if switch_children \
        else node.model
    new_nodes = [n for n in state.nodes if n.node_id != node_id]
    # E4: remove edges on BOTH sides of the faulted node (in-edges to it
    # would otherwise dangle after its removal)
    new_edges = [(a, b) for a, b in state.edges
                 if a != node_id and b != node_id]
    for i, par in enumerate(sorted(node.parents)):
        cid = node_id + suffix[i]
        children.append(cid)
        new_nodes.append(replace(node, node_id=cid, parents=(par,),
                                 status='pending', attempts=0,
                                 last_failure_type=None,
                                 failure_signature_seen=False,
                                 model=child_model))
        new_edges.append((par, cid))
    downs = tuple(sorted(state.children_of(node_id)))
    for c in downs:                       # downstream consumers
        for ch in children:
            new_edges.append((ch, c))
    # E4: UNION downstream parents — replace ONLY the faulted node's slot,
    # preserve every other original parent
    new_nodes = [replace(n, parents=tuple(sorted(
                    set(n.parents) - {node_id} | set(children))))
                 if n.node_id in downs else n for n in new_nodes]
    new_state = replace(state, nodes=tuple(sorted(new_nodes, key=lambda n: n.node_id)),
                        edges=tuple(sorted(new_edges)),
                        dag_version=state.dag_version + 1)
    assert _acyclic(new_state), 'split produced a cycle or dangling edge'  # E4/#2
    _assert_structure(new_state)
    return new_state


def _assert_structure(state: EngineState) -> None:
    """E4: parents fields and edges must be consistent, and every edge
    endpoint must exist (dangling edges are structural corruption)."""
    node_ids = {n.node_id for n in state.nodes}
    for a, b in state.edges:
        assert a in node_ids and b in node_ids, f'dangling edge {a}->{b}'
    for n in state.nodes:
        declared = set(n.parents)
        incoming = {a for a, b in state.edges if b == n.node_id}
        assert declared == incoming, \
            f'{n.node_id}: parents {sorted(declared)} != incoming ' \
            f'{sorted(incoming)} (representation divergence)'


def _acyclic(state: EngineState) -> bool:
    """E4-strict: dangling edges (endpoints outside the node set) now FAIL
    the check instead of being silently ignored."""
    nodes = {n.node_id for n in state.nodes}
    indeg = {nid: 0 for nid in nodes}
    adj = {nid: [] for nid in nodes}
    for a, b in state.edges:
        if a not in nodes or b not in nodes:
            return False                      # dangling edge = illegal structure
        indeg[b] += 1
        adj[a].append(b)
    queue = sorted(n for n, d in indeg.items() if d == 0)
    seen = 0
    while queue:
        n = queue.pop()
        seen += 1
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    return seen == len(nodes)
