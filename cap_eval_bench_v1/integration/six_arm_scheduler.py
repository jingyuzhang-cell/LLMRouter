"""Stage-C-R1 six-arm decision layer (PRODUCTION, zero-call testable).

This module is the DECISION layer only. The production executor is
integration/stage_c_r1.py, which drives these decide() functions against
the real evidence store (stage_c_evidence/), real per-task DAGs, real
silver scorer and (for real runs) the pilot Meter behind the auth gate.

Fixes over the pre-audit draft (operator ruling 2026-10-30):
  FIX-1  Static-Parallel is explicitly an UNRECOVERED weak baseline:
         it never retries a failed node; its Q gap vs Joint is NOT
         attributable to joint optimization (ARM_META carries the flag and
         every trace records it).
  FIX-2  R-only performs a REAL comparison over the legal recovery-set
         family under the frozen objective and constraints — it does not
         mechanically pick the minimal set.
  FIX-3  Z operations are gated by task-contract + dependency legality
         predicates. With no legal non-IDENTITY Z the arm keeps KEEP and
         records why. The Z space is the frozen one:
         {KEEP, SPLIT_VERIFY, MERGE, SUBSTITUTE_EV, ADJUST_DEP} — no
         invented ops, no fabricated nodes.

All six arms share ONE executor, ONE frozen DAG per task, ONE fault state,
ONE resource constraint set, ONE evidence store and ONE scorer.
"""
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# frozen priors (decision inputs only; measured outcomes come from the
# executor's adapter / real calls). PROFILE_Q is the frozen V3 capability
# table lifted verbatim from integration/phase2_stage_c.py.
# ---------------------------------------------------------------------------
PROFILE_Q = {
    'index':          {'glm53': 0.85, 'glm53flash': 0.62},
    'extracts':       {'glm53': 0.85, 'glm53flash': 0.62},
    'timeline':       {'glm53': 0.75, 'glm53flash': 0.60},
    'entity_facts':   {'glm53': 0.80, 'glm53flash': 0.58},
    'factcheck_full': {'glm53': 0.83, 'glm53flash': 0.80},
    'report':         {'glm53': 0.85, 'glm53flash': 0.60},
    # real task-DAG kind names (stage_c_evidence/tasks.json): mirror the
    # frozen v3 entries of their template counterparts
    'reasoning':      {'glm53': 0.80, 'glm53flash': 0.58},
    'verification':   {'glm53': 0.83, 'glm53flash': 0.80},
}
TOKENS_PRIOR = {'glm53': 1100, 'glm53flash': 1400}   # Stage-B: flash ≈1.5× tokens
LATENCY_PRIOR = {'glm53': 8.0, 'glm53flash': 10.0}   # Stage-B: flash ≈1.2× latency
LAMBDA_TOK = 1e-5                                      # utility cost per token
# Credibility decay applies ONLY to SYSTEMATIC failure types (port-contract
# violation, parse, evidence): a repeated identical retry is evidence the
# model cannot satisfy the node contract at that scope. Transient transport
# faults do NOT decay — a network blip says nothing about model capability.
# Switching model resets the decay; freshly created (split) nodes are
# narrower-scope and carry no failure history.
SYSTEMATIC_FAILURES = {'contract', 'parse', 'evidence'}
SUCCESS_DECAY = 0.5
MODELS = ('glm53', 'glm53flash')

ARM_META = {
    'Static-Parallel': dict(
        recovers=False,
        baseline_type='no-recovery weak baseline',
        attribution_note='Q gap vs adaptive arms reflects absence of any '
                         'recovery, NOT the value of joint optimization'),
    'Simple-Dynamic': dict(recovers=True, baseline_type='single-node escalation'),
    'R-only': dict(recovers=True, baseline_type='recovery-set search'),
    'pi-only': dict(recovers=True, baseline_type='model reassignment'),
    'Joint(R,pi)': dict(recovers=True, baseline_type='joint R x pi'),
    'Joint(Z,R,pi)': dict(recovers=True, baseline_type='joint Z x R x pi'),
}
ARMS = list(ARM_META)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
@dataclass
class NodeState:
    node_id: str
    kind: str
    subtask: str = ''
    model: str = 'glm53'          # current π assignment
    status: str = 'pending'       # pending|running|done|failed|blocked
    output: Optional[dict] = None
    usage: dict = field(default_factory=lambda: {'in': 0, 'out': 0})
    latency_s: float = 0.0
    wait_s: float = 0.0
    attempts: int = 0
    version: int = 0              # increments on every (re)execution
    failure_type: Optional[str] = None


