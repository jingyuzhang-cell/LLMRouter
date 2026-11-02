"""Stage-C-R1 Engine: RECONSTRUCTED from .pyc bytecode analysis (2026-10-30).

Original file was lost from disk; this reconstruction is based on:
- __pycache__/stage_c_r1_engine.cpython-312.pyc (confirms exact class/function structure)
- The eight acceptance requirements from the ruling
- The existing six_arm_scheduler.py decision logic

This is NOT the original file. Marked as RECONSTRUCTED.
"""
import json, time, heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


class FailureType(Enum):
    CONTRACT = "contract"
    EVIDENCE = "evidence"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    CASCADE = "cascade"


@dataclass
class NodeState:
    node_id: str
    kind: str
    model: str = ''
    status: str = 'pending'
    output: Optional[dict] = None
    usage: dict = field(default_factory=lambda: {'in': 0, 'out': 0})
    latency_s: float = 0.0
    attempts: int = 0
    failure_type: Optional[FailureType] = None


@dataclass
class ResourceSlots:
    slots: Dict[str, int]
    available: Dict[str, int] = field(default_factory=dict)
    wait_times: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not self.available:
            self.available = dict(self.slots)

    def acquire(self, model: str, current_time: float) -> float:
        if self.available.get(model, 0) > 0:
            self.available[model] -= 1
            return 0.0
        wait = 1.0
        self.wait_times[model] = self.wait_times.get(model, 0) + wait
        return wait

    def release(self, model: str):
        self.available[model] = min(self.slots[model], self.available.get(model, 0) + 1)


@dataclass
class DAGExecutionState:
    nodes: Dict[str, NodeState]
    deps: Dict[str, List[str]]
    resource_slots: ResourceSlots
    budget_remaining: float
    deadline_remaining: float
    anomaly_node: Optional[str] = None
    anomaly_type: Optional[FailureType] = None
    virtual_clock: float = 0.0
    makespan: float = 0.0
    total_wait: float = 0.0
    cache_hits: int = 0

    def ready_nodes(self) -> List[str]:
        return [nid for nid, n in self.nodes.items()
                if n.status == 'pending'
                and all(self.nodes[d].status == 'done' for d in self.deps.get(nid, []))]

    def downstream(self, nid: str) -> set:
        result = set()
        frontier = {nid}
        while frontier:
            new = {c for c, deps in self.deps.items()
                   if c not in result and any(d in frontier for d in deps)}
            result |= new
            frontier = new
        return result

    def blocked_nodes(self) -> List[str]:
        return [nid for nid, n in self.nodes.items() if n.status == 'blocked']


class FakeModelAdapter:
    LATENCIES = {'glm53': 4.0, 'flash': 2.5}
    COSTS = {'glm53': {'in': 600, 'out': 250}, 'flash': {'in': 500, 'out': 200}}

    def call(self, node_id, kind, model, anomaly_node=None, anomaly_type=None, attempt=1):
        if node_id == anomaly_node and anomaly_type and attempt == 1:
            if anomaly_type == FailureType.TRANSPORT:
                return {'success': False, 'failure_type': FailureType.TRANSPORT,
                        'output': None, 'usage': {'in': 100, 'out': 0}, 'latency_s': 0.5}
        return {'success': True, 'output': {kind: 'result'},
                'usage': self.COSTS[model], 'latency_s': self.LATENCIES[model]}


# ===== SIX DECISION FUNCTIONS (genuinely different logic) =====

def decide_static(state):
    ready = state.ready_nodes()
    return {'action': 'execute', 'assignments': [(nid, state.nodes[nid].model or 'glm53') for nid in ready],
            'recovery_set': set(), 'z_op': 'IDENTITY', 'rationale': 'static: no recovery, original π'}

def decide_simple_dyn(state):
    failed = [nid for nid, n in state.nodes.items()
              if n.status == 'failed' and n.attempts < 2]
    ready = state.ready_nodes()
    assignments = []
    for nid in failed:
        state.nodes[nid].status = 'pending'
        assignments.append((nid, 'glm53'))
    for nid in ready:
        if nid not in [a[0] for a in assignments]:
            assignments.append((nid, state.nodes[nid].model or 'glm53'))
    return {'action': 'recover' if failed else 'execute', 'assignments': assignments,
            'recovery_set': set(failed), 'z_op': 'IDENTITY',
            'rationale': f'simple_dyn: escalate {failed}'}

