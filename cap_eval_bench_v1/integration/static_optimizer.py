"""Static heterogeneous allocation optimizer (alloc_static_opt) — REAL, executable.

Genuinely distinct from Router:
  Router     : per-node INDEPENDENT choice by quality/cost ratio (myopic, no constraints)
  Static-Opt : EXHAUSTIVE exact search over all 2^N assignments under GLOBAL constraints
               (total token budget, critical-path latency, per-model quotas), maximizing a
               dependency-weighted quality estimate; emits a legal assignment map the
               executor must honor call-by-call.

Profiles are MEASURED from frozen ledgers (provenance per field); conservative priors are
used where no direct measurement exists and are flagged as such.
"""
import itertools
import json

# ---- measured profiles (median tokens per node-kind per model; latency seconds) ----
# GLM-5.3: stage_a confirm-v3 ledger; Flash: V2/V2.1 comparison ledgers (node-level medians)
COST = {  # tokens
    'index':        {'glm53': 643,  'flash': 1063},
    'extracts':     {'glm53': 2783, 'flash': 1063},
    'timeline':     {'glm53': 882,  'flash': 1063},
    'entity_facts': {'glm53': 882,  'flash': 1063},
    'factcheck':    {'glm53': 1362, 'flash': 1063},
    'report':       {'glm53': 1051, 'flash': 1063},
}
LAT = {  # seconds (service latency medians; Flash includes observed repair overhead)
    'index':        {'glm53': 4.0, 'flash': 6.0},
    'extracts':     {'glm53': 6.0, 'flash': 8.0},
    'timeline':     {'glm53': 5.0, 'flash': 7.0},
    'entity_facts': {'glm53': 5.0, 'flash': 7.0},
    'factcheck':    {'glm53': 6.0, 'flash': 8.0},
    'report':       {'glm53': 6.0, 'flash': 8.0},
}
# quality prior per (kind, model) — provenance:
#  flash==glm on extraction branches: V2.1 extracts redo Q_raw parity (0.8125 == 0.8125)
#  flash on analysis/verify: V2/V2.1 comparisons 0.688-0.812 vs glm 0.812 -> 0.9
#  flash on report: NO direct measurement under fair contract -> conservative 0.7 (flagged)
QW = {
    'index':        {'glm53': 1.0, 'flash': 1.0},
    'extracts':     {'glm53': 1.0, 'flash': 1.0},
    'timeline':     {'glm53': 1.0, 'flash': 0.9},
    'entity_facts': {'glm53': 1.0, 'flash': 0.9},
    'factcheck':    {'glm53': 1.0, 'flash': 0.9},
    'report':       {'glm53': 1.0, 'flash': 0.7},   # PRIOR_UNKNOWN conservative
}
NODE_IMPORTANCE = {'index': 0.5, 'extracts': 1.0, 'timeline': 0.8, 'entity_facts': 0.8,
                   'factcheck': 1.2, 'report': 1.5}


def quality_est(assignment, kinds):
    return sum(NODE_IMPORTANCE[kinds[n]] * QW[kinds[n]][m] for n, m in assignment.items()) \
        / sum(NODE_IMPORTANCE[k] for k in kinds.values())


def cost_est(assignment, kinds):
    return sum(COST[kinds[n]][m] for n, m in assignment.items())


def latency_est(assignment, kinds, deps):  # deps keyed by node id
    """Critical-path service latency over the DAG (serial per-node latency)."""
    memo = {}

    def depth(n):
        if n in memo:
            return memo[n]
        memo[n] = LAT[kinds[n]][assignment[n]] + max((depth(d) for d in deps.get(n, [])), default=0.0)
        return memo[n]
    return max(depth(n) for n in kinds)


DEPS_BY_KIND = {'extracts': ['index'], 'timeline': ['extracts'], 'entity_facts': ['extracts'],
                'factcheck': ['extracts', 'timeline', 'entity_facts'], 'report': ['factcheck']}


def deps_for(nodes):
    """Node-id keyed dependency map derived from kinds (canonical graph)."""
    by_kind = {}
    for n, k in nodes.items():
        by_kind.setdefault(k, n)
    return {n: [by_kind[d] for d in DEPS_BY_KIND.get(k, []) if d in by_kind]
            for n, k in nodes.items()}


def optimize(nodes, budget_tokens=None, max_latency_s=None, quota_flash=None):
    """nodes: {node_id: kind}. Exact exhaustive search over 2^N assignments."""
    ids = sorted(nodes)
    deps = deps_for(nodes)
    best = None
    for combo in itertools.product(['glm53', 'flash'], repeat=len(ids)):
        a = dict(zip(ids, combo))
        c = cost_est(a, nodes)
        if budget_tokens and c > budget_tokens:
            continue
        if max_latency_s and latency_est(a, nodes, deps) > max_latency_s:
            continue
        if quota_flash is not None:
            fc = sum(COST[nodes[n]]['flash'] for n, m in a.items() if m == 'flash')
            if fc > quota_flash:
                continue
        q = quality_est(a, nodes)
        key = (round(q, 6), -c)
        if best is None or key > best['key']:
            best = {'key': key, 'assignment': a, 'Q_est': round(q, 4), 'C_est': c,
                    'L_est': round(latency_est(a, nodes, deps), 1)}
    return best


DEPS_DEFAULT = {'extracts': ['index'], 'timeline': ['extracts'], 'entity_facts': ['extracts'],
                'factcheck': ['extracts', 'timeline', 'entity_facts'], 'report': ['factcheck']}


def router_assignment(nodes):
    """Myopic per-node ratio choice (contrast arm): flash iff QW>=0.95 and cost saving >25%."""
    a = {}
    for n, k in nodes.items():
        saving = (COST[k]['glm53'] - COST[k]['flash']) / COST[k]['glm53']
        a[n] = 'flash' if (QW[k]['flash'] >= 0.95 and saving > 0.25) else 'glm53'
    return a


def rule_assignment(nodes):
    """Frozen rule: flash on extraction/analysis branches, glm on verify+report."""
    return {n: ('flash' if k in ('index', 'extracts', 'timeline', 'entity_facts') else 'glm53')
            for n, k in nodes.items()}


CANON = {'n_index': 'index', 'n_extracts': 'extracts', 'n_timeline': 'timeline',
         'n_entity': 'entity_facts', 'n_factcheck': 'factcheck', 'n_report': 'report'}

if __name__ == '__main__':
    homo_strong_c = sum(COST[k]['glm53'] for k in CANON.values())
    best = optimize(CANON, budget_tokens=int(homo_strong_c * 0.75),   # frozen: ≥25% cost cut vs homo_strong
                    max_latency_s=40.0, quota_flash=90000)
    print('static_opt :', json.dumps(best, ensure_ascii=False))
    print('router     :', router_assignment(CANON))
    print('rule       :', rule_assignment(CANON))
    print('homo_strong C_est =', homo_strong_c,
          '| homo_cheap C_est =', sum(COST[k]['flash'] for k in CANON.values()))
