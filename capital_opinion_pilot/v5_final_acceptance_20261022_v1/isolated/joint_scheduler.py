"""Production compatibility entry for V5. NEVER imports the retired algorithm.

Historical stats' node Q is not a task-quality calibration. Legacy-signature
calls therefore select on known cost/latency with quality UNIDENTIFIED. The
old q_min argument is recorded as unsupported, not applied to invented Q.
New callers should supply full runtime state to joint_scheduler_v5.choose.
Historical reproduction lives under legacy/scheduler_v4_20261022/src/.
"""
from scheduler_common import descendants
import joint_scheduler_v5 as v5

MODES = ('NONE', 'LOCAL', 'EXPAND', 'FULL', 'VERIFY')


def choose(fault_node, all_nodes, desc_map, models, stats, spent, budget, now, deadline,
           q_min=0.5, w_q=1.0, w_c=0.00002, w_l=0.01, blocked=frozenset()):
    nodes = {n for n in all_nodes if any((n, m) in stats for m in models)}
    state = {'fault_node': fault_node, 'children_map': desc_map, 'model_nodes': nodes,
             'missing_outputs': [fault_node], 'feedback': {'confirmed': [fault_node]},
             'pools': {'*': list(models)}, 'blocked': set(blocked),
             'cost_lat': stats, 'token_budget_remaining': max(0, budget-spent),
             'deadline_remaining_s': max(0, deadline-now), 'w_c': w_c, 'w_l': w_l}
    best, scored = v5.choose(state)
    audit = [{**c, 'cost': c['tokens'], 'lat_p90': c['path_s'], 'q_lower': None,
              'why': ','.join(c['rejection_reasons']) or 'ok',
              'legacy_node_q_min_not_task_calibrated': q_min} for c in scored]
    return ((best['Z'], frozenset(best['R']), best['pi']) if best else ('NONE', frozenset(), {})), audit


def candidate_actions(*args, **kwargs):
    raise RuntimeError('retired enumeration API; use joint_scheduler_v5.enumerate_actions(state)')


def predict(*args, **kwargs):
    raise RuntimeError('retired node-minimum predictor; use V5 task evaluator')