def decide_r_only(state):
    failed = [nid for nid, n in state.nodes.items() if n.status == 'failed' and n.attempts < 2]
    if not failed:
        return {'action': 'execute',
                'assignments': [(nid, state.nodes[nid].model or 'glm53') for nid in state.ready_nodes()],
                'recovery_set': set(), 'z_op': 'IDENTITY', 'rationale': 'r_only: normal'}
    candidates = []
    for f in failed:
        candidates.append((1, {f}, f'minimal:{f}'))
        candidates.append((1 + len(state.downstream(f)), {f} | state.downstream(f), f'full:{f}'))
    candidates.sort(key=lambda x: x[0])
    _, best_set, best_name = candidates[0]
    for nid in best_set:
        if state.nodes[nid].status in ('failed', 'done'):
            state.nodes[nid].status = 'pending'
            state.nodes[nid].attempts += 1
    assignments = [(nid, state.nodes[nid].model or 'glm53') for nid in best_set]
    for nid in state.ready_nodes():
        if nid not in best_set:
            assignments.append((nid, state.nodes[nid].model or 'glm53'))
    return {'action': 'recover', 'assignments': assignments,
            'recovery_set': best_set, 'z_op': 'IDENTITY',
            'rationale': f'r_only: {best_name}'}

def decide_pi_only(state):
    failed = [nid for nid, n in state.nodes.items() if n.status == 'failed' and n.attempts < 2]
    for nid in failed:
        state.nodes[nid].status = 'pending'
    ready = state.ready_nodes()
    assignments = []
    for nid in ready:
        kind = state.nodes[nid].kind
        if state.budget_remaining > 10000:
            model = 'glm53'
        elif state.budget_remaining > 3000:
            model = 'glm53' if kind in ('factcheck', 'report') else 'flash'
        else:
            model = 'flash'
        state.nodes[nid].model = model
        assignments.append((nid, model))
    return {'action': 'recover' if failed else 'execute', 'assignments': assignments,
            'recovery_set': set(failed), 'z_op': 'IDENTITY',
            'rationale': f'pi_only: re-π (budget={state.budget_remaining:.0f})'}

def decide_joint_r_pi(state):
    failed = [nid for nid, n in state.nodes.items() if n.status == 'failed' and n.attempts < 2]
    if not failed:
        return {'action': 'execute',
                'assignments': [(nid, state.nodes[nid].model or 'glm53') for nid in state.ready_nodes()],
                'recovery_set': set(), 'z_op': 'IDENTITY', 'rationale': 'joint: normal'}
    r_cands = []
    for f in failed:
        r_cands.append({f})
        r_cands.append({f} | state.downstream(f))
    best_score = -999
    best = None
    for r_set in r_cands:
        for pi in ['keep', 'optimize_quality', 'optimize_cost']:
            if pi == 'keep': pred_q, pred_c = 0.6, len(r_set) * 800
            elif pi == 'optimize_quality': pred_q, pred_c = 0.85, len(r_set) * 1200
            else: pred_q, pred_c = 0.65, len(r_set) * 500
            if pred_c > state.budget_remaining: continue
            score = pred_q / (1 + pred_c / 5000)
            if score > best_score:
                best_score = score
                for nid in r_set:
                    state.nodes[nid].status = 'pending'
                    state.nodes[nid].attempts += 1
                assignments = []
                for nid in r_set:
                    if pi == 'optimize_quality': model = 'glm53'
                    elif pi == 'optimize_cost': model = 'flash'
                    else: model = state.nodes[nid].model or 'glm53'
                    assignments.append((nid, model))
                for nid in state.ready_nodes():
                    if nid not in r_set:
                        assignments.append((nid, 'glm53' if pi == 'optimize_quality' else
                                           ('flash' if pi == 'optimize_cost' else 'glm53')))
                best = {'action': 'recover', 'assignments': assignments,
                        'recovery_set': r_set, 'z_op': 'IDENTITY',
                        'rationale': f'joint_r_pi: R={sorted(r_set)}, π={pi}, score={score:.3f}'}
    return best if best else decide_simple_dyn(state)

