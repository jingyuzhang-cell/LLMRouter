"""End-to-End demo: one complex task + two follow-ups through the whole chain.

Round 1 (Static->Feedback->Dynamic): task A's DAG executes from the frozen
fresh table with the router-top model; ONE REAL failure is preserved ->
feedback memory updates -> diagnosis -> single second-best reroute (deployable
policy) -> descendant invalidated & recomputed. Round 2 (Graph Forest): follow-
up 'analyze B and compare with A' -> retrieve+reuse A and B subgraphs (ZERO new
calls) -> tool-executed comparison (no LLM arithmetic). Round 3: 'A metric +10%'
-> version v1 kept -> invalidate -> recompute affected reasoning + verification
(2 real calls). Finally: Pareto over the demo-workload plans -> best plan ->
final answers.
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/end_to_end_demo'
POOL = ['medium', 'large', 'coder']
ALPHA_C, ALPHA_L = 0.05 / 1000.0, 0.05 / 10.0


def utility_row(dev, n, emb, qmap):
    types = [1.0 if n['node_type'] == t else 0.0
             for t in ['extraction', 'transformation', 'reasoning', 'verification']]
    x = np.hstack([emb['emb'][qmap[n['question']]], types, np.log1p(len(n['question']))]).reshape(1, -1)
    return x @ dev['NodeRouter_coef'].T + dev['NodeRouter_intercept'] - \
        ALPHA_C * dev['mean_C'] - ALPHA_L * dev['mean_L']


def run():
    if OUT.exists():
        raise FileExistsError('end_to_end_demo already exists')
    OUT.mkdir()
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    matrix = dict(np.load(SRC / 'SCORED_MATRIX.npz', allow_pickle=False))
    dev = np.load(SRC / 'DEV_MODELS.npz', allow_pickle=False)
    emb = np.load(SRC / 'QUESTION_EMBEDDINGS.npz', allow_pickle=False)
    qmap = {q: i for i, q in enumerate(emb['questions'].tolist())}
    tasks = {t['uid']: t for t in json.loads((SRC / 'TASKS.json').read_text())}
    idx = {n['node_id']: i for i, n in enumerate(nodes_all)}
    by_task = {}
    for n in nodes_all:
        if matrix['main'][idx[n['node_id']]]:
            by_task.setdefault(n['task_uid'], []).append(n)
    # Task A: reasoning fails on router-top, succeeds on second-best; extraction ok; has vfpos
    taskA = taskB = None
    for uid, ns in by_task.items():
        r = next((n for n in ns if n['node_type'] == 'reasoning'), None)
        if not r:
            continue
        u = utility_row(dev, r, emb, qmap)[0]
        order = list(np.argsort(-u))
        i = idx[r['node_id']]
        if matrix['Q'][i, order[0]] == 0 and matrix['Q'][i, order[1]] > 0 and \
                any(n['node_type'] == 'extraction' for n in ns):
            taskA = (uid, ns, r, order)
            break
    for uid, ns in by_task.items():
        if uid == taskA[0]:
            continue
        r = next((n for n in ns if n['node_type'] == 'reasoning'), None)
        if r and matrix['Q'][idx[r['node_id']], int(np.argmax(utility_row(dev, r, emb, qmap)[0]))] > 0:
            taskB = (uid, ns, r)
            break
    log = dict(taskA=taskA[0], taskB=taskB[0])
    calls = 0

    # ---- Round 1: static execution + feedback + dynamic reroute (table replay)
    uid, ns, reasoning, order = taskA
    top, second = int(order[0]), int(order[1])
    ri = idx[reasoning['node_id']]
    steps = []
    ext_nodes = [n for n in ns if n['node_type'] == 'extraction']
    ext_q = [float(matrix['Q'][idx[n['node_id']], top]) for n in ext_nodes]
    steps.append(dict(stage='static_execution', nodes=[n['node_id'] for n in ext_nodes] + [reasoning['node_id']],
                      model=POOL[top], extraction_Q=ext_q,
                      reasoning_Q=float(matrix['Q'][ri, top]), status='FAILED (real failure preserved)'))
    steps.append(dict(stage='feedback_memory_update', entry=dict(node_type='reasoning', model=POOL[top],
                                                                 actual_q=0.0)))
    steps.append(dict(stage='diagnosis', verdict='model-recoverable', policy='single second-best reroute'))
    q2 = float(matrix['Q'][ri, second])
    steps.append(dict(stage='reroute', model=POOL[second], reasoning_Q=q2, status='RECOVERED' if q2 > 0 else 'failed'))
    vf = next((n for n in ns if n['node_id'].endswith('vfpos')), None)
    if vf:
        vi = idx[vf['node_id']]
        steps.append(dict(stage='invalidate+recompute', node=vf['node_id'], old_stale=True,
                          recomputed_Q=float(matrix['Q'][vi, second])))
    log['round1'] = dict(steps=steps, final_answer=tasks[uid]['answer'],
                         calls=0, note='executions read from frozen table (replay)')

    # ---- Round 2: graph forest reuse + TOOL comparison (zero LLM calls)
    bi = idx[taskB[2]['node_id']]
    b_top = int(np.argmax(utility_row(dev, taskB[2], emb, qmap)[0]))
    a_val, b_val = tasks[taskA[0]]['answer'], tasks[taskB[0]]['answer']
    comparison = dict(a=a_val, b=b_val, larger='a' if a_val >= b_val else 'b',
                      difference=abs(a_val - b_val), executed_by='TOOL (deterministic)')
    log['round2'] = dict(reused=[n['node_id'] for n in taskA[1]] + [taskB[2]['node_id']],
                         reused_new_calls=0, tool_comparison=comparison)

    # ---- Round 3: modify fact +10% -> version -> recompute (2 real calls)
    engine.OUT = OUT
    facts = dict(reasoning['gold_facts'])
    facts['facts'][0]['value'] = facts['facts'][0]['value'] * 1.10
    import fcntl
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log_ = None
        try:
            proc, log_, _ = engine.start_model(POOL[second])
            rr = engine.call_model(POOL[second], v.sprompt(dict(question=tasks[uid]['question']), facts))
            calls += 1
            expr = v.decode(rr['answer'])['expression']
            new_val = v.calculate(expr, facts)
            rv = engine.call_model(POOL[second], f'Verify: question "{tasks[uid]["question"][:120]}", computed '
                                                 f'value {new_val} from modified facts. Correct? '
                                                 f'Return ONLY JSON {{"accept":true|false}}.')
            calls += 1
            try:
                verdict = v.decode(rv['answer'])
            except Exception:
                verdict = dict(accept=None, raw=(rv.get('answer') or '')[:80])
        finally:
            if proc is not None:
                engine.stop_model(proc, log_)
    log['round3'] = dict(versions=dict(v1_value=tasks[uid]['answer'], v2_value=new_val, v1_kept=True),
                         invalidated=['verification'], recomputed_calls=2, verdict=verdict,
                         forest_contents=['A_original(v1)', f'A_modified(v2)={new_val}', 'B', 'A_vs_B'])

    # ---- Pareto over demo-workload plans
    def plan_metrics(picks, executed_counts):
        Q = [float(matrix['Q'][idx[n['node_id']], p]) for n, p in picks]
        C = [float(matrix['C'][idx[n['node_id']], p]) * c for (n, p), c in zip(picks, executed_counts)]
        L = [float(matrix['L'][idx[n['node_id']], _p]) * c for (n, _p), c in zip(picks, executed_counts)]
        return dict(Q=float(np.mean(Q)), C=float(np.sum(C)), L=float(np.sum(L)))
    demo_nodes = ext_nodes + [reasoning] + ([vf] if vf else []) + [taskB[2]]
    plans = {
        'Static(top model)': plan_metrics([(n, top) for n in demo_nodes], [1] * len(demo_nodes)),
        'Dynamic-Reroute': plan_metrics([(n, second if n is reasoning else top) for n in demo_nodes],
                                        [2 if n is reasoning else 1 for n in demo_nodes]),
        'Graph-Reuse': plan_metrics([(n, second if n is reasoning else top) for n in demo_nodes],
                                    [0 if n in taskA[1] or n is taskB[2] else 1 for n in demo_nodes]),
        'Oracle(non-deployable)': plan_metrics([(n, int(np.argmax(matrix['Q'][idx[n['node_id']]])))
                                                for n in demo_nodes], [1] * len(demo_nodes)),
    }
    def pareto(d):
        vec = {k: (v['Q'], -v['C'], -v['L']) for k, v in d.items()}
        def dom(a, b):
            return all(x >= y - 1e-12 for x, y in zip(a, b)) and any(x > y + 1e-12 for x, y in zip(a, b))
        return sorted(k for k in d if not any(dom(vec[j], vec[k]) for j in d if j != k))
    deployable = {k: v for k, v in plans.items() if 'Oracle' not in k}
    frontier = pareto(deployable)
    best = max(deployable, key=lambda k: deployable[k]['Q'] - ALPHA_C * deployable[k]['C'])
    log['pareto'] = dict(plans=plans, demo_frontier=frontier, selected=best)
    core.write(OUT / 'DEMO_RESULTS.json', dict(log=log, real_calls=calls,
                                               chain='Task->Decomposition->NodeRouter->Static->Execution->'
                                                     'Feedback->Dynamic(Reroute)->GraphForest(Reuse/Tool/Version)->'
                                                     'Pareto->FinalAnswer'))
    print(json.dumps(dict(taskA=log['taskA'][:12], round1_status=steps[3]['status'],
                          round2_zero_calls=log['round2']['reused_new_calls'],
                          round3=dict(v1=tasks[uid]['answer'], v2=new_val, verdict=verdict),
                          pareto_selected=best, real_calls=calls), indent=1, ensure_ascii=False))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
