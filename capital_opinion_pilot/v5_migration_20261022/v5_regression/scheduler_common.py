"""Shared, model-free graph and capability operations. No scheduler fallback."""
import itertools
import math


def descendants(node, children):
    result, todo = set(), [node]
    while todo:
        for child in children.get(todo.pop(), ()):
            if child not in result:
                result.add(child)
                todo.append(child)
    result.discard(node)
    return result


def closure(roots, children, model_nodes):
    # Walk ALL vertices, including deterministic joins, before filtering.
    return (set(roots) | set().union(*(descendants(n, children) for n in roots))) & set(model_nodes)


def topological(children, nodes):
    nodes = set(nodes) | set(children) | {v for vs in children.values() for v in vs}
    parents = {n: set() for n in nodes}
    for u, vs in children.items():
        for v in vs:
            parents[v].add(u)
    out, remaining = [], set(nodes)
    while remaining:
        ready = sorted(n for n in remaining if not (parents[n] & remaining))
        if not ready:
            raise ValueError('cyclic DAG')
        out.extend(ready)
        remaining.difference_update(ready)
    return out, parents


def assignments(scope, state):
    keys = sorted(scope)
    pools = state.get('pools', {})
    blocked = set(state.get('blocked', ()))
    availability = state.get('availability', {})
    contracts = state.get('contract_compatible', {})
    choices = [[m for m in sorted(set(pools.get(n, pools.get('*', ()))))
                if (n, m) not in blocked and availability.get(m, True)
                and contracts.get((n, m), True)] for n in keys]
    limit = state.get('max_assignments', 100000)
    count = math.prod(map(len, choices))
    if count > limit:
        raise ValueError(f'assignment_search_limit:{count}>{limit}')
    return [dict(zip(keys, models)) for models in itertools.product(*choices)]


def finite_nonnegative(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def estimates(scope, pi, state):
    """Conservative supplied latency + full DAG precedence, incl. zero-cost joins.

    Optional resource_limit=1 serializes work. Otherwise assumes unlimited model
    concurrency; this is a prediction, not measured execution wall time.
    Missing cost/latency/currency cells never default to zero.
    """
    order, parents = topological(state['children_map'], state['model_nodes'])
    duration, tokens, cash = {}, 0, {}
    for n in sorted(scope):
        cell = state.get('cost_lat', {}).get((n, pi[n]))
        if cell is None or len(cell) < 2 or not all(finite_nonnegative(v) for v in cell[:2]):
            raise ValueError(f'unidentified_cost_latency:{n}:{pi[n]}')
        tokens += cell[0]
        duration[n] = cell[1]
        cost = state.get('cash_cost', {}).get((n, pi[n]))
        if cost is None and state.get('cash_budget'):
            raise ValueError(f'unidentified_cash_cost:{n}:{pi[n]}')
        for currency, amount in (cost or {}).items():
            if not finite_nonnegative(amount):
                raise ValueError('invalid_cash_cost')
            cash[currency] = cash.get(currency, 0) + amount
    for n, seconds in state.get('deterministic_latency', {}).items():
        if not finite_nonnegative(seconds):
            raise ValueError('invalid_deterministic_latency')
        if any(n in descendants(u, state['children_map']) for u in scope):
            duration[n] = seconds
    finish = {}
    for n in order:
        finish[n] = max((finish[p] for p in parents[n]), default=0) + duration.get(n, 0)
    path = max(finish.values(), default=0)
    if state.get('resource_limit') == 1:
        path = sum(duration.values())
    elif state.get('resource_limit') not in (None, 1):
        raise ValueError('unsupported_resource_limit')
    overhead = state.get('planning_overhead_s', 0) + state.get('switch_overhead_s', 0)
    if not finite_nonnegative(overhead):
        raise ValueError('invalid_overhead')
    return tokens, path + overhead, cash
