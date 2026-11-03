"""Deadline-controlled parallel executor v2 (protocol fix, 2026-10-14, zero-pay).

Problem (F7 round): R3/R4 ran 98.4s/101.7s against a 90s deadline. The scheduler
only DISCOVERED infeasibility at the 4th fault (Z=NONE at t6, ~86s in) after
already spending 3 extra recovery calls. Deadline enforcement was observational,
not behavioral.

Fix — three enforcement points, all BEFORE money is spent:
  E1 pre-call gate    : no model call may START at or after the deadline.
  E2 preflight        : before each node call / recovery re-execution, predicted
                        latency (capability stats, or last observed for this
                        (node, model) in this run) must fit the remaining time;
                        otherwise the node is skipped and the skip is recorded
                        with its reason (deadline_preflight).
  E3 hard stop        : at deadline, the executor stops issuing anything and
                        finalises the record with deadline_violation_s and the
                        timeout cause chain.

Records per run: completion wall, deadline_met, violation margin, every
skip/refusal with reason, scheduling decision latency (time spent in
JS.choose), and the executed-node log. Zero-call testable via FakeMeter.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor


# Measured P90 latency table (s) from ALL real ledgers (e4/f7min/f7v2,
# 2026-10-14 calibration). 9 of 13 cells had P90/mean > 1.30, so the old
# mean*1.30 margin systematically underestimated heavy tails. Preflight now
# takes max(last_observed*1.15, P90, stats_mean*1.6) — conservative by design:
# prefer refusing a marginal call over violating the deadline.
LAT_P90 = {('t1', 'deepseek'): 11.9, ('t1', 'glm53'): 27.7,
           ('t2', 'deepseek'): 12.8, ('t2', 'glm53'): 17.9,
           ('t3', 'deepseek'): 4.8, ('t3', 'glm53'): 12.6,
           ('t4', 'deepseek'): 8.5, ('t4', 'glm53'): 21.0,
           ('t5', 'deepseek'): 6.4, ('t5', 'glm53'): 17.6,
           ('t6', 'deepseek'): 5.4, ('t6', 'glm53'): 19.2}


class DeadlineExceeded(RuntimeError):
    pass


class DeadlineGuardedExecutor:
    """Drop-in replacement for the F7 executor with behavioural deadline control.

    Same node/layer structure and fault semantics as the F7 round (t1|t2, m,
    t3|t4, t5, t6; blocked (node, model) pairs are never called). `meter.call`
    must accept (run_id, node, alias, system, user) and return the raw dict;
    `node_prompt_fn(event, node, merged_json, outputs)` builds prompts; policies:
    'static' | 's5cap' | 's6' exactly as the F7 freeze.
    """

    def __init__(self, meter, event, run_id, pi0, blocked, policy, stats,
                 deadline_s=90.0, children=None, model_nodes=None,
                 node_prompt_fn=None, parse_fn=None, merge_fn=None,
                 choose_fn=None, pool_order=('glm53', 'glm53flash', 'deepseek', 'qwen'),
                 budget_tokens=40000, recovery_state=None):
        from pilot_node_contracts import node_prompt, parse_node, MODEL_NODES
        from scheduler_common import descendants as _desc
        from merge_facts import merge_facts
        self.meter, self.event, self.run_id = meter, event, run_id
        self.pi = dict(pi0)
        self.blocked = frozenset(blocked)
        self.policy = policy
        self.stats = stats
        self.deadline = deadline_s
        self.children = children or {'t1': ['m'], 't2': ['m'], 'm': ['t3', 't4'],
                                     't3': ['t5'], 't4': ['t5'], 't5': ['t6']}
        self.model_nodes = model_nodes or list(MODEL_NODES)
        self.node_prompt = node_prompt_fn or node_prompt
        self.parse = parse_fn or parse_node
        self.merge = merge_fn or merge_facts
        self.choose = choose_fn
        self.budget_tokens = budget_tokens
        self.recovery_state = recovery_state or {}
        self.pool = tuple(pool_order)
        self.outputs, self.done = {}, set()
        self.node_log, self.decisions, self.fault_records = [], [], []
        self.skips = []           # E2 refusals with reasons
        self.decision_latencies = []
        self.last_lat = {}        # (node, alias) -> last observed latency this run
        self.stopped_reason = None
        self.t0 = time.monotonic()

    def elapsed(self):
        return time.monotonic() - self.t0

    def _pred_lat(self, node, alias):
        cell = self.stats.get((node, alias))
        stats_est = (cell[1] if cell else 6.0) * 1.6
        p90 = LAT_P90.get((node, alias), 0.0)
        last = self.last_lat.get((node, alias), 0.0) * 1.15
        return max(stats_est, p90, last)

    def _gate(self, node, alias, what):
        """E1+E2. Returns True if the call may proceed."""
        rem = self.deadline - self.elapsed()
        if rem <= 0:
            self.skips.append({'node': node, 'model': alias, 'at': what,
                               'reason': 'deadline_reached', 'remaining_s': round(rem, 2)})
            return False
        cell = self.stats.get((node, alias))
        if cell is None or sum(l['in']+l['out'] for l in self.node_log) + cell[0] > self.budget_tokens:
            self.skips.append({'node': node, 'model': alias, 'reason': 'budget_or_unknown_cost'})
            return False
        pred = self._pred_lat(node, alias)
        if pred > rem:
            self.skips.append({'node': node, 'model': alias, 'at': what,
                               'reason': 'deadline_preflight', 'predicted_s': round(pred, 1),
                               'remaining_s': round(rem, 2)})
            return False
        return True

    def _attempt(self, node, alias, what):
        import json
        if (node, alias) in self.blocked:
            raise DeadlineExceeded(f'blocked:({node},{alias})')
        if not self._gate(node, alias, what):
            raise DeadlineExceeded('deadline_gate')
        merged_json = json.dumps(self.outputs.get('m', {}), ensure_ascii=False)
        system, user = self.node_prompt(self.event, node, merged_json, self.outputs)
        raw = self.meter.call(self.run_id, node, alias, system, user)
        self.last_lat[(node, alias)] = raw.get('lat', self.last_lat.get((node, alias), 5.0))
        strict_ok, compat_ok, value, note = None, None, None, None
        # layered contract via json_compat when the meter exposes raw text
        try:
            from json_compat import parse_layers, node_contract
            pl = parse_layers(raw['text'])
            strict_ok, compat_ok, value, note = node_contract(node, pl)
        except Exception:
            ok, value = self.parse(node, raw['text'])
            strict_ok = compat_ok = ok
        self.node_log.append({'node': node, 'model': alias,
                              'strict_ok': strict_ok, 'compat_ok': compat_ok,
                              'contract_note': note,
                              'in': raw.get('in', 0), 'out': raw.get('out', 0),
                              'lat': raw.get('lat', 0.0),
                              'truncated': raw.get('stop') in ('length', 'max_tokens')})
        return strict_ok, compat_ok and raw.get('stop') not in ('length', 'max_tokens'), value

    def _run_node(self, node):
        if node in self.done:
            return None
        parents = {p for p, vs in self.children.items() if node in vs}
        alias = self.pi.get(node, 'glm53')
        if not self._gate(node, alias, 'node_preflight'):
            return None
        if not parents <= self.done:
            self.skips.append({'node': node, 'reason': 'blocked_dependency'})
            return None
        try:
            strict_ok, compat_ok, value = self._attempt(node, alias, 'node')
            if compat_ok:  # compat layer counts as executable (recorded separately)
                self.outputs[node] = value
                self.done.add(node)
                return None
            return (node, alias, 'contract_fail')
        except DeadlineExceeded as e:
            s = str(e)
            if s.startswith('blocked:'):
                return (node, alias, s)
            return (node, alias, 'deadline_skip')
        except Exception as e:
            return (node, alias, f'transport_error:{type(e).__name__}')

    def _recover(self, fault_node, failed_alias):
        import joint_scheduler_v5 as V5
        from scheduler_common import descendants
        if self.policy == 's6':
            state = dict(self.recovery_state)
            state["allow_proxy_objective"] = False
            feedback=dict(state.get('feedback', {}))
            feedback['confirmed']=sorted(set(feedback.get('confirmed', ())) | {fault_node})
            state.update(children_map=self.children, model_nodes=set(self.model_nodes),
                         missing_outputs=[fault_node], feedback=feedback,
                         pools={'*': self.pool}, blocked=set(self.blocked),
                         cost_lat={(n,m):(v[0],self._pred_lat(n,m)) for (n,m),v in self.stats.items()},
                         token_budget_remaining=self.budget_tokens-sum(l['in']+l['out'] for l in self.node_log),
                         deadline_remaining_s=self.deadline-self.elapsed(),
                         cache_model={n:self.pi[n] for n in self.done if n in self.pi},
                         pending_assignment={n:self.pi[n] for n in self.model_nodes if n not in self.done and n != fault_node})
            # Only permanent configured unavailability is blocked. Contract failure
            # alone does not imply this model or its next instance is dead.
            t0=time.monotonic()
            best,audit=(self.choose or V5.choose)(state)
            self.decision_latencies.append({'node':fault_node,'decision_s':time.monotonic()-t0})
            self.decisions.append({'policy':'V5','fault':(fault_node,failed_alias),
                                   'selected':best,'candidates':audit})
            if best is None or best['Z'] in ('NONE','VERIFY'):
                self.decisions[-1]['why']='no_executable_recovery'
                return
            R=set(best['R']); self.pi.update(best['pi'])
        else:
            R=({fault_node}|descendants(fault_node,self.children)) & set(self.model_nodes)
            for n in sorted(R):
                options=[m for m in self.pool if (n,m) not in self.blocked and (n,m) in self.stats]
                if not options:
                    return
                self.pi[n]=min(options,key=lambda m:(-self.stats[(n,m)][2],self.pool.index(m)))
            self.decisions.append({'policy':'s5cap','Z':'LOCAL_fixed','R':sorted(R),'pi':dict(self.pi)})
        affected=R|set().union(*(descendants(n,self.children) for n in R))
        for n in affected:
            self.outputs.pop(n,None);self.done.discard(n)
        # Entire chosen recovery set is carried out, preserving join dependencies.
        for layer in [['t1','t2'],['m'],['t3','t4'],['t5'],['t6']]:
            for n in layer:
                if n=='m' and n in affected and {'t1','t2'} <= self.done:
                    self.outputs['m']=self.merge([self.outputs['t1'],self.outputs['t2']],['t1','t2'])
                    self.done.add('m')
                elif n in R:
                    failure=self._run_node(n)
                    if failure:
                        self.fault_records.append({'node':n,'model':self.pi[n],'reason':failure[2],'at_s':self.elapsed()})
                        return  # no automatic recursive retry

    def run(self):
        failures = []
        for layer in [['t1', 't2'], ['m'], ['t3', 't4'], ['t5'], ['t6']]:
            if self.stopped_reason:
                break
            if layer == ['m']:
                f1, f2 = self.outputs.get('t1') or [], self.outputs.get('t2') or []
                if {'t1','t2'} <= self.done:
                    self.outputs['m'] = self.merge([f1, f2], ['t1', 't2'])
                    self.done.add('m')
                continue
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(self._run_node, n) for n in layer]
                failures += [f.result() for f in futs if f.result() is not None]
            for tup in list(failures):
                node, alias, reason = tup
                if node in layer:
                    failures.remove(tup)
                    self.fault_records.append({'node': node, 'model': alias, 'reason': reason,
                                               'at_s': round(self.elapsed(), 2)})
                    if self.policy != 'static' and reason.startswith('blocked:'):
                        self._recover(node, alias)
                    elif self.policy != 'static' and reason == 'contract_fail':
                        self._recover(node, alias)
        wall = self.elapsed()
        violation = max(0.0, wall - self.deadline)
        return {'complete': all(n in self.outputs for n in self.model_nodes),
                'wall_s': round(wall, 2), 'deadline_met': wall <= self.deadline,
                'deadline_violation_s': round(violation, 2),
                'outputs': {k: self.outputs.get(k) for k in self.model_nodes},
                'node_log': self.node_log, 'decisions': self.decisions,
                'fault_records': self.fault_records, 'skips': self.skips,
                'decision_latencies': self.decision_latencies}