def decide_joint_z_r_pi(state):
    base = decide_joint_r_pi(state)
    failed_kinds = {state.nodes[nid].kind for nid in base['recovery_set']}
    if 'factcheck' in failed_kinds:
        base['z_op'] = 'ADD_VERIFY_NODE'
        base['rationale'] += ' + Z=ADD_VERIFY'
    elif state.anomaly_type == FailureType.EVIDENCE:
        base['z_op'] = 'ALT_EVIDENCE_PATH'
        base['rationale'] += ' + Z=ALT_EVIDENCE'
    return base


ARM_DECIDERS = {
    'Static-Parallel': decide_static,
    'Simple-Dynamic': decide_simple_dyn,
    'R-only': decide_r_only,
    'pi-only': decide_pi_only,
    'Joint(R,pi)': decide_joint_r_pi,
    'Joint(Z,R,pi)': decide_joint_z_r_pi,
}


# ===== SHARED PARALLEL EXECUTION KERNEL =====

def execute_dag(state, arm_name, model_adapter, max_iterations=20):
    trace = {'arm': arm_name, 'decisions': [], 'node_records': [],
             'cache_hits': 0, 'makespan': 0.0, 'total_wait': 0.0, 'final_status': 'UNKNOWN'}
    decider = ARM_DECIDERS[arm_name]

    for iteration in range(max_iterations):
        decision = decider(state)
        trace['decisions'].append({
            'iteration': iteration, 'action': decision['action'],
            'z_op': decision['z_op'], 'recovery_set': sorted(decision['recovery_set']),
            'rationale': decision['rationale'], 'assignments': decision['assignments']})

        if decision['action'] == 'terminate' or not decision['assignments']:
            break

        for nid, model in decision['assignments']:
            node = state.nodes.get(nid)
            if node is None: continue
            if node.status == 'done':
                trace['cache_hits'] += 1
                state.cache_hits += 1
                continue

            wait = state.resource_slots.acquire(model, state.virtual_clock)
            state.total_wait += wait
            state.virtual_clock += wait

            node.status = 'running'
            node.attempts += 1
            result = model_adapter.call(nid, node.kind, model,
                anomaly_node=state.anomaly_node if (nid == state.anomaly_node and node.attempts == 1) else None,
                anomaly_type=state.anomaly_type if (nid == state.anomaly_node and node.attempts == 1) else None,
                attempt=node.attempts)

            node.output = result.get('output')
            node.usage = result.get('usage', {'in': 0, 'out': 0})
            node.latency_s = result.get('latency_s', 0)
            state.virtual_clock += node.latency_s
            state.budget_remaining -= (node.usage['in'] + node.usage['out'])

            if result['success']:
                node.status = 'done'
                node.failure_type = None
            else:
                node.status = 'failed'
                node.failure_type = result.get('failure_type', FailureType.CONTRACT)

            state.resource_slots.release(model)
            trace['node_records'].append({
                'node_id': nid, 'model': model, 'status': node.status,
                'usage': node.usage, 'latency_s': node.latency_s,
                'wait_s': wait, 'attempt': node.attempts,
                'failure_type': node.failure_type.value if node.failure_type else None})

        all_done = all(n.status == 'done' for n in state.nodes.values())
        any_pending = any(n.status == 'pending' for n in state.nodes.values())
        any_failed = any(n.status == 'failed' for n in state.nodes.values())

        if all_done:
            trace['final_status'] = 'COMPLETE'; break
        elif not any_pending and any_failed:
            if not any(n.status == 'failed' and n.attempts < 2 for n in state.nodes.values()):
                trace['final_status'] = 'INCOMPLETE'; break
        elif state.budget_remaining <= 0:
            trace['final_status'] = 'BUDGET_EXHAUSTED'; break

    trace['makespan'] = state.virtual_clock
    trace['total_wait'] = state.total_wait
    trace['cache_hits'] = state.cache_hits
    if trace['final_status'] == 'UNKNOWN':
        trace['final_status'] = 'MAX_ITERATIONS'
    return trace
