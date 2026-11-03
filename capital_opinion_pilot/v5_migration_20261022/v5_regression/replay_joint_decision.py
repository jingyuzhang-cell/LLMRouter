"""Zero-pay replay demo of the two-stage joint scheduler on the D-arm's REAL ledgers.

REPLAY_ONLY: verifies the decision procedure is executable/auditable and that
(Z, R, pi) actually varies with state (budget/deadline/fault position). It does
NOT produce new measured quality gains. Uses only recorded usage/latency/graph
facts from model_call_ledger_qcl{c,d}.jsonl.
"""
import json

from pilot_common import PILOT_DIR

# node-level historical stats from the real C/D runs (P50/P90 latency, mean tokens,
# contract-ok rate) — this stands in for the RQ1 capability table (frozen inputs).
STATS = {  # node: model -> (tok_mean, lat_p50, lat_p90, contract_ok)
    ('t3', 'glm53'): (2382, 5.5, 7.0, 1.0), ('t3', 'glm53flash'): (2382, 6.0, 8.0, 1.0),
    ('t4', 'glm53'): (2716, 7.9, 10.0, 1.0), ('t4', 'glm53flash'): (2716, 10.7, 14.0, 1.0),
    ('t5', 'glm53'): (1881, 5.7, 7.5, 1.0), ('t5', 'glm53flash'): (2690, 16.1, 20.0, 0.5),
    ('t6', 'glm53'): (1103, 7.3, 9.5, 1.0), ('t6', 'glm53flash'): (1500, 9.0, 12.0, 1.0),
}
DESC = {'t3': ['t5', 't6'], 't4': ['t5', 't6'], 't5': ['t6']}
DEFAULT_PI = {'t5': 'glm53', 't6': 'glm53'}


def predict_cost(R, pi):
    return sum(STATS[(n, pi.get(n, 'glm53'))][0] for n in R)


def predict_lat(R, pi):
    return sum(STATS[(n, pi.get(n, 'glm53'))][2] for n in R)


def feasible(action, spent, B, now, T, Qmin, qtable):
    Z, R, pi = action
    if spent + predict_cost(R, pi) > B:
        return False, 'budget'
    if now + predict_lat(R, pi) > T:
        return False, 'deadline'
    if R and min(qtable.get((n, pi.get(n, 'glm53')), 0.0) for n in R) < Qmin:
        return False, 'quality_lower_bound'
    return True, 'ok'


def enumerate_actions(fault_node, failed_model):
    acts = [(Z, R, pi) for Z in ('NONE', 'LOCAL', 'FULL')
            for R in [set()] if Z == 'NONE'
            for pi in [{}]]
    # R determined by Z and closure
    Rs = {'NONE': set(), 'LOCAL': {fault_node} | set(DESC[fault_node]),
          'FULL': {'t3', 't4', 't5', 't6'}}
    models = ('glm53', 'glm53flash')
    for Z in ('LOCAL', 'FULL'):
        for Z_ in [Z]:
            pass
        R = Rs[Z]
        # enumerate pi over fault node + descendants (others keep planned/default)
        import itertools
        keys = sorted(R)
        for combo in itertools.product(models, repeat=len(keys)):
            pi = dict(DEFAULT_PI)
            pi.update(dict(zip(keys, combo)))
            acts.append((Z, R, pi))
    return acts


def schedule(fault_node, failed_model, spent, B, now, T, Qmin, qtable):
    aud = []
    best = None
    for a in enumerate_actions(fault_node, failed_model):
        Z, R, pi = a
        ok, why = feasible(a, spent, B, now, T, Qmin, qtable)
        aud.append({'Z': Z, 'R': sorted(R), 'pi': {k: v for k, v in pi.items() if k in R},
                    'cost': predict_cost(R, pi), 'lat_p90': predict_lat(R, pi), 'feasible': ok, 'why': why})
        if ok:
            score = sum(qtable.get((n, pi.get(n, 'glm53')), 0.0) for n in R) / max(1, len(R)) \
                    - 0.00002 * predict_cost(R, pi) - 0.01 * predict_lat(R, pi)
            if Z == 'NONE':
                score = -1  # never acceptable when a node failed (chain incomplete)
            if best is None or score > best[0]:
                best = (score, a)
    return (best[1] if best else None), aud


def main():
    # qtable from real C/D runs (content-Q on raw, contract-adjusted): frozen stand-in
    qtable = {('t3', 'glm53'): 0.75, ('t3', 'glm53flash'): 0.55, ('t4', 'glm53'): 0.65,
              ('t4', 'glm53flash'): 0.70, ('t5', 'glm53'): 0.75, ('t5', 'glm53flash'): 0.60,
              ('t6', 'glm53'): 0.80, ('t6', 'glm53flash'): 0.55}
    scenarios = [
        ('seed1 t3-fail, 宽松约束', 't3', 'glm53flash', 20000, 100000, 0.0, 90.0, 0.55),
        ('seed1 t3-fail, 预算紧', 't3', 'glm53flash', 20000, 26000, 0.0, 90.0, 0.55),
        ('seed3 t5-fail, 截止紧', 't5', 'glm53', 30000, 60000, 0.0, 12.0, 0.55),
        ('seed3 t5-fail, 宽松', 't5', 'glm53', 30000, 60000, 0.0, 90.0, 0.55),
    ]
    out = []
    for name, fn, fm, spent, B, now, T, Qmin in scenarios:
        act, aud = schedule(fn, fm, spent, B, now, T, Qmin, qtable)
        n_rej = {w: sum(1 for a in aud if not a['feasible'] and a['why'] == w)
                 for w in ('budget', 'deadline', 'quality_lower_bound')}
        out.append({'scenario': name, 'chosen': {'Z': act[0], 'R': sorted(act[1]),
                                                  'pi': {k: v for k, v in act[2].items() if k in act[1]}},
                    'predicted_cost': predict_cost(act[1], act[2]),
                    'predicted_lat_p90': predict_lat(act[1], act[2]),
                    'rejected': n_rej, 'n_candidates': len(aud)})
        print(name, '->', out[-1]['chosen'], 'cost', out[-1]['predicted_cost'],
              'lat', out[-1]['predicted_lat_p90'], 'rejected', n_rej)
    json.dump({'replay_only': True, 'source': 'qcl C/D ledgers + STATS table',
               'scenarios': out}, open(PILOT_DIR / 'replay_joint_decision_result.json', 'w'),
              ensure_ascii=False, indent=1)
    zs = {o['chosen']['Z'] for o in out}
    pis = {(o['chosen']['Z'], tuple(sorted(o['chosen']['R'])), o['chosen']['pi'].get(
        [n for n in o['chosen']['R']][0] if o['chosen']['R'] else 't5', '?')) for o in out}
    print('joint-ness check: Z varies =', len(zs) > 1, '; distinct decisions =', len(pis))


if __name__ == '__main__':
    main()
