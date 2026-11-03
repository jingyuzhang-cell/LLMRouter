"""Joint dynamic scheduler library: a=(Z, R, pi) two-stage decision (SPEC v1.0).

Library only — integrated into execution by joint_executor.py. Decision inputs:
DAG state, fault signal, budget/deadline remaining, and a FROZEN node capability
table (model -> per-node Q/C/L stats, from RQ1 / history). Gold-blind by design:
no gold paths are accessible here.
"""
import itertools

MODES = ('NONE', 'LOCAL', 'FULL')


def descendants(node, desc_map):
    out, frontier = set(), [node]
    while frontier:
        u = frontier.pop()
        for v in desc_map.get(u, []):
            if v not in out:
                out.add(v)
                frontier.append(v)
    return out


def candidate_actions(fault_node, all_nodes, desc_map, models):
    """R is determined by Z (closure); pi enumerated over R. Cache legality:
    completed unaffected nodes are never in R (enforced by executor passing
    only pending/affected scope)."""
    acts = [('NONE', frozenset(), {})]
    for Z in ('LOCAL', 'FULL'):
        R = ({fault_node} | descendants(fault_node, desc_map)) if Z == 'LOCAL' else set(all_nodes)
        R = frozenset(R)
        keys = sorted(R)
        for combo in itertools.product(models, repeat=len(keys)):
            acts.append((Z, R, dict(zip(keys, combo))))
    return acts


def predict(action, stats):
    Z, R, pi = action
    cost = sum(stats.get((n, pi.get(n, 'glm53')), (2000, 6.0, 0.5))[0] for n in R)
    lat = sum(stats.get((n, pi.get(n, 'glm53')), (2000, 6.0, 0.5))[1] for n in R)
    q = min((stats.get((n, pi.get(n, 'glm53')), (2000, 6.0, 0.5))[2] for n in R), default=1.0) if R else 0.0
    return {'cost': cost, 'lat_p90': lat, 'q_lower': q}


def choose(fault_node, all_nodes, desc_map, models, stats, spent, budget, now, deadline,
           q_min=0.5, w_q=1.0, w_c=0.00002, w_l=0.01, blocked=frozenset()):
    """Two-stage: filter by hard constraints (budget/deadline/quality-lower-bound),
    then maximise weighted objective. Returns (action, audit_log)."""
    audit = []
    feasible = []
    for a in candidate_actions(fault_node, all_nodes, desc_map, models):
        if any(a[2].get(n) == m for (n, m) in blocked):
            audit.append({'Z': a[0], 'R': sorted(a[1]), 'pi': dict(a[2]), 'cost': -1, 'lat_p90': -1,
                          'q_lower': -1, 'feasible': False, 'why': 'blocked:model_unavailable'})
            continue
        Z, R, pi = a
        p = predict(a, stats)
        why = 'ok'
        if spent + p['cost'] > budget:
            why = f"budget:{spent}+{p['cost']}>{budget}"
        elif now + p['lat_p90'] > deadline:
            why = f"deadline:{now:.0f}+{p['lat_p90']:.0f}>{deadline:.0f}"
        elif R and p['q_lower'] < q_min:
            why = f"quality_lower_bound:{p['q_lower']:.2f}<{q_min}"
        audit.append({'Z': Z, 'R': sorted(R), 'pi': {k: pi[k] for k in sorted(pi)},
                      **p, 'feasible': why == 'ok', 'why': why})
        if why == 'ok':
            score = (w_q * (p['q_lower'] if R else -1) - w_c * p['cost'] - w_l * p['lat_p90'])
            feasible.append((score, a))
    if not feasible:
        return ('NONE', frozenset(), {}), audit
    feasible.sort(key=lambda x: -x[0])
    return feasible[0][1], audit
