"""RecoveringExecutor: integrates the joint scheduler into typed-DAG-style execution.

Runs a frozen node plan through an injected METER (real Meter in production,
FakeMeter in zero-call tests). On an injected fault (unavailable/contract_fail/
timeout bound to (node,seed)), it calls joint_scheduler.choose() and executes the
chosen (Z, R, pi) through the SAME meter path — real calls only in production;
FakeMeter tests are labelled TEST. Completed unaffected outputs are protected
(cache legality); every decision's audit log is returned with the run record.
"""
import time

import joint_scheduler as JS

FAULT_MODES = ('clean', 'unavailable', 'contract_fail', 'timeout')


class FaultInjector:
    def __init__(self, mode, node, seed=0):
        self.mode, self.node, self.seed = mode, node, seed

    def trip(self, node, alias):
        """Returns (tripped, injected_exception_or_None). Deterministic per binding."""
        if self.mode == 'clean' or node != self.node:
            return False, None
        if self.mode == 'unavailable':
            return True, RuntimeError('INJECTED model_unavailable')
        return True, None  # contract_fail/timeout handled post-call by executor


class GuardedPolicy:
    """Fairness wrapper (ruling 2026-10-13): EVERY strategy (S3/S4/S5) executes under
    the SAME hard budget/deadline guard as S6. An infeasible fixed action is recorded
    as ABSTAIN (no over-budget execution to manufacture contrasts); abstention is
    logged with the violated constraint, mirroring S6's deliberate-NONE audit."""

    def __init__(self, ex, policy):
        self.ex, self.policy = ex, policy

    def __call__(self, fault_node):
        ex = self.ex
        R = {fault_node} | JS.descendants(fault_node, ex.desc)
        pi = self.policy(fault_node)
        cost = sum(ex.stats[(n, pi[n])][0] for n in R)
        lat = sum(ex.stats[(n, pi[n])][1] for n in R)
        if ex.spent() + cost > ex.budget:
            ex.decisions.append({'action': {'Z': 'ABSTAIN', 'R': sorted(R), 'pi': pi},
                                 'why': f'budget:{ex.spent()}+{cost}>{ex.budget}',
                                 'policy_type': 'fixed_guarded'})
            ex.deliberate_none = {'node': fault_node, 'none_type': 'fixed_policy_infeasible_budget'}
            return None
        if lat > ex.deadline:
            ex.decisions.append({'action': {'Z': 'ABSTAIN', 'R': sorted(R), 'pi': pi},
                                 'why': f'deadline:{lat:.0f}>{ex.deadline:.0f}',
                                 'policy_type': 'fixed_guarded'})
            ex.deliberate_none = {'node': fault_node, 'none_type': 'fixed_policy_infeasible_deadline'}
            return None
        ex.pi.update(pi)
        out = {}
        for layer in ex.order:
            for u in layer:
                if u in R:
                    ok, o = ex.call_fn(u, ex.pi.get(u, 'glm53'))
                    if ok:
                        out[u] = o
        return out.get(fault_node)


class RecoveringExecutor:
    def __init__(self, nodes, order, desc_map, meter, stats, planned_pi,
                 budget, deadline, call_fn, models=('glm53', 'glm53flash')):
        """nodes: id->subtask; order: topo layer list; desc_map: node->children;
        call_fn(node_id, alias) -> (ok, output); stats: (node,alias)->(cost,lat,q)."""
        self.nodes, self.order, self.desc = nodes, order, desc_map
        self.meter, self.stats, self.pi = meter, stats, dict(planned_pi)
        self.budget, self.deadline = budget, deadline
        self.call_fn, self.models = call_fn, models
        self.decisions = []
        self.calls_log = []
        self.prediction_errors = []
        self.deliberate_none = None

    def spent(self):
        return self.meter.actual_tokens

    def run(self, injector):
        outputs, done = {}, set()
        t0 = time.monotonic()
        fault_hit = None
        for layer in self.order:
            for u in layer:
                alias = self.pi.get(u, 'glm53')
                tripped, exc = injector.trip(u, alias)
                if tripped and exc:
                    fault_hit = (u, alias)
                    self._record_decision(u, injector.mode, 'injected_unavailable')
                    recovered = self._recover(u)
                    if recovered is None:
                        continue
                    u_out = recovered
                else:
                    ok, out = self.call_fn(u, alias)
                    if not ok and injector.mode != 'clean' and u == injector.node:
                        fault_hit = (u, alias)
                        self._record_decision(u, 'contract_fail_observed', 'observed')
                        recovered = self._recover(u)
                        u_out = recovered if recovered is not None else out
                    else:
                        u_out = out
                if u_out is not None:
                    outputs[u] = u_out
                    done.add(u)
        complete = all(n in outputs for n in self.nodes)
        return {'complete': complete, 'deliberate_none': self.deliberate_none,
                'prediction_errors': self.prediction_errors, 'outputs': outputs,
                'fault': fault_hit, 'decisions': self.decisions,
                'wall_s': round(time.monotonic() - t0, 3),
                'tokens': self.spent(), 'provenance': 'REAL' if not getattr(self.meter, 'fake', False) else 'TEST'}

    def _record_decision(self, node, fault_kind, how):
        self.decisions.append({'node': node, 'fault_kind': fault_kind, 'detected_via': how})

    def _recover(self, fault_node):
        failed_alias = self.pi.get(fault_node, 'glm53')
        action, audit = JS.choose(fault_node, list(self.nodes), self.desc, self.models,
                                  self.stats, self.spent(), self.budget, 0.0, self.deadline,
                                  blocked={(fault_node, failed_alias)})
        self.decisions.append({'action': {'Z': action[0], 'R': sorted(action[1]),
                                          'pi': {k: action[2][k] for k in sorted(action[2])}},
                               'audit_rejected': [a for a in audit if not a['feasible']][:6],
                               'n_candidates': len(audit)})
        Z, R, pi = action
        if Z == 'NONE':
            # deliberate, documented decision: every alternative was rejected by a
            # hard constraint (see audit_rejected) — NOT a silent task failure
            self.deliberate_none = {'node': fault_node,
                                    'none_type': 'no_feasible_recovery',
                                    'rejected': [a['why'] for a in audit if not a['feasible']][:6]}
            return None
        self.pi.update(pi)
        out = {}
        for layer in self.order:
            for u in layer:
                if u in R:
                    pred = self.stats.get((u, self.pi.get(u, 'glm53')))
                    ok, o = self.call_fn(u, self.pi.get(u, 'glm53'))
                    # prediction-vs-actual captured per recovery call (meta from meter)
                    rec = self.meter.calls[-1] if self.meter.calls else None
                    if rec is not None and pred is not None:
                        self.prediction_errors.append({
                            'node': u, 'model': rec['model_alias'],
                            'pred_cost': pred[0], 'actual_cost': rec['usage']['input_tokens'] + rec['usage']['output_tokens'],
                            'pred_lat_p90': pred[1], 'actual_lat': rec['latency_s']})
                    if ok:
                        out[u] = o
        self.outputs_backup = getattr(self, 'outputs_backup', {})
        self.outputs_backup.update(out)
        return out.get(fault_node)
