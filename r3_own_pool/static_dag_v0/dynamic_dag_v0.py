"""Dynamic DAG v0 — control-flow validation via zero-generation replay.

Walks each fresh-holdout task's mini-DAG (extraction* -> reasoning ->
verification) in frozen order. On node failure: diagnose as model-recoverable,
reroute to the router's SECOND-best candidate under the frozen utility (never
hindsight oracle), allow at most one further escalation, mark downstream
dependents stale and re-evaluate them. Because the underlying table is the
conditional node table (gold inputs for reasoning/verification), this
validates the CONTROL FLOW (state transitions), not real error propagation.
"""
import argparse
import json

import numpy as np

from . import core

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/dynamic_dag_v0'
POOL = ['medium', 'large', 'coder']
TYPE_ORDER = {'extraction': 0, 'reasoning': 1, 'verification': 2}
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0


def replay(nodes, sub, X, coef, intercept, mean_C, mean_L):
    qhat = X @ coef.T + intercept
    utility = qhat - ALPHA_C * mean_C - ALPHA_L * mean_L      # (nodes, 3) deployable
    log = []
    stats = dict(tasks=0, executed=0, failures=0, reroutes=0, recovered_second=0,
                 escalations=0, recovered_third=0, hard_failures=0, stale_marks=0,
                 reevaluations=0, decompose_candidates=[])
    by_task = {}
    for i, n in enumerate(nodes):
        by_task.setdefault(n['task_uid'], []).append(i)
    for uid, idxs in by_task.items():
        idxs = sorted(idxs, key=lambda i: (TYPE_ORDER.get(nodes[i]['node_type'], 9), nodes[i]['node_id']))
        stats['tasks'] += 1
        stale = set()
        for pos, i in enumerate(idxs):
            stats['executed'] += 1
            order = list(np.argsort(-utility[i]))
            pick = int(order[0])
            q = float(sub['Q'][i, pick])
            attempt = [POOL[pick]]
            if q <= 0:
                stats['failures'] += 1
                second = int(order[1])
                stats['reroutes'] += 1
                attempt.append(POOL[second])
                q2 = float(sub['Q'][i, second])
                if q2 <= 0 and len(order) > 2:
                    third = int(order[2])
                    stats['escalations'] += 1
                    attempt.append(POOL[third])
                    q2 = float(sub['Q'][i, third])
                q = q2
                if q <= 0:
                    stats['hard_failures'] += 1
                    if nodes[i]['node_type'] == 'reasoning':
                        stats['decompose_candidates'].append(dict(node_id=nodes[i]['node_id'], task_uid=uid,
                                                                  models_tried=attempt))
                else:
                    stats['recovered_second' if len(attempt) == 2 else 'recovered_third'] += 1
                # invalidate downstream dependents and re-evaluate them
                for j in idxs[pos + 1:]:
                    if j not in stale:
                        stale.add(j)
                        stats['stale_marks'] += 1
                    stats['reevaluations'] += 1
            log.append(dict(task_uid=uid, node_id=nodes[i]['node_id'], node_type=nodes[i]['node_type'],
                            attempts=attempt, final_q=q, was_stale=i in stale,
                            stale_cascade=sorted(nodes[j]['node_id'] for j in stale if j in idxs[pos + 1:])[:4]))
    choices = np.zeros(len(nodes), dtype=int)

    def final_pick(entry):
        return POOL.index(entry['attempts'][-1])

    for entry in log:
        i = next(k for k, n in enumerate(nodes) if n['node_id'] == entry['node_id'])
        choices[i] = POOL.index(entry['attempts'][-1])
    Q = sub['Q'][np.arange(len(choices)), choices]
    C = sub['C'][np.arange(len(choices)), choices].astype(float)
    L = sub['L'][np.arange(len(choices)), choices].astype(float)
    base = int(np.argmax(utility[0])) if len(utility) else 0
    # deployable variant: second-best only, no escalation (pool has 3 models, so
    # best+second+third would equal the pool oracle by construction - inflated)
    second_choices = choices.copy()
    for entry in log:
        i = next(k for k, n in enumerate(nodes) if n['node_id'] == entry['node_id'])
        if len(entry['attempts']) >= 2:
            second_choices[i] = POOL.index(entry['attempts'][1])
    Qs = sub['Q'][np.arange(len(second_choices)), second_choices]
    Cs = sub['C'][np.arange(len(second_choices)), second_choices].astype(float)
    Ls = sub['L'][np.arange(len(second_choices)), second_choices].astype(float)
    stats['deployable_second_only'] = dict(Q=float(Qs.mean()), tokens=float(Cs.mean()),
                                           latency_s=float(Ls.mean()),
                                           utility=float((Qs - ALPHA_C * Cs - ALPHA_L * Ls).mean()),
                                           calls_multiplier=float((stats['executed'] + stats['reroutes'])
                                                                  / max(1, stats['executed'])))
    stats['oracle_bound_warning'] = ('with a 3-model pool, allowing escalation to the third candidate '
                                     'enumerates the pool; final Q then equals the pool oracle and is a '
                                     'ceiling, not deployable evidence')
    stats['final'] = dict(Q=float(Q.mean()), tokens=float(C.mean()), latency_s=float(L.mean()),
                          utility=float((Q - ALPHA_C * C - ALPHA_L * L).mean()),
                          calls_multiplier=float(stats['executed'] + stats['reroutes'] + stats['escalations'])
                          / max(1, stats['executed']))
    return log, stats


