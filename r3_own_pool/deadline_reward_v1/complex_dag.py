"""Complex DAG experiment infrastructure (zero calls).

Structures: chain / diamond / wide-parallel / multi-path / deep- DAGs
at 4/8/12/16 nodes. Joint action enumeration with Oracle for
identifying when dynamic scheduling has real optimization
opportunities vs when simple rules suffice.

Run: python3 -m deadline_reward_v1.complex_dag --audit
"""
from __future__ import annotations

import itertools
import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent

# ---- DAG structure generators ----------------------------------------
STRUCTURES = {
    'chain': lambda n: {f'n{i}': [f'n{i+1}'] for i in range(n - 1)},
    'diamond': lambda n: _diamond(n),
    'wide': lambda n: _wide(n),
    'multipath': lambda n: _multipath(n),
    'deep': lambda n: _deep(n),
}


def _diamond(n):
    """Generalized diamond: source → k branches → sink."""
    if n <= 2:
        return {'n0': ['n1']}
    mid = n - 2
    k = max(2, min(mid, 4))
    edges = {'n0': [f'b{i}' for i in range(k)]}
    for i in range(k):
        edges[f'b{i}'] = ['sink']
    # distribute remaining nodes among branches
    remaining = mid - k
    for i in range(remaining):
        bi = i % k
        new = f'x{i}'
        prev = f'b{bi}' if i < k else f'x{i - k}'
        if prev in edges:
            edges[prev] = [new]
        edges[new] = ['sink'] if i < k else ['sink']
    edges['sink'] = []
    return edges


def _wide(n):
    """Wide parallel: source → n-2 independent nodes → sink."""
    m = n - 2
    edges = {'src': [f'p{i}' for i in range(m)]}
    for i in range(m):
        edges[f'p{i}'] = ['snk']
    edges['snk'] = []
    return edges


