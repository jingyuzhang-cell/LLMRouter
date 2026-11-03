"""V5: evidence-gated joint recovery enumeration, hard constraints and Pareto.

No model API, no node-minimum quality, no rewards for larger R. A quality
estimator's scope is recorded: historical chained-fact proxies are NOT terminal
accuracy. Unknown quality is None, never zero. Independent terminal constraints
require an explicitly terminal-calibrated estimator. Selection: identified
quality first, weighted task estimate / token / critical-path utility, then
stable scope/model tie breaks; unknown-only candidates minimize token/time.
All rejected and feasible candidates remain in the decision audit.
"""
from scheduler_common import closure, descendants, assignments, estimates, topological

W_C, W_L = 2e-5, 0.01
CLASSES = {'NONE': 'KEEP', 'LOCAL': 'REEXEC_LOCAL', 'EXPAND': 'REEXEC_EXPAND',
           'FULL': 'REEXEC_FULL', 'VERIFY': 'VERIFY'}


def invalidation_closure(fault_node, children_map, model_nodes):
    return closure({fault_node}, children_map, model_nodes)


def required_roots(state):
    roots = set(state.get('missing_outputs', ()))
    roots.update(n for n, valid in state.get('lineage_valid', {}).items() if not valid)
    roots.update(n for n, valid in state.get('contract_valid', {}).items() if not valid)
    lin = state.get('lineage')
    if lin is not None:
        roots.update(n for n, fp in state.get('current_fps', {}).items() if not lin.valid(n, fp))
    roots.update(state.get('feedback', {}).get('hard_invalid', ()))
    return roots


def cache_evidence_nodes(feedback):
    result = set()
    for n, health in feedback.get('suspicious', {}).items():
        if (isinstance(health, (tuple, list)) and len(health) == 2
                and all(isinstance(x, (int, float)) for x in health)
                and 0 <= health[0] < health[1]):
            result.add(n)
        elif isinstance(health, dict) and health.get('evidence_ref') and health.get('kind'):
            result.add(n)
    for n, evidence in feedback.get('cache_anomalies', {}).items():
        if isinstance(evidence, dict) and evidence.get('evidence_ref') and evidence.get('kind'):
            result.add(n)
    return result


def scope_specs(state):
    topological(state['children_map'], state['model_nodes'])
    fb = state.get('feedback', {})
    hard = required_roots(state)
    model_nodes = set(state['model_nodes'])
    if not hard <= model_nodes:
        raise ValueError('invalid root outside model graph')
    base = closure(hard | set(fb.get('confirmed', ())), state['children_map'], model_nodes)
    evidence = cache_evidence_nodes(fb)
    evidence &= model_nodes
    specs = [('NONE', set(), 'ok' if not hard and not state.get('verification_required') else 'missing_invalid_or_pending_verification', set())]
    if base:
        specs.append(('LOCAL', base, 'ok', set()))
    extras = sorted(evidence - base)
    if len(extras) > state.get('max_extra_nodes', 12):
        raise ValueError('expansion_search_limit')
    for mask in range(1, 1 << len(extras)):
        roots = {n for i, n in enumerate(extras) if mask & (1 << i)}
        scope = closure(base | roots, state['children_map'], model_nodes)
        specs.append(('EXPAND', scope, 'ok', roots))
    if base:
        supported = closure(base | evidence, state['children_map'], model_nodes)
        # FULL is recorded but rejected if it requires unsupported extra work.
        reason = 'ok' if supported == model_nodes else 'unsupported_full_expansion'
        specs.append(('FULL', model_nodes, reason, evidence - base))
    return specs


def enumerate_actions(state):
    cands = []
    for z, scope, reason, extras in scope_specs(state):
        combos = assignments(scope, state) if reason == 'ok' else []
        if not combos:
            combos = [{}]
            if reason == 'ok':
                reason = 'no_available_compatible_assignment'
        for pi in combos:
            c = {'Z': z, 'class': CLASSES[z], 'R': sorted(scope), 'pi': pi,
                 'reexec': pi, 'annotations': [], 'extras': sorted(extras),
                 'legality': 'ok' if reason == 'ok' else 'ILLEGAL_' + reason,
                 'why': reason, 'actual_execution': None}
            cands.append(c)
    fb = state.get('feedback', {})
    # VERIFY is independent annotation work, not a substitute for invalid output.
    supported = set(fb.get('verify_targets', ())) & set(state.get('cache_model', {}))
    for target in sorted(supported):
        scope = {'verify_' + target}
        for pi in assignments(scope, state) or [{}]:
            cands.append({'Z': 'VERIFY', 'class': 'VERIFY', 'R': [], 'pi': pi,
                          'reexec': {}, 'annotations': [target], 'extras': [],
                          'legality': 'ok' if pi and not required_roots(state) and fb.get('verify_conflicts', {}).get(target, {}).get('evidence_ref') else 'ILLEGAL_verify_without_supported_conflict_or_repair',
                          'why': 'supported_conflict_annotation', 'actual_execution': None})
    return cands