@dataclass
class DAGState:
    nodes: Dict[str, NodeState]
    deps: Dict[str, List[str]]    # node -> parents (frozen task DAG)
    kinds: Dict[str, str]
    subtasks: Dict[str, str]
    deadline_s: float
    budget_remaining: float       # tokens
    t_now: float = 0.0            # virtual clock
    # z-applied structure (ADJUST_DEP removes edges; SPLIT_VERIFY adds nodes)
    active_deps: Dict[str, List[str]] = field(default_factory=dict)
    z_ops_applied: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.active_deps:
            self.active_deps = {k: list(v) for k, v in self.deps.items()}

    def parents(self, nid) -> List[str]:
        return self.active_deps.get(nid, [])

    def ready_nodes(self) -> List[str]:
        return [nid for nid, n in self.nodes.items()
                if n.status == 'pending'
                and all(self.nodes[p].status == 'done' for p in self.parents(nid))]

    def blocked_nodes(self) -> List[str]:
        return [nid for nid, n in self.nodes.items()
                if n.status in ('pending', 'blocked')
                and any(self.nodes[p].status == 'failed' for p in self.parents(nid))]

    def failed_nodes(self) -> List[str]:
        return [nid for nid, n in self.nodes.items() if n.status == 'failed']

    def downstream(self, nid) -> Set[str]:
        result, frontier = set(), {nid}
        while frontier:
            new = set()
            for cand, ps in self.active_deps.items():
                if cand not in result and any(p in frontier for p in ps):
                    new.add(cand)
            result |= new
            frontier = new
        return result - {nid}

    def terminal(self) -> str:
        return [nid for nid in self.nodes if not self.downstream(nid)][0]


@dataclass
class SchedulingDecision:
    action_type: str                       # execute | recover | terminate
    assignments: List[Tuple[str, str]]     # (node_id, model) to execute now
    recovery_set: Set[str] = field(default_factory=set)
    z_op: str = 'KEEP'
    z_detail: str = ''
    reoptimize: List[Tuple[str, str]] = field(default_factory=list)  # π updates
    rationale: str = ''


# ---------------------------------------------------------------------------
# frozen objective (shared by R-only and the two Joint arms)
# ---------------------------------------------------------------------------
def _q_terminal_hat(state: DAGState, r_set: Set[str], pi_updates: Dict[str, str]) -> float:
    """Multiplicative quality propagation along the heaviest parent path,
    using the frozen PROFILE_Q. Healthy cached nodes keep their executed
    model's factor; nodes in R use their π-updated model."""
    memo: Dict[str, float] = {}

    def q(nid: str) -> float:
        if nid in memo:
            return memo[nid]
        node = state.nodes[nid]
        model = pi_updates.get(nid, node.model)
        base = PROFILE_Q.get(node.kind, {}).get(model, 0.5)
        if (nid in r_set and node.attempts > 0 and node.model == model
                and node.failure_type in SYSTEMATIC_FAILURES):
            base *= SUCCESS_DECAY ** node.attempts
        ps = state.parents(nid)
        val = base * (max((q(p) for p in ps), default=1.0))
        memo[nid] = val if node.status != 'failed' or nid in r_set else 0.0
        return val

    return q(state.terminal())


def _cost_hat(r_set: Set[str], pi_updates: Dict[str, str], state: DAGState) -> Tuple[float, float]:
    toks = sum(TOKENS_PRIOR[pi_updates.get(n, state.nodes[n].model)] for n in r_set)
    lat = max((LATENCY_PRIOR[pi_updates.get(n, state.nodes[n].model)] for n in r_set),
              default=0.0)  # parallel within R under K_m>=1
    return toks, lat


def frozen_objective(state: DAGState, r_set: Set[str],
                     pi_updates: Dict[str, str]) -> float:
    toks, lat = _cost_hat(r_set, pi_updates, state)
    met = 1.0 if state.t_now + lat <= state.deadline_s else 0.0
    q = _q_terminal_hat(state, r_set, pi_updates)
    return q * met - LAMBDA_TOK * toks


