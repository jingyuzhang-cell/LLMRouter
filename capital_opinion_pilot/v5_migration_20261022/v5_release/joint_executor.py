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
        if time.monotonic() - ex.t0 + lat > ex.deadline:
            ex.decisions.append({'action': {'Z': 'ABSTAIN', 'R': sorted(R), 'pi': pi},
                                 'why': f'deadline:{lat:.0f}>{ex.deadline:.0f}',
                                 'policy_type': 'fixed_guarded'})
            ex.deliberate_none = {'node': fault_node, 'none_type': 'fixed_policy_infeasible_deadline'}
            return None
        ex.pi.update(pi)
        for n in R:
            ex.outputs.pop(n, None)
            ex.done.discard(n)
        for layer in ex.order:
            for u in layer:
                parents = {p for p, vs in ex.desc.items() if u in vs}
                if u in R and parents <= ex.done and ex._call_allowed(u, ex.pi[u]):
                    ok, value = ex.call_fn(u, ex.pi[u])
                    if ok and value is not None:
                        ex.outputs[u] = value
                        ex.done.add(u)
        return ex.outputs.get(fault_node)



class RecoveringExecutor:
    def __init__(self, nodes, order, desc_map, meter, stats, planned_pi,
                 budget, deadline, call_fn, models=('glm53', 'glm53flash'), recovery_state=None):
        """nodes: id->subtask; order: topo layer list; desc_map: node->children;
        call_fn(node_id, alias) -> (ok, output); stats: (node,alias)->(cost,lat,q)."""
        self.nodes, self.order, self.desc = nodes, order, desc_map
        self.meter, self.stats, self.pi = meter, stats, dict(planned_pi)
        self.budget, self.deadline = budget, deadline
        self.call_fn, self.models = call_fn, models
        self.recovery_state = recovery_state or {}
        self.decisions = []
        self.calls_log = []
        self.prediction_errors = []
        self.deliberate_none = None

    def spent(self):
        return self.meter.actual_tokens

    def run(self, injector):
        self.outputs, self.done = {}, set()
        self.t0 = time.monotonic()
        self.failed_pairs = set()
        fault_hit = None
        for layer in self.order:
            for u in layer:
                if u in self.done:
                    continue  # recovery output is already committed, never call twice
                parents = {p for p, vs in self.desc.items() if u in vs}
                if not parents <= self.done:
                    self.calls_log.append({'node': u, 'status': 'blocked_dependency'})
                    continue
                alias = self.pi.get(u, 'glm53')
                if not self._call_allowed(u, alias):
                    continue
                tripped, exc = injector.trip(u, alias)
                if tripped and exc:
                    self.failed_pairs.add((u, alias))
                    ok, out = False, None
                else:
                    ok, out = self.call_fn(u, alias)
                    if tripped and injector.mode in ('contract_fail', 'timeout'):
                        ok, out = False, None
                if not ok:
                    fault_hit = (u, alias)
                    self._record_decision(u, injector.mode if tripped else 'contract_fail_observed', 'runtime')
                    out = self._recover(u)
                    ok = out is not None
                if ok and out is not None:
                    self.outputs[u] = out
                    self.done.add(u)
        return {'complete': all(n in self.outputs for n in self.nodes),
                'deliberate_none': self.deliberate_none,
                'prediction_errors': self.prediction_errors, 'outputs': self.outputs,
                'fault': fault_hit, 'decisions': self.decisions, 'calls_log': self.calls_log,
                'wall_s': round(time.monotonic() - self.t0, 6),
                'tokens': self.spent(),
                'provenance': 'REAL' if not getattr(self.meter, 'fake', False) else 'TEST'}

    def _call_allowed(self, node, alias):
        cell = self.stats.get((node, alias))
        reason = None
        if cell is None:
            reason = 'unidentified_cost_latency'
        elif self.spent() + cell[0] > self.budget:
            reason = 'budget'
        elif time.monotonic() - self.t0 + cell[1] > self.deadline:
            reason = 'deadline'
        if reason:
            self.calls_log.append({'node': node, 'model': alias, 'status': 'refused', 'reason': reason})
            self.deliberate_none = {'node': node, 'none_type': reason}
        return reason is None

    def _record_decision(self, node, fault_kind, how):
        self.decisions.append({'node': node, 'fault_kind': fault_kind, 'detected_via': how})

    def _recover(self, fault_node):
        import joint_scheduler_v5 as V5
        state=dict(self.recovery_state)
        state["allow_proxy_objective"] = False
        feedback=dict(state.get('feedback', {}))
        feedback['confirmed']=sorted(set(feedback.get('confirmed', ())) | {fault_node})
        state.update(children_map=self.desc, model_nodes=set(self.nodes),
                     missing_outputs=[fault_node], feedback=feedback,
                     pools=state.get('pools', {'*':list(self.models)}),
                     blocked=set(state.get('blocked', ())) | self.failed_pairs,
                     cache_model={n:self.pi[n] for n in self.done},
                     pending_assignment={n:self.pi[n] for n in self.nodes if n not in self.done and n != fault_node},
                     cost_lat=state.get('cost_lat', self.stats),
                     token_budget_remaining=self.budget-self.spent(),
                     deadline_remaining_s=self.deadline-(time.monotonic()-self.t0))
        best, audit=V5.choose(state)
        for c in audit:
            c['why']=','.join(c['rejection_reasons']) or 'ok'
        action=(best['Z'],set(best['R']),best['pi']) if best else ('NONE',set(),{})
        self.decisions.append({'action': {'Z': action[0], 'R': sorted(action[1]), 'pi': action[2]},
                               'audit': audit, 'n_candidates': len(audit)})
        Z, R, pi = action
        if Z == 'NONE':
            self.deliberate_none = {'node': fault_node, 'none_type': 'no_feasible_recovery',
                                   'rejected': [a['why'] for a in audit if not a['feasible']]}
            return None
        self.pi.update(pi)
        for n in R:
            self.outputs.pop(n, None)
            self.done.discard(n)
        for layer in self.order:
            for u in layer:
                if u not in R:
                    continue
                parents = {p for p, vs in self.desc.items() if u in vs}
                if not parents <= self.done or not self._call_allowed(u, self.pi[u]):
                    continue
                before = len(self.meter.calls)
                ok, value = self.call_fn(u, self.pi[u])
                rec = self.meter.calls[-1] if len(self.meter.calls) > before else None
                if rec:
                    pred = self.stats[(u, self.pi[u])]
                    self.prediction_errors.append({'node': u, 'model': rec['model_alias'],
                        'pred_cost': pred[0],
                        'actual_cost': rec['usage']['input_tokens'] + rec['usage']['output_tokens'],
                        'pred_lat_p90': pred[1], 'actual_lat': rec['latency_s']})
                if ok and value is not None:
                    self.outputs[u] = value
                    self.done.add(u)
                elif u == fault_node:
                    break
        return self.outputs.get(fault_node)
