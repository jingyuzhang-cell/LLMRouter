"""Collect TAT-QA benchmark: 3 models on every node (reuses frozen prompts)."""
import argparse
import fcntl
import json
import time

from . import core
from . import run as engine
from . import tool_aware_v1 as v

OUT = core.ROOT / 'static_dag_v0/tatqa_benchmark'
SLOTS = ['medium', 'large', 'coder']
V0 = ('Check this financial computation. QUESTION: {q}\nFACTS: {facts}\nEXPRESSION: {expr}\nVALUE: {val}\n'
      'Does it correctly answer the question using accurate facts? '
      'Answer ONLY JSON {{"verdict":"yes"|"no"}}.')


def run():
    if (OUT / 'ALL_DONE').exists():
        raise FileExistsError('tatqa collection complete')
    nodes = json.loads((OUT / 'NODES.json').read_text())
    tasks = {t['uid']: t for t in json.loads((OUT / 'TASKS.json').read_text())}
    calls = {}
    for n in nodes:
        t = tasks[n['task_uid']]
        if n['node_type'] == 'extraction':
            key = n['shares_model_call']
            calls.setdefault(key, dict(call_key=key, task_uid=n['task_uid'], node_type='extraction',
                                       node_ids=[], prompt=v.eprompt(dict(question=t['question'], context=t['context']))))
            calls[key]['node_ids'].append(n['node_id'])
        elif n['node_type'] == 'reasoning':
            calls[n['node_id']] = dict(call_key=n['node_id'], task_uid=n['task_uid'], node_type='reasoning',
                                       node_ids=[n['node_id']],
                                       prompt=v.sprompt(dict(question=t['question']), n['gold_facts']))
        else:
            val = None
            try:
                expr = n['gold_expr']
                for i, f in enumerate(n['gold_facts']['facts']):
                    expr = expr.replace(f'v{i}', str(f['value']))
                val = eval(expr, {'__builtins__': {}}, {})
            except Exception:
                val = None
            calls[n['node_id']] = dict(call_key=n['node_id'], task_uid=n['task_uid'], node_type='verification',
                                       node_ids=[n['node_id']],
                                       prompt=V0.format(q=t['question'], facts=json.dumps(n['gold_facts']),
                                                        expr=n['gold_expr'], val=val), gold_value=val)
    jobs = list(calls.values())
    core.write(OUT / 'CALLS.json', jobs)
    engine.OUT = OUT
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for slot in SLOTS:
            done = OUT / (slot + '_RESPONSES.jsonl')
            if done.exists():
                continue
            ledger = OUT / (slot + '_REQUESTS.jsonl')
            proc = log = None
            start = time.time()
            try:
                proc, log, _ = engine.start_model(slot)
                with ledger.open('a') as intents, done.open('a') as out:
                    for c in jobs:
                        intents.write(json.dumps(dict(call_key=c['call_key'], model=slot,
                                                      prompt=c['prompt'], unix_time=time.time()),
                                                 ensure_ascii=False) + '\n')
                        r = engine.call_model(slot, c['prompt'])
                        out.write(json.dumps(dict(**r, call_key=c['call_key'], task_uid=c['task_uid'],
                                                  node_type=c['node_type'], node_ids=c['node_ids'], model=slot,
                                                  gold_value=c.get('gold_value')),
                                             ensure_ascii=False) + '\n')
                core.write(OUT / (slot + '_STATUS.json'), dict(phase='COMPLETE', records=len(jobs),
                                                               total_seconds=time.time() - start))
                print(slot, 'complete', len(jobs))
            finally:
                if proc is not None:
                    engine.stop_model(proc, log)
    (OUT / 'ALL_DONE').write_text(json.dumps(dict(unix_time=time.time(), models=SLOTS, calls_per_model=len(jobs))))
    print('ALL DONE', len(jobs) * len(SLOTS), 'calls')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
