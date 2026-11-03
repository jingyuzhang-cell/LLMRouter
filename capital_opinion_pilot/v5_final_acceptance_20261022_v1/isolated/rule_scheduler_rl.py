"""Strong rule baseline: same feedback, legal scopes, cells and hard evaluator.

Scope rule: mandatory closure first; add detector-evidenced cache abnormalities
when the caller supplies a severe flag (or grounding < 0.5); verify unresolved
conflicts only with usable caches. Per-node minimum token assignment, retry a
fastest-per-node assignment if infeasible. No joint utility search.
"""
from joint_scheduler_v5 import enumerate_actions, score_actions, normalize_state


def choose(state):
    state = normalize_state(state)
    scored = score_actions(enumerate_actions(state), state)
    fb = state.get('feedback', {})
    severe = set(fb.get('cache_anomalies', {}))
    for node, health in fb.get('suspicious', {}).items():
        if isinstance(health, (tuple, list)) and len(health) == 2 and isinstance(health[0], (int,float)) and isinstance(health[1], (int,float)) and health[1] > 0 and health[0] / health[1] < .5:
            severe.add(node)
    candidates = [c for c in scored if c['legality'] == 'ok']
    # Rules determine scope; per-node choices are independent, not a joint score.
    scopes = {}
    for c in candidates:
        scopes.setdefault((c['Z'], tuple(c['R']), tuple(c['annotations'])), []).append(c)
    preferred = ['EXPAND', 'FULL', 'LOCAL', 'VERIFY', 'NONE'] if severe else ['LOCAL', 'VERIFY', 'NONE', 'EXPAND', 'FULL']
    keys = sorted(scopes, key=lambda k: (preferred.index(k[0]), len(k[1]), k))
    for key in keys:
        group = scopes[key]
        if severe and key[0] == 'EXPAND' and not severe <= set(key[1]):
            continue
        models = sorted({n for c in group for n in c['pi']})
        for metric in (0, 1):
            pi = {}
            for n in models:
                choices = sorted({c['pi'][n] for c in group if n in c['pi']})
                choices = [m for m in choices if (n, m) in state.get('cost_lat', {})]
                if not choices:
                    break
                pi[n] = min(choices, key=lambda m: (state['cost_lat'][(n, m)][metric], m))
            match = next((c for c in group if c['pi'] == pi and c['feasible']), None)
            if match:
                return {**match, 'selection_rule': 'RL_scope_rules_then_per_node_cost_or_latency'}, scored
    return None, scored