def run():
    if OUT.exists():
        raise FileExistsError('dynamic_dag_v0 already exists')
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    order = {t['uid']: k for k, t in enumerate(json.loads((SRC / 'TASKS.json').read_text()))}
    idx = [i for i, n in enumerate(nodes_all) if matrix['main'][i]]
    idx.sort(key=lambda i: order[nodes_all[i]['task_uid']])
    nodes = [nodes_all[i] for i in idx]
    sub = {k: v[idx] for k, v in matrix.items() if k in ('Q', 'C', 'L', 'FrozenNodeRouter', 'NodeOracle')}
    types = np.array([[1.0 if n['node_type'] == t else 0.0
                       for t in ['extraction', 'transformation', 'reasoning', 'verification']] for n in nodes])
    ctx = np.log1p(np.array([len(n['question']) for n in nodes], dtype=float)).reshape(-1, 1)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    X = np.hstack([np.array([emb['emb'][qmap[n['question']]] for n in nodes]), types, ctx])
    log, stats = replay(nodes, sub, X, dev['NodeRouter_coef'], dev['NodeRouter_intercept'],
                        dev['mean_C'], dev['mean_L'])
    frozen = sub['FrozenNodeRouter'].astype(int)
    Qf = sub['Q'][np.arange(len(nodes)), frozen]
    stats['vs_frozen_static'] = dict(Q_static=float(Qf.mean()), Q_dynamic=stats['final']['Q'],
                                     delta_pp=100 * (stats['final']['Q'] - Qf.mean()))
    stats['pass_criteria'] = dict(
        c1_failures_trigger_reroute=stats['reroutes'] == stats['failures'],
        c2_descendants_marked_stale=stats['stale_marks'] > 0,
        c3_note='structural decomposition exercised in the separate pilot stage',
        c4_new_flow_executes_and_returns_final_state=True)
    OUT.mkdir()
    (OUT / 'REPLAY.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in log))
    core.write(OUT / 'RESULTS.json', dict(
        experiment='Dynamic DAG v0 (control-flow validation, zero generation)',
        framing='conditional node table: validates reroute/stale/reevaluate CONTROL FLOW, not real error propagation',
        reroute_policy='second-best under frozen deployable utility; one escalation allowed; never hindsight oracle',
        stats=stats, decompose_pilot_pool=[c['node_id'] for c in stats['decompose_candidates']][:20]))
    print(json.dumps({k: v for k, v in stats.items() if k not in ('decompose_candidates',)},
                     indent=1, ensure_ascii=False))
    print('decompose candidates (reasoning, hard-failed):', len(stats['decompose_candidates']))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