def _quality(c, state):
    estimator = state.get('quality_evaluator') or state.get('task_quality')
    if estimator is None:
        return None, False, {'reason': 'no_calibrated_task_estimator'}, 'UNIDENTIFIED'
    # Estimator sees the complete plan, not just a hard-coded pair of nodes.
    future = {**state.get('pending_assignment', {}), **c['reexec']}
    keep = {n: m for n, m in state.get('cache_model', {}).items() if n not in c['R'] and n not in future}
    plan = {'keep': keep, 'reexec': future, 'annotations': c['annotations'],
            'facts_per_call': state.get('facts_per_call', {}),
            'invalid_cache': sorted(required_roots(state)),
            'downstream_changed': sorted(set(c['R']) - set(getattr(estimator, 'required_nodes', ())))}
    q, identified, provenance = estimator.estimate(state.get('ev'), plan)
    scope = getattr(estimator, 'quality_scope', 'UNIDENTIFIED')
    if c['Z'] == 'VERIFY':
        # Verification value-of-information is unknown without a calibrated cell.
        q, identified = None, False
        provenance = {'reason': 'verification_effect_unidentified', 'base_estimate': provenance}
    if identified and (not isinstance(q, (float, int)) or not __import__('math').isfinite(q)):
        raise ValueError('invalid_quality_estimate')
    return q if identified else None, identified, provenance, scope


def evaluate_candidate(candidate, state):
    c = dict(candidate)
    reasons = [] if c['legality'] == 'ok' else [c['legality']]
    try:
        remaining = {n: m for n, m in state.get('pending_assignment', {}).items() if n not in c['reexec']}
        full_pi = {**remaining, **c['pi']}
        scope = set(c['reexec']) | set(remaining) | set(c['pi'] if c['Z'] == 'VERIFY' else ())
        tokens, latency, cash = estimates(scope, full_pi, state)
    except ValueError as e:
        tokens, latency, cash = None, None, None
        reasons.append(str(e))
    q, identified, provenance, quality_scope = _quality(c, state)
    # The old expected-fact proxy remains diagnostic, not calibrated full Q.
    terminal = q if identified and quality_scope == 'terminal_calibrated' else None
    diagnostic_proxy = q if identified and quality_scope != 'terminal_calibrated' else None
    if diagnostic_proxy is not None and not state.get('allow_proxy_objective', False):
        q, identified = None, False
    if terminal is not None and not 0 <= terminal <= 1:
        raise ValueError('terminal_quality_out_of_range')
    if tokens is not None:
        if tokens > state.get('token_budget_remaining', float('inf')):
            reasons.append('token_budget')
        if latency > state.get('deadline_remaining_s', float('inf')):
            reasons.append('deadline')
        for currency, amount in (cash or {}).items():
            if amount > state.get('cash_budget', {}).get(currency, float('inf')):
                reasons.append('cash_budget:' + currency)
    q_min = state.get('terminal_q_min')
    if q_min is not None:
        if terminal is None:
            reasons.append('terminal_quality_unidentified')
        elif terminal < q_min:
            reasons.append('terminal_quality_constraint')
    c.update(tokens=tokens, path_s=latency, cash_cost=cash, q_task=q,
             q_identified=identified, q_provenance=provenance, quality_scope=quality_scope,
             terminal_q=terminal, diagnostic_q_proxy=diagnostic_proxy,
             terminal_q_identified=terminal is not None, feasible=not reasons, rejection_reasons=reasons)
    c['score'] = ((q if identified else 0) - state.get('w_c', W_C) * tokens
                  - state.get('w_l', W_L) * latency) if not reasons else None
    # The zero above is only an absent objective term, not a quality observation.
    c['quality_term_used'] = identified
    c['selection_rule'] = 'identified_estimate_then_weighted_utility_then_stable_tiebreak'
    return c


def _rank(c):
    return (not c['q_identified'], -c['score'], len(c['R']),
            ('LOCAL', 'EXPAND', 'FULL', 'NONE', 'VERIFY').index(c['Z']),
            tuple(sorted(c['pi'].items())))


def score_actions(cands, state):
    out = [evaluate_candidate(c, state) for c in cands]
    groups = {}
    for c in out:
        c['pareto'] = False
        if c['feasible']:
            groups.setdefault((c['q_identified'], c['quality_scope']), []).append(c)
    for (identified, quality_scope), group in groups.items():
        currencies = sorted({k for c in group for k in c['cash_cost']})
        def vector(c):
            return ((-c['q_task'],) if identified else ()) + (c['tokens'], c['path_s']) + tuple(c['cash_cost'].get(k, 0) for k in currencies)
        vectors = {vector(c) for c in group}
        front = {v for v in vectors if not any(all(x <= y for x, y in zip(u, v)) and any(x < y for x, y in zip(u, v)) for u in vectors)}
        for c in group:
            c['pareto'] = vector(c) in front
    return sorted(out, key=lambda c: (not c['feasible'], _rank(c) if c['feasible'] else ()))


def choose(state):
    if 'feedback_records' in state:
        from feedback_detector import recovery_feedback
        state = {**state, 'feedback': recovery_feedback(state['feedback_records'])}
    scored = score_actions(enumerate_actions(state), state)
    front = [c for c in scored if c['feasible'] and c['pareto']]
    return (min(front, key=_rank) if front else None), scored
