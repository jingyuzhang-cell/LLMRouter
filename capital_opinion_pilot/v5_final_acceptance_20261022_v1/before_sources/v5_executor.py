"""Injected execution of a selected V5/RL action; no transport or model client.

Callbacks must return explicit contract and usage observations. Unknown usage
halts execution; it is not converted to zero. All attempted execution records
are separate from predictions. No retry, no fallback to V4. Deterministic tools
use the same callback with model=None, and refresh input-version fingerprints.
"""
from copy import deepcopy
import time
from scheduler_common import finite_nonnegative
from scheduler_common import topological, descendants
from cache_lineage import fingerprint
import joint_scheduler_v5
import rule_scheduler_rl


class V5RecoveryExecutor:
    def __init__(self, state, outputs, call, strategy='V5'):
        if strategy not in ('V5', 'RL'):
            raise ValueError('unknown strategy')
        self.state = dict(state)
        self.state["allow_proxy_objective"] = False  # production never optimizes a historical proxy
        self.state.setdefault("resource_limit", 1)  # this injected executor is serial
        self.outputs = deepcopy(outputs)
        missing_cache = set(self.state.get('cache_model', {})) - set(self.outputs)
        self.state['missing_outputs'] = sorted(set(self.state.get('missing_outputs', ())) | missing_cache)
        self.call = call
        self.strategy = strategy

    def run(self):
        chooser = joint_scheduler_v5.choose if self.strategy == 'V5' else rule_scheduler_rl.choose
        started = time.monotonic()
        best, audit = chooser(self.state)
        planning_s = time.monotonic()-started
        self.state['deadline_remaining_s'] = self.state.get('deadline_remaining_s', float('inf')) - planning_s
        if best is None:
            return {'status': 'REFUSED', 'selected': None, 'candidates': audit,
                    'outputs': self.outputs, 'actual': []}
        actual = []
        usage_unknown = False
        post_planning = joint_scheduler_v5.evaluate_candidate(best, self.state)
        if not post_planning['feasible']:
            return {'status':'REFUSED_AFTER_PLANNING','selected':best,'candidates':audit,
                    'outputs':self.outputs,'actual':[], 'actual_tokens':0,
                    'actual_execution_s':0,'actual_cash':{},'actual_planning_s':planning_s,
                    'post_planning_rejections':post_planning['rejection_reasons']}
        if best['Z'] == 'VERIFY':
            tokens, wall, cash = 0, 0, {}
            status = 'VERIFIED_ANNOTATION'
            for target in best['annotations']:
                node = 'verify_' + target
                model = best['pi'][node]
                cost, latency = self.state['cost_lat'][(node, model)][:2]
                if cost > self.state.get('token_budget_remaining', float('inf')) or latency > self.state['deadline_remaining_s']:
                    status = 'STOPPED'
                    break
                try:
                    result = self.call(node, model, {'target_output': self.outputs.get(target)})
                except Exception as exc:
                    actual.append({'node':node,'error_type':type(exc).__name__})
                    status = 'FAILED'
                    usage_unknown = True
                    break
                actual.append({'node': node, 'result': result})
                valid_usage = isinstance(result, dict) and _usage_valid(result)
                if valid_usage:
                    tokens += result['tokens'];wall += result['wall_s'];cash=result['cash_cost']
                else:
                    usage_unknown = True
                if not isinstance(result, dict) or result.get('contract_ok') is not True or 'output' not in result:
                    status = 'CONTRACT_FAILED'
                    break
                if not valid_usage:
                    status = 'USAGE_UNKNOWN'
                    break
                if tokens > self.state.get('token_budget_remaining',float('inf')) or wall > self.state['deadline_remaining_s'] or any(v>self.state.get('cash_budget',{}).get(k,float('inf')) for k,v in cash.items()):
                    status = 'POST_SETTLEMENT_OVERRUN'
            best['actual_execution'] = actual
            best = {**best, 'actual_execution': actual}
            return {'status': status, 'selected': best, 'candidates': audit,
                    'outputs': self.outputs, 'actual': actual, 'actual_tokens':None if usage_unknown else tokens,
                    'actual_execution_s':None if usage_unknown else wall,'actual_cash':None if usage_unknown else cash,
                    'known_settled_tokens':tokens,'known_settled_cash':cash,'usage_identified':not usage_unknown,
                    'actual_planning_s':planning_s}
        invalidated = set(best['R'])
        for n in best['R']:
            invalidated.update(descendants(n, self.state['children_map']))
        for n in invalidated:
            self.outputs.pop(n, None)
        order, parents = topological(self.state['children_map'], self.state['model_nodes'])
        required = set(best['R']) | set(self.state.get('pending_assignment', {}))
        tools = invalidated - set(self.state['model_nodes'])
        status = 'COMPLETE'
        tokens, wall, cash = 0, 0, {}
        for n in order:
            if n not in required | tools:
                continue
            if not parents[n] <= set(self.outputs):
                actual.append({'node': n, 'status': 'BLOCKED_DEPENDENCY'})
                status = 'INCOMPLETE'
                continue
            model = best['pi'].get(n, self.state.get('pending_assignment', {}).get(n))
            # Serial injected runner: serialize predictions at dispatch. Its actual
            # wall is supplied by the callback, distinct from DAG parallel prediction.
            if model is not None:
                cost, lat = self.state['cost_lat'][(n, model)][:2]
                if tokens + cost > self.state.get('token_budget_remaining', float('inf')) or wall + lat > self.state.get('deadline_remaining_s', float('inf')):
                    actual.append({'node': n, 'status': 'STOP_CONSTRAINT'})
                    status = 'STOPPED'
                    break
                cost_cash = self.state.get('cash_cost', {}).get((n, model), {})
                if any(cash.get(cur, 0) + val > self.state.get('cash_budget', {}).get(cur, float('inf')) for cur, val in cost_cash.items()):
                    status = 'STOPPED'
                    actual.append({'node': n, 'status': 'STOP_CASH'})
                    break
            inputs = {p: self.outputs[p] for p in sorted(parents[n])}
            try:
                result = self.call(n, model, inputs)
            except Exception as exc:
                actual.append({'node': n, 'status': 'EXECUTION_FAILED', 'error_type': type(exc).__name__})
                status = 'FAILED'
                usage_unknown = True
                break
            actual.append({'node': n, 'model': model, 'inputs_fp': fingerprint(inputs), 'result': result})
            valid_usage = isinstance(result, dict) and _usage_valid(result)
            if valid_usage:
                tokens += result['tokens']; wall += result['wall_s']
                for cur, val in result['cash_cost'].items():
                    cash[cur] = cash.get(cur, 0) + val
            else:
                usage_unknown = True
            if not isinstance(result, dict) or result.get('contract_ok') is not True or 'output' not in result:
                status = 'CONTRACT_FAILED'
                break
            if not valid_usage:
                status = 'USAGE_UNKNOWN'
                break
            if tokens > self.state.get('token_budget_remaining', float('inf')) or wall > self.state.get('deadline_remaining_s', float('inf')) or any(val > self.state.get('cash_budget', {}).get(cur, float('inf')) for cur, val in cash.items()):
                status = 'POST_SETTLEMENT_OVERRUN'
                break
            self.outputs[n] = result['output']
            if self.state.get('lineage') is not None:
                self.state['lineage'].register(n, model, result['output'], fingerprint(inputs), 'strict')
        best['actual_execution'] = actual
        best = {**best, 'actual_execution': actual}
        return {'status': status, 'selected': best, 'candidates': audit,
                'outputs': self.outputs, 'actual': actual,
                'actual_tokens': None if usage_unknown else tokens, 'actual_execution_s': None if usage_unknown else wall,
                'actual_cash':None if usage_unknown else cash, 'usage_identified':not usage_unknown,
                'known_settled_tokens':tokens, 'known_settled_cash':cash,
                'actual_planning_s': planning_s, 'actual_total_s':None if usage_unknown else wall+planning_s,
                'terminal_outputs_present':all(n in self.outputs for n in self.state.get('terminal_nodes', [n for n in self.state['model_nodes'] if not self.state['children_map'].get(n)]))}


def _usage_valid(result):
    return (finite_nonnegative(result.get('tokens')) and finite_nonnegative(result.get('wall_s'))
            and isinstance(result.get('cash_cost'), dict)
            and all(finite_nonnegative(v) for v in result['cash_cost'].values()))
