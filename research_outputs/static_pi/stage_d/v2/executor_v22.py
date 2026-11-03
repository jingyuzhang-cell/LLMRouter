"""Stage D V2.2 executor (independent version; frozen stage_d_executor.py untouched).

Encodes V2.2.1 definitions:
  - Z = task re-decomposition with real DAG topology change (split + merge),
        including contracts/prompts DERIVED for the new sub-tasks.
  - R0 = fixed closure re-execution, identical for all four factorial arms.
  - pi = rewrite model of ACTIVE, UNDISPATCHED model nodes only (never Running/Completed/deleted).
  - L1 = deterministic normalization applied to all six arms (not an arm variable).
  - Fault = spec-level and PERSISTENT (not one-shot output corruption).
"""
import json, itertools, random

MODEL_NODES = ('E1', 'E2', 'E3', 'E4', 'J1', 'J2', 'SINK')

def fresh_dag():
    nodes = {
        'E1': dict(kind='model', ups=[], downs=['J1'], sys='E_SYS+POS', user='doc1', deleted=False),
        'E2': dict(kind='model', ups=[], downs=['J1'], sys='E_SYS+POS', user='doc2', deleted=False),
        'E3': dict(kind='model', ups=[], downs=['J2'], sys='E_SYS', user='doc3', deleted=False),
        'E4': dict(kind='model', ups=[], downs=['J2'], sys='E_SYS', user='doc4', deleted=False),
        'J1': dict(kind='model', ups=['E1', 'E2'], downs=['J2'], sys='J1_SYS', user='merge', deleted=False),
        'J2': dict(kind='model', ups=['J1', 'E3', 'E4'], downs=['SINK'], sys='J2_SYS', user='bind', deleted=False),
        'SINK': dict(kind='model', ups=['J2'], downs=[], sys='SINK_SYS', user='compose', deleted=False),
    }
    return dict(nodes=nodes, version=0, edits=[], deleted=set())

def active_model_nodes(dag):
    return [n for n, s in dag['nodes'].items()
            if s['kind'] == 'model' and not s['deleted']]

def _rewire(dag, old, new_name):
    """Replace `old` by `new_name` in BOTH directions of the dependency graph."""
    for up in dag['nodes'][old]['ups']:
        if not dag['nodes'][up]['deleted']:
            dag['nodes'][up]['downs'] = [new_name if d == old else d for d in dag['nodes'][up]['downs']]
    for dn in dag['nodes'][old]['downs']:
        if not dag['nodes'][dn]['deleted']:
            dag['nodes'][dn]['ups'] = [new_name if u == old else u for u in dag['nodes'][dn]['ups']]

def Z_split(dag, node):
    """Real structural change: one node -> two derived sub-tasks + a code merge.
    The sub-tasks get contracts/prompts derived from the original (allowed by the Z definition)."""
    assert node in ('E1', 'E2'), 'Z split only defined for E nodes'
    src = dag['nodes'][node]
    pos, rest, mrg = f'{node}_pos', f'{node}_rest', f'{node}_merge'
    dag['nodes'][pos] = dict(kind='model', ups=list(src['ups']), downs=[mrg],
                             sys='E_SYS+POS_ONLY', user=src['user'], deleted=False, derived_from=node)
    dag['nodes'][rest] = dict(kind='model', ups=list(src['ups']), downs=[mrg],
                              sys='E_SYS_NO_POS', user=src['user'], deleted=False, derived_from=node)
    dag['nodes'][mrg] = dict(kind='code', ups=[pos, rest], downs=list(src['downs']),
                             deleted=False, derived_from=node)
    _rewire(dag, node, mrg)
    dag['nodes'][node]['deleted'] = True
    dag['deleted'].add(node)
    dag['version'] += 1
    dag['edits'].append(dict(op='split', node=node, added=[pos, rest, mrg],
                             dag_version=dag['version']))
    return dag

def R0(dag, node, states, versions):
    """Fixed closure re-execution. Identical for all four factorial arms."""
    versions[node] = versions.get(node, 0) + 1
    states[node] = 'READY'
    stack = list(dag['nodes'][node]['downs'])
    touched = []
    while stack:
        d = stack.pop()
        if d not in dag['nodes'] or dag['nodes'][d]['deleted']:
            continue
        if states.get(d) in ('COMPLETED', 'READY'):
            states[d] = 'READY'
            touched.append(d)
        stack.extend(dag['nodes'][d]['downs'])
    return touched

def compute_U(dag, states):
    """U = active DAG model nodes that are NOT yet dispatched (never Running/Completed/deleted)."""
    return sorted(n for n in active_model_nodes(dag)
                  if states.get(n, 'PENDING') in ('PENDING', 'READY'))

def pi_reassign(dag, U, alt='deepseek'):
    scope = []
    for n in U:
        dag['nodes'][n]['model'] = alt
        scope.append(n)
    return scope
