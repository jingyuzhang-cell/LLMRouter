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
                 choose_fn=None, pool_order=('glm53', 'glm53flash', 'deepseek', 'qwen')):
        from e4_controlled_experiment import node_prompt, parse_node, MODEL_NODES
        from joint_scheduler import descendants as _desc
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
        return strict_ok, compat_ok, value

    def _run_node(self, node):
        alias = self.pi.get(node, 'glm53')
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
        import joint_scheduler as JS
        pre = {'fault': (fault_node, failed_alias), 'at_s': round(self.elapsed(), 2),
               'remaining_s': round(self.deadline - self.elapsed(), 2),
               'completed': sorted(self.done), 'pi': dict(self.pi)}
        spent = sum(l['in'] + l['out'] for l in self.node_log)
        if self.policy == 's6':
            t0 = time.monotonic()
            action, audit = JS.choose(fault_node, self.model_nodes + ['m'], self.children,
                                      self.pool, self.stats, spent, 40000,
                                      self.elapsed(), self.deadline, q_min=0.05,
                                      blocked=self.blocked | {(fault_node, failed_alias)})
            self.decision_latencies.append({'node': fault_node,
                                            'decision_s': round(time.monotonic() - t0, 4)})
            Z, R, pi = action
            self.decisions.append({'policy': 's6', 'fault': (fault_node, failed_alias),
                                   'Z': Z, 'R': sorted(n for n in R if n in self.model_nodes),
                                   'pi_changes': {k: pi[k] for k in sorted(pi)
                                                  if k in self.model_nodes and pi[k] != self.pi.get(k)},
                                   'n_feasible': sum(1 for a in audit if a['feasible'])})
            if Z == 'NONE':
                self.decisions[-1]['why'] = 'no_feasible_action(deadline/budget/blocked)'
                return
            self.pi.update({k: v for k, v in pi.items() if k in self.model_nodes})
        else:  # s5cap
            R = ({fault_node} | JS.descendants(fault_node, self.children)) & set(self.model_nodes)
            changes = {}
            for n in sorted(R):
                cands = [m for m in self.pool if (n, m) not in self.blocked]
                q = lambda m: self.stats.get((n, m), (0, 0, 0.0))[2]
                best = max(cands, key=lambda m: (q(m), -self.pool.index(m)))
                if best != self.pi.get(n):
                    changes[n] = best
            self.pi.update(changes)
            self.decisions.append({'policy': 's5cap', 'fault': (fault_node, failed_alias),
                                   'Z': 'LOCAL_fixed', 'R': sorted(R), 'pi_changes': changes})
        alias2 = self.pi.get(fault_node, 'glm53')
        try:
            strict_ok, compat_ok, value = self._attempt(fault_node, alias2, 'recovery')
            if compat_ok:
                self.outputs[fault_node] = value
                self.done.add(fault_node)
        except DeadlineExceeded:
            self.skips.append({'node': fault_node, 'model': alias2, 'at': 'recovery',
                               'reason': 'deadline_gate_recovery'})
        except Exception:
            pass

    def run(self):
        failures = []
        for layer in [['t1', 't2'], ['m'], ['t3', 't4'], ['t5'], ['t6']]:
            if self.stopped_reason:
                break
            if layer == ['m']:
                f1, f2 = self.outputs.get('t1') or [], self.outputs.get('t2') or []
                if f1 or f2:
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
