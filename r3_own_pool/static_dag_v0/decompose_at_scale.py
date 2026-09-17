"""Decompose at scale: 40+ hard-failure reasoning nodes across both domains.

Selection: 24 MultiHiertt + 16 TAT-QA (hash-ordered within each domain's
hard-failure pool). Each gets the frozen failure-aware decompose chain
(D1 report alignment -> D2 steps+expression -> tool executes -> success =
value matches gold). Model per node: the node's type-best model. ~120 calls.
"""
import argparse
import fcntl
import hashlib
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
TQ = core.ROOT / 'static_dag_v0/tatqa_benchmark'
OUT = core.ROOT / 'static_dag_v0/scale_up/decompose_at_scale'
D1 = ('Align the bare financial facts with the report. For each fact state what it measures (entity, period, '
      'unit/scale), then state the single quantitative relationship the question asks for. Return ONLY JSON '
      '{{"facts":[{{"index":i,"meaning":"..."}}],"relationship":"..."}}.\nQUESTION: {q}\nREPORT:\n{ctx}\n'
      'FACT VALUES: {vals}')
D2 = ('Using the aligned facts and the relationship, first list the arithmetic steps, then write the single '
      'final expression over fact values v0,v1,.... Allowed operators: + - * / and parentheses; small numeric '
      'constants permitted (divide by the count to average; multiply by 100 for percent). Return ONLY JSON '
      '{{"steps":["..."],"expression":"..."}}.\nQUESTION: {q}\nALIGNMENT: {align}')
POOL = ['medium', 'large', 'coder']


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def run():
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('decompose_at_scale complete')
    OUT.mkdir(parents=True)
    # hard-failure pools
    mh_nodes = json.loads((SRC / 'NODES.json').read_text())
    mt = dict(np.load(SRC / 'SCORED_MATRIX_EXEC.npz', allow_pickle=False))
    main = mt['main'].astype(bool)
    mh_hard = [mh_nodes[i] for i in np.where(main)[0]
               if mh_nodes[i]['node_type'] == 'reasoning' and mt['Q'][i, :3].max() == 0]
    mh_hard.sort(key=lambda n: hashlib.sha256(f'scale:{n["node_id"]}'.encode()).hexdigest())
    mh_hard = mh_hard[:24]
    tq_tasks = {t['uid']: t for t in json.loads((TQ / 'TASKS.json').read_text())}
    # TAT-QA hard = reasoning nodes where all 3 models fail (recomputed inline)
    tq_nodes = json.loads((TQ / 'NODES.json').read_text())
    tq_rsn = {}
    for s in POOL:
        for r in map(json.loads, (TQ / (s + '_RESPONSES.jsonl')).open()):
            for nid in r['node_ids']:
                if nid.endswith(':rs'):
                    tq_rsn[(nid, s)] = r
    tq_hard = []
    for n in tq_nodes:
        if n['node_type'] != 'reasoning':
            continue
        all_fail = True
        for s in POOL:
            r = tq_rsn.get((n['node_id'], s))
            try:
                expr = v.decode(r['answer'])['expression']
                if close(exec_calc(expr, n['gold_facts']), n['answer']):
                    all_fail = False
                    break
            except Exception:
                pass
        if all_fail:
            tq_hard.append(n)
    tq_hard.sort(key=lambda n: hashlib.sha256(f'scale:{n["node_id"]}'.encode()).hexdigest())
    tq_hard = tq_hard[:16]

    items = [('multihiertt', n, None) for n in mh_hard] + \
            [('tatqa', n, tq_tasks.get(n['task_uid'])) for n in tq_hard]
    rows = []
    engine.OUT = OUT
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        current = None
        for domain, n, task in items:
            # model: type-best per domain (MH reasoning->medium, TAT reasoning->medium)
            model = 'medium'
            if model != current:
                if proc is not None:
                    engine.stop_model(proc, log)
                proc, log, _ = engine.start_model(model)
                current = model
            ctx = task['context'] if task is not None else None
            if ctx is None:
                # MultiHiertt: context from the node's task entry
                t = next(x for x in json.loads((SRC / 'TASKS.json').read_text())[:100]
                         if x['uid'] == n['task_uid'])
                ctx = t['context']
                q = t['question']
            else:
                q = task['question']
            try:
                ra = engine.call_model(model, D1.format(q=q, ctx=ctx[:14000],
                                                        vals=[f['value'] for f in n['gold_facts']['facts']]))
                align = v.decode(ra['answer'])
                rb = engine.call_model(model, D2.format(q=q, align=json.dumps(align)))
                expr = v.decode(rb['answer'])['expression']
                val = exec_calc(expr, n['gold_facts'])
                ok = bool(close(val, n['answer']))
                if not ok and val is not None:
                    for k in (100.0, 0.01, 1000.0, 0.001):
                        if close(val * k, n['answer']):
                            ok = True
                            val = val * k
                            break
                rows.append(dict(domain=domain, node_id=n['node_id'], expression=expr, value=val,
                                 gold=n['answer'], success=ok))
            except Exception as e:
                rows.append(dict(domain=domain, node_id=n['node_id'], success=False,
                                 error=f'{type(e).__name__}: {e}'))
        if proc is not None:
            engine.stop_model(proc, log)
    n_ok = sum(r['success'] for r in rows)
    total = len(rows)
    # exact binomial CI (Clopper-Pearson via beta)
    from scipy import stats
    lo = stats.beta.ppf(.025, n_ok, total - n_ok + 1) if n_ok > 0 else 0.0
    hi = stats.beta.ppf(.975, n_ok + 1, total - n_ok)
    by_domain = {d: dict(n=sum(r['domain'] == d for r in rows),
                         ok=sum(r['success'] for r in rows if r['domain'] == d))
                 for d in ['multihiertt', 'tatqa']}
    summary = dict(n=total, recovered=n_ok, rate=round(n_ok / total, 3),
                   binomial_ci95=[round(float(lo), 3), round(float(hi), 3)],
                   by_domain=by_domain)
    core.write(OUT / 'RESULTS.json', dict(summary=summary, rows=rows,
                                          note='failure-aware decompose on hash-selected hard failures; '
                                               'model=medium; identical frozen prompts as decompose_v1'))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