def legal_recovery_sets(state: DAGState) -> List[Set[str]]:
    """The legal R family for the current failed nodes: any subset of
    {f} ∪ downstream(f) containing f (re-execution superset), constrained
    by remaining budget. Downstream sets here are ≤5 nodes → ≤32 subsets."""
    failed = state.failed_nodes()
    if not failed:
        return []
    universe: Set[str] = set()
    for f in failed:
        universe |= {f} | state.downstream(f)
    out = []
    for k in range(len(universe) + 1):
        for sub in itertools.combinations(sorted(universe), k):
            s = set(sub)
            if all(f in s for f in failed):
                toks, _ = _cost_hat(s, {}, state)
                if toks <= state.budget_remaining:
                    out.append(s)
    return out


def best_pi_for(state: DAGState, nodes: List[str], budget: float) -> Dict[str, str]:
    """Greedy π under budget: assign glm53 while tokens allow, else flash."""
    pi, spent = {}, 0.0
    for nid in nodes:
        if spent + TOKENS_PRIOR['glm53'] <= budget:
            pi[nid] = 'glm53'
            spent += TOKENS_PRIOR['glm53']
        else:
            pi[nid] = 'glm53flash'
    return pi


# ---------------------------------------------------------------------------
# FIX-3: Z legality predicates (frozen Z space, task-contract + dependency
# legality basis; no invented operations)
# ---------------------------------------------------------------------------
VERIFY_KINDS = {'factcheck_full', 'timeline', 'verification'}


def z_candidates(state: DAGState) -> List[Tuple[str, str]]:
    """Legal (op, detail) list for the CURRENT failure. Each entry carries
    its legality basis; KEEP is always legal."""
    cands = [('KEEP', 'default: no structure change')]
    failed = set(state.failed_nodes())
    if not failed:
        return cands

    # SPLIT_VERIFY: split a failed verify-capable node with >=2 healthy
    # parents of distinct kinds into per-lineage verifiers feeding the same
    # child. Legality: contract kind, parent health, lineage distinctness,
    # acyclicity (children unchanged, split nodes only read parents).
    for f in sorted(failed):
        n = state.nodes[f]
        ps = [p for p in state.parents(f)]
        if (n.kind in VERIFY_KINDS and len(ps) >= 2
                and len({state.nodes[p].kind for p in ps}) >= 2
                and all(state.nodes[p].status == 'done' for p in ps)):
            cands.append(('SPLIT_VERIFY', f'{f} -> per-lineage verifiers over '
                                           f'parents {ps} (kind={n.kind})'))

    # MERGE: two healthy same-kind siblings with identical parent sets and
    # non-disjoint evidence focus. Legality requires contract compatibility.
    # (Checked but expected EMPTY on the current task set — recorded.)
    ids = sorted(state.nodes)
    for a, b in itertools.combinations(ids, 2):
        na, nb = state.nodes[a], state.nodes[b]
        if (na.kind == nb.kind and na.kind != 'report'
                and state.parents(a) and state.parents(a) == state.parents(b)
                and na.status == 'done' and nb.status == 'done'):
            docs_a = set(na.subtask.split('，')[:1])
            docs_b = set(nb.subtask.split('，')[:1])
            if docs_a & docs_b:
                cands.append(('MERGE', f'{a}+{b} same kind/parents, focus overlap'))

    # ADJUST_DEP: remove a transitively-redundant edge u->v (u still reaches
    # v through other paths). Legality: reachability preserved, DAG acyclic.
    for v, ps in state.active_deps.items():
        for u in ps:
            rest = [p for p in ps if p != u]
            if any(_reaches(state, u, w) for w in rest):
                cands.append(('ADJUST_DEP', f'drop redundant edge {u}->{v}'))
                break

    # SUBSTITUTE_EV: alternate doc with same event identity — none in the
    # frozen store (each doc_id unique, no alternates). Recorded as illegal.
    return cands


def _reaches(state: DAGState, u: str, v: str) -> bool:
    stack, seen = [u], set()
    while stack:
        x = stack.pop()
        for c, ps in state.active_deps.items():
            if x in ps and c not in seen:
                if c == v:
                    return True
                seen.add(c)
                stack.append(c)
    return False


