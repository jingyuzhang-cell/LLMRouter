"""Decomposition benchmark runner: three frozen arms in one unified session.

Mono-L (large) | DAG-L/L (large ext -> large rsn -> exec) | DAG-L/M (large ext -> medium rsn -> exec).
No gold anywhere, no retries: extraction parse failure => both DAG arms fail, reasoning not called.
Runs grouped by model: large (mono -> ext -> rsnL), then medium (rsnM). Keyed ledger, resumable.
Refuses to start while the GPU is busy (engine guard), so it can never interrupt another job.
"""
import argparse
import fcntl
import json
import time

from . import core
from . import run as engine
from . import tool_aware_v1 as v

ROOT = core.ROOT / 'static_dag_v0'
FSC = ROOT / 'fresh_static_confirmation'
TQB = ROOT / 'tatqa_benchmark'
SU = ROOT / 'scale_up'
OUT = ROOT / 'decomposition_benchmark' / 'paired_run'

MONO = ('Answer the financial question using the report. Think as needed, then give ONLY the final numeric '
        'answer on the last line in the format: Answer: <number>\nQUESTION: {q}\nREPORT:\n{ctx}')


def load_tasks():
    mh_freeze = json.loads((ROOT / 'decomposition_benchmark' / 'decomposition_final_multihiertt_100.json').read_text())
    tq_freeze = json.loads((ROOT / 'decomposition_benchmark' / 'decomposition_final_tatqa_200.json').read_text())
    mh = {t['uid']: t for t in json.loads((FSC / 'TASKS.json').read_text())}
    tq = {t['uid']: t for t in json.loads((TQB / 'TASKS.json').read_text())}
    tq.update({t['uid']: t for t in json.loads((SU / 'TQ_TASKS.json').read_text())})
    tasks = []
    for e in mh_freeze:
        t = mh[e['task_id']]
        tasks.append(dict(dom='mh', uid=t['uid'], question=t['question'], context=t['context'], answer=t['answer']))
    for e in tq_freeze:
        t = tq[e['task_id']]
        tasks.append(dict(dom='tq', uid=t['uid'], question=t['question'], context=t['context'], answer=t['answer']))
    assert len(tasks) == 300, len(tasks)
    return tasks


def led(rows, path):
    with path.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
        f.flush()


def done_keys(path):
    if not path.exists():
        return set()
    return {json.loads(l)['key'] for l in path.open()}


def call(slot, key, prompt, meta, req_path, resp_path, have):
    if key in have:
        return None
    r = engine.call_model(slot, prompt)
    row = dict(key=key, model=slot, **meta, prompt=prompt, **r)
    led([row], resp_path)
    led([dict(key=key, model=slot, unix_time=time.time())], req_path)
    return row


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT
    resp = OUT / 'RESPONSES.jsonl'
    req = OUT / 'REQUESTS.jsonl'
    have = done_keys(resp)
    tasks = load_tasks()
    if (OUT / 'ALL_DONE').exists():
        raise FileExistsError('paired run already complete')
    core.write(OUT / 'STATUS.json', dict(phase='STARTING', n_tasks=len(tasks), cached=len(have), unix_time=time.time()))
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            proc, log, _ = engine.start_model('large')
            # ---- large: mono -> extraction -> DAG-L/L reasoning ----
            for t in tasks:
                call('large', f'{t["dom"]}:{t["uid"]}:mono',
                     MONO.format(q=t['question'], ctx=t['context'][:14000]),
                     dict(arm='Mono-L', dom=t['dom'], uid=t['uid']), req, resp, have)
            for t in tasks:
                call('large', f'{t["dom"]}:{t["uid"]}:ext',
                     v.eprompt(dict(question=t['question'], context=t['context'])),
                     dict(arm='DAG-extraction', dom=t['dom'], uid=t['uid']), req, resp, have)
            facts_by_uid = {}
            resp_rows = {json.loads(l)['key']: json.loads(l) for l in resp.open()}
            for t in tasks:
                ext = resp_rows.get(f'{t["dom"]}:{t["uid"]}:ext')
                facts = None
                if ext and ext.get('status') == 'delivered':
                    try:
                        facts = v.parse_facts(ext['answer'])
                    except Exception:
                        facts = None
                facts_by_uid[(t['dom'], t['uid'])] = facts
                if facts is None:
                    led([dict(key=f'{t["dom"]}:{t["uid"]}:rsnL', model='large', arm='DAG-L/L',
                              dom=t['dom'], uid=t['uid'], status='skipped_parse_failure', answer=None, usage=None)],
                        resp)
            for t in tasks:
                facts = facts_by_uid[(t['dom'], t['uid'])]
                if facts is None:
                    continue
                call('large', f'{t["dom"]}:{t["uid"]}:rsnL',
                     v.sprompt(dict(question=t['question']), facts),
                     dict(arm='DAG-L/L', dom=t['dom'], uid=t['uid'], facts_used=facts), req, resp, have)
            engine.stop_model(proc, log)
            proc = log = None
            # ---- medium: DAG-L/M reasoning (same facts) ----
            proc, log, _ = engine.start_model('medium')
            for t in tasks:
                facts = facts_by_uid[(t['dom'], t['uid'])]
                if facts is None:
                    led([dict(key=f'{t["dom"]}:{t["uid"]}:rsnM', model='medium', arm='DAG-L/M',
                              dom=t['dom'], uid=t['uid'], status='skipped_parse_failure', answer=None, usage=None)],
                        resp)
                    continue
                call('medium', f'{t["dom"]}:{t["uid"]}:rsnM',
                     v.sprompt(dict(question=t['question']), facts),
                     dict(arm='DAG-L/M', dom=t['dom'], uid=t['uid'], facts_used=facts), req, resp, have)
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    rows = [json.loads(l) for l in resp.open()]
    skips = sum(1 for r in rows if r.get('status') == 'skipped_parse_failure')
    core.write(OUT / 'ALL_DONE', dict(unix_time=time.time(), n_rows=len(rows), parse_failure_skips=skips))
    print(json.dumps(dict(rows=len(rows), parse_failure_skips=skips)))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