def _multipath(n):
    """Multiple paths of different lengths from source to sink."""
    paths = max(2, n // 4)
    edges = {'src': []}
    node_id = 0
    path_ends = []
    for p in range(paths):
        length = max(1, (n - 2) // paths)
        prev = 'src'
        for j in range(length):
            node_id += 1
            nid = f'm{node_id}'
            edges[prev] = edges.get(prev, []) + [nid]
            prev = nid
        path_ends.append(prev)
    edges['snk'] = []
    for pe in path_ends:
        edges[pe] = edges.get(pe, []) + ['snk']
    return edges


def _deep(n):
    """Deep chain with occasional parallel pairs."""
    edges = {}
    for i in range(n - 1):
        if i > 0 and i % 3 == 0 and i + 2 < n:
            edges[f'n{i}'] = [f'n{i+1}', f'n{i+2}']
            edges[f'n{i+1}'] = [f'n{i+3}'] if i + 3 < n else ['sink']
            edges[f'n{i+2}'] = [f'n{i+3}'] if i + 3 < n else ['sink']
        elif f'n{i}' not in edges:
            edges[f'n{i}'] = [f'n{i+1}']
    edges[f'n{n-1}'] = []
    return edges


def topo_sort(edges: Dict[str, List[str]]) -> List[str]:
    nodes = set(edges) | {v for vs in edges.values() for v in vs}
    indeg = {n: 0 for n in nodes}
    for u, vs in edges.items():
        for v in vs:
            indeg[v] += 1
    order, ready = [], sorted(n for n in nodes if indeg[n] == 0)
    while ready:
        n = ready.pop(0)
        order.append(n)
        for v in sorted(edges.get(n, [])):
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
    assert len(order) == len(nodes), 'cycle'
    return order


def downstream(edges, node):
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in edges.get(n, []):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def closure_options(edges, faulted, executed):
    """All LEGAL recovery closure sets: {faulted} ∪ (subsets of
    downstream∩executed that are still needed). The MINIMAL closure
    is just {faulted}; the FULL closure adds all executed downstream.
    Intermediate options exist when some downstream outputs remain
    valid (e.g., er unaffected by fe fault)."""
    ds = downstream(edges, faulted) & set(executed)
    # legal closures: {faulted} plus any "upward-closed" subset of ds
    # (if you re-execute a node, you must re-execute its downstream
    # that was already executed)
    options = [{faulted}]
    # full closure
    options.append({faulted} | ds)
    # partial: include faulted + some but not all downstream
    # (only valid if the excluded nodes don't depend on included ones)
    for r in range(1, len(ds)):
        for subset in itertools.combinations(sorted(ds), r):
            s = set(subset)
            # check upward-closed: if n in s, all downstream of n
            # that are in ds must also be in s
            valid = all(downstream(edges, n) & ds <= s
                        for n in s)
            if valid:
                options.append({faulted} | s)
    # deduplicate
    unique = []
    for o in options:
        if o not in unique:
            unique.append(o)
    return unique


# ---- Joint action enumeration -----------------------------------------
MODELS = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']


def enumerate_joint_actions(edges, faulted, executed,
                            available_models=MODELS):
    """Enumerate (Z, R, π) joint actions:
    Z: NONE / LOCAL_REPAIR / FULL_RECOVERY / TERMINATE
    R: legal closure sets (from closure_options)
    π: model assignments for nodes in R (permutation with repetition)
    Returns list of (name, Z, R, π) tuples with estimated cost."""
    closures = closure_options(edges, faulted, executed)
    actions = []

    # Z = TERMINATE
    actions.append(dict(
        Z='TERMINATE', R=set(), pi={},
        est_tokens=0, est_time=0,
        description='stop everything'))

    # Z = NONE (accept the fault)
    actions.append(dict(
        Z='NONE', R=set(), pi={},
        est_tokens=0, est_time=0,
        description='accept fault, continue with degraded output'))

    # Z = LOCAL_REPAIR (if fence-only fault)
    actions.append(dict(
        Z='LOCAL_REPAIR', R=set(), pi={},
        est_tokens=0, est_time=0,
        description='zero-call deterministic fence fix'))

    # Z = FULL_RECOVERY: for each closure option × model assignment
    for ri, closure in enumerate(closures):
        repair_nodes = sorted(closure)
        if not repair_nodes:
            continue
        # for small closures, enumerate all model assignments
        if len(repair_nodes) <= 2:
            assignments = list(itertools.product(
                available_models, repeat=len(repair_nodes)))
        else:
            # for larger closures, sample representative assignments
            rng = random.Random(42)
            assignments = [
                tuple(rng.choice(available_models)
                      for _ in repair_nodes)
                for _ in range(min(16, 4 ** len(repair_nodes)))]
            # add "all same model" options
            for m in available_models:
                assignments.append((m,) * len(repair_nodes))

        for ai, assignment in enumerate(assignments):
            pi = dict(zip(repair_nodes, assignment))
            # estimate cost
            est_tok = sum(4000 + 2000 for _ in repair_nodes)
            est_time = sum(20.0 for _ in repair_nodes)
            actions.append(dict(
                Z='FULL_RECOVERY',
                R=set(closure), pi=pi,
                est_tokens=est_tok, est_time=est_time,
                description=f'closure={sorted(closure)}, '
                            f'pi={pi}'))

    return actions


def count_optimization_opportunities(edges, faulted, executed):
    """How many DISTINCT joint actions exist? If < threshold, there
    is no real optimization opportunity for dynamic scheduling."""
    actions = enumerate_joint_actions(edges, faulted, executed)
    closures = closure_options(edges, faulted, executed)
    # count unique (closure, model_assignment) combinations
    unique_combos = set()
    for a in actions:
        if a['Z'] == 'FULL_RECOVERY':
            key = (tuple(sorted(a['R'])),
                   tuple(sorted(a['pi'].items())))
            unique_combos.add(key)
    return dict(
        n_actions=len(actions),
        n_closures=len(closures),
        n_closure_model_combos=len(unique_combos),
        has_opportunity=len(unique_combos) > 4,
        opportunity_description=(
            f'{len(closures)} legal closures × '
            f'{len(unique_combos)} distinct model assignments'
            if unique_combos else 'no recovery options'))


# ---- Audit mode --------------------------------------------------------
def audit():
    """Zero-call audit: generate all structures at all sizes, count
    optimization opportunities at every fault position."""
    results = {}
    for name, gen in STRUCTURES.items():
        for size in (4, 8, 12, 16):
            edges = gen(size)
            nodes = topo_sort(edges)
            key = f'{name}_{size}'
            opps = {}
            for faulted in nodes:
                executed = [n for n in nodes
                            if n not in downstream(edges, faulted)]
                # at a fault during execution, downstream may or may
                # not have run; test both cases
                for scenario, ex_set in [
                        ('early', executed),
                        ('late', nodes)]:
                    o = count_optimization_opportunities(
                        edges, faulted, set(ex_set))
                    opps[f'{faulted}_{scenario}'] = o
            n_opp = sum(1 for v in opps.values() if v['has_opportunity'])
            results[key] = dict(
                n_nodes=size, n_edges=sum(len(v) for v in
                                          edges.values()),
                n_fault_positions=len(nodes),
                n_with_opportunity=n_opp,
                total_positions=len(opps),
                opportunity_rate=round(
                    n_opp / max(1, len(opps)), 3),
                max_closure_choices=max(
                    v['n_closures'] for v in opps.values()),
                max_model_combos=max(
                    v['n_closure_model_combos']
                    for v in opps.values()))
    report = dict(
        version='COMPLEX_DAG_OPPORTUNITY_AUDIT_v1',
        zero_calls=True,
        structures=list(STRUCTURES),
        sizes=[4, 8, 12, 16],
        results=results,
        key_finding='')
    # summarize
    best = max(results.values(), key=lambda r: r['opportunity_rate'])
    report['key_finding'] = (
        f'Best structure: {max(results, key=lambda k: results[k]["opportunity_rate"])} '
        f'with {best["opportunity_rate"]:.0%} opportunity rate; '
        f'4-node diamond: {results.get("diamond_4", {}).get("opportunity_rate", 0):.0%}')
    (HERE / 'COMPLEX_DAG_OPPORTUNITY_AUDIT.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(
        {k: dict(opp_rate=v['opportunity_rate'],
                 max_closures=v['max_closure_choices'],
                 max_combos=v['max_model_combos'])
         for k, v in results.items()}, indent=1))
    print('\n' + report['key_finding'])
    return 0


if __name__ == '__main__':
    raise SystemExit(audit())