# ---------------------------------------------------------------------------
# six arm decide() functions
# ---------------------------------------------------------------------------
def _normal(state: DAGState, who: str) -> SchedulingDecision:
    """Healthy-state decision shared by all arms: execute ready nodes under
    the current (frozen initial) π. Arms diverge only AFTER an anomaly."""
    ready = state.ready_nodes()
    if not ready:
        return SchedulingDecision('terminate', [],
                                  rationale=f'{who}: no ready nodes')
    return SchedulingDecision('execute',
                              [(n, state.nodes[n].model) for n in ready],
                              z_op='KEEP', rationale=f'{who}: normal execution')


def decide_StaticParallel(state: DAGState) -> SchedulingDecision:
    """FIX-1: static π, NO recovery — weak baseline by construction."""
    ready = state.ready_nodes()
    if not ready and not state.failed_nodes():
        return SchedulingDecision('terminate', [], rationale='nothing ready')
    return SchedulingDecision(
        'execute', [(n, state.nodes[n].model) for n in ready], z_op='KEEP',
        rationale='FIX-1 weak baseline: frozen π, failed nodes are NOT '
                  'recovered; blocked descendants stay blocked')


def decide_SimpleDynamic(state: DAGState) -> SchedulingDecision:
    failed = [n for n in state.failed_nodes()
              if state.nodes[n].attempts < 2]
    assignments = []
    for nid in failed:
        stronger = 'glm53' if state.nodes[nid].model != 'glm53' else 'glm53'
        assignments.append((nid, stronger))
    assignments += [(n, state.nodes[n].model) for n in state.ready_nodes()
                    if n not in {a for a, _ in assignments}]
    return SchedulingDecision(
        'recover' if failed else 'execute', assignments,
        recovery_set=set(failed), z_op='KEEP',
        rationale=f'simple-dynamic: escalate failed {failed} to stronger model')


def decide_R_only(state: DAGState) -> SchedulingDecision:
    """FIX-2: REAL comparison over the legal R family under the frozen
    objective — not the mechanical minimal set."""
    if not state.failed_nodes():
        return _normal(state, 'r_only')
    family = legal_recovery_sets(state)
    if not family:
        return SchedulingDecision('terminate', [], rationale='no legal R')
    scored = [(frozen_objective(state, r, {}), r) for r in family]
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    best_u, best_r = scored[0]
    # deterministic tie note: smallest set wins ties (sort above)
    return SchedulingDecision(
        'recover', [(n, state.nodes[n].model) for n in sorted(best_r)],
        recovery_set=best_r, z_op='KEEP',
        rationale=f'FIX-2 real comparison: {len(family)} legal sets, '
                  f'argmax U={best_u:.5f} -> R={sorted(best_r)} '
                  f'(runner-up U={scored[1][0]:.5f} R={sorted(scored[1][1])})'
                  if len(scored) > 1 else f'argmax U={best_u:.5f}')


def decide_pi_only(state: DAGState) -> SchedulingDecision:
    if not state.failed_nodes():
        return _normal(state, 'pi_only')
    failed = list(state.failed_nodes())
    remaining = [n for n in state.nodes
                 if state.nodes[n].status in ('pending', 'failed')]
    pi = best_pi_for(state, remaining, state.budget_remaining)
    assignments = [(n, pi[n]) for n in sorted(set(failed) | set(state.ready_nodes()))]
    updates = [(n, pi[n]) for n in remaining]
    return SchedulingDecision(
        'recover' if failed else 'execute', assignments,
        recovery_set=set(failed), reoptimize=updates,
        rationale=f'pi-only: retry {{failed}} + re-optimize π over '
                  f'{len(remaining)} remaining nodes')


def decide_Joint_R_pi(state: DAGState) -> SchedulingDecision:
    if not state.failed_nodes():
        return _normal(state, 'joint_r_pi')
    family = legal_recovery_sets(state)
    if not family:
        return SchedulingDecision('terminate', [], rationale='no legal R')
    best = None
    for r in family:
        for pi_mode in ('keep', 'strong', 'budget'):
            rem = sorted(r | {n for n in state.nodes
                              if state.nodes[n].status == 'pending'})
            if pi_mode == 'keep':
                pi = {}
            elif pi_mode == 'strong':
                pi = {n: 'glm53' for n in rem}
            else:
                pi = best_pi_for(state, rem, state.budget_remaining)
            u = frozen_objective(state, r, pi)
            if best is None or u > best[0]:
                best = (u, r, pi, pi_mode)
    u, r, pi, mode = best
    assignments = [(n, pi.get(n, state.nodes[n].model))
                   for n in sorted(r | set(state.ready_nodes()))]
    return SchedulingDecision(
        'recover', assignments, recovery_set=r,
        reoptimize=sorted(pi.items()), z_op='KEEP',
        rationale=f'joint(R,π): {len(family)} legal R × 3 π modes, '
                  f'argmax U={u:.5f} -> R={sorted(r)}, π={mode}')


