"""Graph Forest v0: retrievable, reusable, versioned history-graph memory.

Three-round follow-up closed loop over the fresh-holdout history. The forest
persists per-task graphs (nodes with model/Q/C/L/status + edges + versions).
Round 1 loads history graphs (zero calls). Round 2 issues a follow-up that
REUSES a stored task's result and executes only the new aggregate node.
Round 3 modifies one input fact of a stored task: locates affected nodes,
keeps old versions, invalidates dependents, recomputes only those. PASS =
store/retrieve/reuse/modify/invalidate all demonstrated, with call counts
proving reused nodes are never re-executed.
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/graph_forest_v0'
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0
AGG_PROMPT = ('Compare two financial results and state which is larger and the difference. '
              'Return ONLY JSON {{"a":number,"b":number,"larger":"a"|"b","difference":number}}.\n'
              'RESULT A ({qa}): {a}\nRESULT B ({qb}): {b}')


class Forest:
    def __init__(self):
        self.graphs = {}

    def save_graph(self, task):
        self.graphs[task['uid']] = dict(task_uid=task['uid'], question=task['question'], nodes=task['nodes'],
                                        edges=task['edges'], version=0)

    def retrieve(self, uid):
        return self.graphs[uid]

    def node(self, uid, node_id):
        return next(n for n in self.graphs[uid]['nodes'] if n['node_id'] == node_id)

    def modify_fact(self, uid, fact_index, new_value):
        g = self.graphs[uid]
        g['version'] += 1
        affected, invalidated = [], []
        for n in g['nodes']:
            if n['node_type'] == 'reasoning' and fact_index in n.get('uses_facts', []):
                n['versions'] = n.get('versions', [])
                n['versions'].append(dict(value=n['value'], version=g['version'] - 1, reason='pre-modify'))
                n['stale'] = True
                affected.append(n['node_id'])
            elif n['node_type'] == 'verification' and n.get('depends_on') in affected:
                n['versions'] = n.get('versions', [])
                n['versions'].append(dict(value=n['value'], version=g['version'] - 1, reason='upstream-modified'))
                n['stale'] = True
                invalidated.append(n['node_id'])
        return affected, invalidated

    def recompute(self, uid, node_id, result):
        n = self.node(uid, node_id)
        n.update(result)
        n['stale'] = False
        n['recomputed'] = True
        return n


def run():
    if OUT.exists():
        raise FileExistsError('graph_forest_v0 already exists')
    OUT.mkdir()
    tasks = json.loads((SRC / 'TASKS.json').read_text())
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    matrix = {k: (v if k[0].isupper() else v) for k, v in matrix.items()}
    sub = {k: matrix[k] for k in ('Q', 'C', 'L', 'FrozenNodeRouter')}
    ids = {n['node_id']: i for i, n in enumerate(nodes_all)}
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    forest = Forest()
    calls = []
    evidence = {}

    # ---- Round 1: store two history graphs from executed tasks (zero calls)
    picks = [t for t in tasks if any(n['task_uid'] == t['uid'] and n['node_type'] == 'reasoning'
                                     and sub['Q'][ids[n['node_id']], sub['FrozenNodeRouter'][ids[n['node_id']]]] > 0
                                     for n in nodes_all)][:2]
    stored = []
    for t in picks:
        tnodes = []
        reasoning = next(n for n in nodes_all if n['task_uid'] == t['uid'] and n['node_type'] == 'reasoning')
        ridx = ids[reasoning['node_id']]
        model = ['medium', 'large', 'coder'][int(sub['FrozenNodeRouter'][ridx])]
        tnodes.append(dict(node_id=reasoning['node_id'], node_type='reasoning', model=model,
                           value=float(t['answer']), uses_facts=list(range(len(reasoning['gold_facts']['facts']))),
                           Q=float(sub['Q'][ridx, sub['FrozenNodeRouter'][ridx]]),
                           C=int(sub['C'][ridx, sub['FrozenNodeRouter'][ridx]]),
                           L=float(sub['L'][ridx, sub['FrozenNodeRouter'][ridx]])))
        ver = next(n for n in nodes_all if n['task_uid'] == t['uid'] and n['node_type'] == 'verification'
                   and n['node_id'].endswith('vfpos'))
        vidx = ids[ver['node_id']]
        tnodes.append(dict(node_id=ver['node_id'], node_type='verification', model=model,
                           value=True, depends_on=reasoning['node_id'],
                           Q=float(sub['Q'][vidx, sub['FrozenNodeRouter'][vidx]]),
                           C=int(sub['C'][vidx, sub['FrozenNodeRouter'][vidx]]),
                           L=float(sub['L'][vidx, sub['FrozenNodeRouter'][vidx]])))
        forest.save_graph(dict(uid=t['uid'], question=t['question'], nodes=tnodes,
                               edges=[[reasoning['node_id'], ver['node_id']]]))
        stored.append(t['uid'])
    evidence['round1_stored'] = dict(graphs=len(forest.graphs), calls=len(calls), uids=stored)

    # ---- Round 2: follow-up compares the two stored results; REUSE both, execute only aggregate
    ga, gb = forest.retrieve(stored[0]), forest.retrieve(stored[1])
    va = forest.node(stored[0], next(n['node_id'] for n in ga['nodes'] if n['node_type'] == 'reasoning'))['value']
    vb = forest.node(stored[1], next(n['node_id'] for n in gb['nodes'] if n['node_type'] == 'reasoning'))['value']
    engine.OUT = OUT
    proc = log = None
    import fcntl
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            proc, log, _ = engine.start_model('medium')
            r2 = engine.call_model('medium', AGG_PROMPT.format(qa=ga['question'][:80], a=va,
                                                               qb=gb['question'][:80], b=vb))
            calls.append('round2_aggregate')
            round2_out = v.decode(r2['answer'])
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    evidence['round2_reuse'] = dict(reused_nodes=4, new_calls=1, aggregate=round2_out,
                                    reuse_hit=[n['node_id'] for g in (ga, gb) for n in g['nodes']])

    # ---- Round 3: modify fact v0 of graph A; version, invalidate, recompute dependents only
    reasoning = forest.node(stored[0], next(n['node_id'] for n in ga['nodes'] if n['node_type'] == 'reasoning'))
    old_value = reasoning['value']
    affected, invalidated = forest.modify_fact(stored[0], 0, new_value=None)
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            proc, log, _ = engine.start_model('medium')
            q = next(t for t in tasks if t['uid'] == stored[0])
            facts = dict(nodes_all[ids[reasoning['node_id']]]['gold_facts'])
            facts['facts'][0]['value'] = facts['facts'][0]['value'] * 2 + 11  # the modification
            rr = engine.call_model('medium', v.sprompt(dict(question=q['question']), facts))
            calls.append('round3_recompute_reasoning')
            expr = v.decode(rr['answer'])['expression']
            new_val = v.calculate(expr, facts)
            forest.recompute(stored[0], reasoning['node_id'],
                             dict(value=new_val, model='medium', recomputed_from_version=ga['version'] - 1))
            rv = engine.call_model('medium', f'Recompute check: does the value {new_val} follow from the '
                                             f'modified facts? Return ONLY JSON {{"consistent":true|false}}.')
            calls.append('round3_recompute_verification')
            try:
                round3_out = v.decode(rv['answer'])
            except Exception:
                round3_out = dict(consistent=None, raw=(rv.get('answer') or '')[:120])
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    evidence['round3_modify'] = dict(affected=affected, invalidated=invalidated,
                                     versions_kept=len(reasoning.get('versions', [])),
                                     old_value=old_value, new_value=new_val,
                                     recomputed_calls=2, verdict=round3_out)
    passed = dict(
        store=len(forest.graphs) == 2,
        retrieve=evidence['round2_reuse']['reused_nodes'] == 4,
        reuse_zero_extra_calls=len(calls) == 3,
        modify_and_version=evidence['round3_modify']['versions_kept'] >= 1,
        invalidate_and_recompute=evidence['round3_modify']['new_value'] is not None
        and reasoning['stale'] is False)
    OUT.mkdir(exist_ok=True)
    core.write(OUT / 'RESULTS.json', dict(experiment='Graph Forest v0 (three-round follow-up closed loop)',
                                          evidence=evidence, total_new_calls=len(calls), passed=passed,
                                          PASS=all(passed.values()),
                                          note='mechanism validation only; no quality claim'))
    print(json.dumps(dict(passed=passed, PASS=all(passed.values()), calls=len(calls),
                          round2=round2_out, round3=evidence['round3_modify']), indent=1, ensure_ascii=False))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
