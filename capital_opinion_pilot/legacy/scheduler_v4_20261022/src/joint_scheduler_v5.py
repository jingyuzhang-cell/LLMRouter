"""joint_scheduler_v5.py — action-class scheduler skeleton (feedback-conditioned).

Replaces the degenerate Z∈{NONE,LOCAL,FULL} with feedback-conditioned classes:
  KEEP           : no re-execution; risk logged (legal always)
  VERIFY         : add annotation verify.v1 on a suspicious node (legal when the
                   suspicion is of class F3 — reasoning-required conflicts; the
                   F2/F5 extraction-grounding trigger is FREE and deterministic,
                   so VERIFY-for-extraction is dominated and not generated)
  REEXEC_LOCAL   : re-execute fault node + invalidation closure (legal when a
                   node is CONFIRMED-INVALID or its upstream changed)
  REEXEC_EXPAND  : LOCAL + re-execute additional caches flagged SEMANTIC-
                   SUSPICIOUS by the deterministic detector (legal when the
                   detector output supports each addition — no fabrication)

Objective (pre-registered): score = Q̂_task (expected chained facts, from
task_quality with measured cells) − w_c·Δtokens − w_l·Δpath_s, with
w_c=2e-5, w_l=0.01. If an action's Q̂ is UNIDENTIFIED, its quality term is
EXCLUDED (recorded as quality_unidentified) and the action competes on cost/
latency only — never a guessed quality value, never a bonus for larger scope.
π enumeration over re-executed nodes is reused from joint_scheduler semantics.
"""
import itertools

from dag_patch import PatchedDAG, NODE_SPECS

W_C, W_L = 2e-5, 0.01


def invalidation_closure(fault_node, children_map, model_nodes):
    out, frontier = {fault_node}, [fault_node]
    while frontier:
        u = frontier.pop()
        for v in children_map.get(u, []):
            if v not in out and v in model_nodes:
                out.add(v)
                frontier.append(v)
    return out


def enumerate_actions(state):
    """state: {fault_node, blocked:set, children_map, model_nodes, feedback:{
    confirmed:[nodes], suspicious:{node:health}}, pools:{node:[models]},
    lineage_valid:{node:bool}, task_quality, facts_per_call, cost_lat:{(node,
    model):(tokens,lat_s)}, ev, deadline_remaining_s}
    Returns list of candidate actions with legality + estimates."""
    fb = state['feedback']
    cands = []
    # KEEP: legal ONLY if no node is contract-invalid (missing/unusable output).
    # A verify-flagged SEMANTIC invalidation keeps a usable output, so KEEP
    # stays legal there and competes on score (pre-registered semantics).
    missing = set(state.get('missing_outputs', []))
    keep_legal = not missing
    cands.append({'class': 'KEEP', 'reexec': {}, 'annotations': [],
                  'legality': 'ok' if keep_legal else 'ILLEGAL_missing_output',
                  'why': 'legal; risk logged' if keep_legal
                         else f'illegal: {sorted(missing)} have no usable output'})
    # VERIFY (annotation) for reasoning-required suspicions (F3 class markers
    # supplied by caller as feedback['verify_targets'])
    for tgt in fb.get('verify_targets', []):
        cands.append({'class': 'VERIFY', 'reexec': {}, 'annotations': [tgt],
                      'legality': 'ok', 'why': f'annotation verify.v1 on {tgt}'})
    # REEXEC_LOCAL for each invalid node (contract-invalid nodes are FORCED:
    # KEEP is illegal above; semantic-invalid nodes compete on score)
    for fnode in fb.get('confirmed', []):
        R = invalidation_closure(fnode, state['children_map'], state['model_nodes'])
        _add_reexec(cands, state, R, 'REEXEC_LOCAL', fnode)
    # REEXEC_EXPAND: LOCAL of the primary fault + suspicious caches
    primary = fb.get('confirmed', [None])[0]
    if primary:
        base = invalidation_closure(primary, state['children_map'], state['model_nodes'])
        susp = [n for n, h in fb.get('suspicious', {}).items() if n not in base]
        # powerset of suspicious extras (small)
        for k in range(1, 1 << len(susp)):
            extras = {susp[i] for i in range(len(susp)) if (k >> i) & 1}
            R = base | extras
            _add_reexec(cands, state, R, 'REEXEC_EXPAND', primary, extras)
    return cands


def _add_reexec(cands, state, R, cls, primary, extras=frozenset()):
    pools = {n: [m for m in state['pools'].get(n, state['pools']['*'])
                 if (n, m) not in state['blocked']] for n in R}
    keys = sorted(R)
    for combo in itertools.product(*(pools[n] for n in keys)):
        pi = dict(zip(keys, combo))
        cost = sum(state['cost_lat'][(n, pi[n])][0] for n in R)
        # parallel path: layers of the base DAG restricted to R (single fault
        # closure is a chain-of-layers; approximate by layering via children_map)
        path = _path_estimate(R, pi, state)
        cands.append({'class': cls, 'reexec': pi, 'R': sorted(R),
                      'annotations': [], 'primary': primary,
                      'extras': sorted(extras),
                      'legality': 'ok', 'tokens': cost, 'path_s': path})


def _path_estimate(R, pi, state):
    layers, rem = [], set(R)
    while rem:
        ready = {n for n in rem if not (set(state['children_map'].get(n, [])) & rem)}
        layers.append(ready)
        rem -= ready
    total = 0.0
    for layer in layers:
        total += max(state['cost_lat'][(n, pi[n])][1] for n in layer)
    return round(total, 1)


def score_actions(cands, state):
    tq = state['task_quality']
    cands = [c for c in cands if c.get('legality', 'ok') == 'ok']  # enforce legality
    out = []
    for c in cands:
        plan = {'keep': {n: state['cache_model'][n] for n in ('t1', 't2')
                         if n not in c['reexec']},
                'reexec': {n: m for n, m in c['reexec'].items() if n in ('t1', 't2')},
                'facts_per_call': state['facts_per_call']}
        q, identified, prov = tq.estimate(state['ev'], plan) if tq else (None, False, {})
        q_term = q if identified else 0.0
        score = q_term - W_C * c.get('tokens', 0) - W_L * c.get('path_s', 0.0)
        out.append({**c, 'q_task': q, 'q_identified': identified,
                    'q_provenance': prov, 'score': round(score, 4)})
    out.sort(key=lambda a: -a['score'])
    return out


def choose(state):
    cands = enumerate_actions(state)
    scored = score_actions(cands, state)
    best = scored[0] if scored else None
    return best, scored