def _copy_state(state: DAGState) -> DAGState:
    return DAGState(nodes=dict(state.nodes), deps=state.deps,
                    kinds=dict(state.kinds), subtasks=dict(state.subtasks),
                    deadline_s=state.deadline_s,
                    budget_remaining=state.budget_remaining,
                    t_now=state.t_now,
                    active_deps={k: list(v) for k, v in state.active_deps.items()},
                    z_ops_applied=list(state.z_ops_applied))


def _simulate_split(state: DAGState, target: str) -> Optional[DAGState]:
    """Decision-time structural simulation of SPLIT_VERIFY. Semantics kept
    deliberately in sync with the executor's apply_z."""
    ps = state.parents(target)
    if len(ps) < 2:
        return None
    child = next((c for c, cds in state.active_deps.items() if target in cds),
                 None)
    sim = _copy_state(state)
    for suf, p in zip(('_a', '_b'), ps[:2]):
        nid = target + suf
        sim.nodes[nid] = NodeState(nid, state.nodes[target].kind,
                                   model='glm53')
        sim.kinds[nid] = state.nodes[target].kind
        sim.active_deps[nid] = [p]
        if child:
            sim.active_deps[child] = sim.active_deps.get(child, []) + [nid]
    sim.nodes.pop(target)
    sim.active_deps.pop(target, None)
    if child:
        sim.active_deps[child] = [p for p in sim.active_deps[child]
                                  if p != target]
    return sim


def _dedupe(assignments):
    seen, out = set(), []
    for n, m in assignments:
        if n not in seen:
            seen.add(n)
            out.append((n, m))
    return out


def decide_Joint_Z_R_pi(state: DAGState) -> SchedulingDecision:
    base = decide_Joint_R_pi(state)
    zs = z_candidates(state)
    best_u = frozen_objective(state, base.recovery_set, dict(base.reoptimize))
    best = (best_u, 'KEEP', '')
    for z_op, detail in zs:
        if z_op == 'KEEP':
            continue
        if z_op == 'SPLIT_VERIFY':
            if state.budget_remaining < 2 * TOKENS_PRIOR['glm53']:
                continue
            target = detail.split(' -> ')[0]
            sim = _simulate_split(state, target)
            if sim is None:
                continue
            pi2 = dict(base.reoptimize)
            pi2[f'{target}_a'] = 'glm53'
            pi2[f'{target}_b'] = 'glm53'
            r2 = (set(base.recovery_set) - {target}) | {
                f'{target}_a', f'{target}_b'}
            u = frozen_objective(sim, r2, pi2)
            if u > best_u:
                best = (u, 'SPLIT_VERIFY', detail)
        # MERGE / ADJUST_DEP legality is enumerable but neither can beat
        # KEEP under the frozen objective for current failure semantics
        # (merge drops coverage; redundant-edge removal does not change the
        # quality factors) — recorded, not selected; see acceptance report.
    u, z_op, z_detail = best
    base.z_op, base.z_detail = z_op, z_detail
    if z_op == 'SPLIT_VERIFY':
        target = z_detail.split(' -> ')[0]
        base.assignments = _dedupe([
            (f'{target}_a', 'glm53') if n == target else
            (f'{target}_b', 'glm53') if n == target else (n, m)
            for n, m in base.assignments])
        base.recovery_set = (set(base.recovery_set) - {target}) | {
            f'{target}_a', f'{target}_b'}
    base.rationale += (
        f' | Z-space={[z for z, _ in zs]} -> {z_op} '
        f'(U_keep={best_u:.5f}'
        + (f', U_split={u:.5f})' if z_op == 'SPLIT_VERIFY' else ')'))
    return base


ARM_DECIDERS = {
    'Static-Parallel': decide_StaticParallel,
    'Simple-Dynamic': decide_SimpleDynamic,
    'R-only': decide_R_only,
    'pi-only': decide_pi_only,
    'Joint(R,pi)': decide_Joint_R_pi,
    'Joint(Z,R,pi)': decide_Joint_Z_R_pi,
}
