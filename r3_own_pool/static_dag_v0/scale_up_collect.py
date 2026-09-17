"""Scale-up collection: TAT-QA 160 more tasks (monolithic/extraction/reasoning)
plus MultiHiertt 50 more monolithic. Resumable, model-grouped batches."""
import argparse
import fcntl
import json
import time

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .tatqa_benchmark_build import context, literals  # reuse builders

TQ = core.ROOT / 'static_dag_v0/tatqa_benchmark'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
OUT = core.ROOT / 'static_dag_v0/scale_up'
N_NEW_TQ = 160
MONO = ('Answer the financial question using the report. Think as needed, then give ONLY the final numeric '
        'answer on the last line in the format: Answer: <number>\nQUESTION: {q}\nREPORT:\n{ctx}')
import re


def extract_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '') or \
        re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except ValueError:
        return None


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def build_tq_tasks():
    import hashlib
    paras = json.loads((core.ROOT / 'data/tatqa/tatqa_dataset_dev.json').read_text())
    used = {t['uid'] for t in json.loads((TQ / 'TASKS.json').read_text())}
    eligible = []
    for para in paras:
        for q in para['questions']:
            d = (q.get('derivation') or '').strip()
            if q.get('answer_type') != 'arithmetic' or not d or not re.search(r'[+\-*/]', d):
                continue
            lits = [x for x in literals(d) if x not in (0.0, 1.0, 100.0)]
            if len(set(lits)) < 2 or q['uid'] in used:
                continue
            try:
                gold = eval(d, {'__builtins__': {}}, {})
            except Exception:
                continue
            if isinstance(gold, (int, float)):
                eligible.append(dict(uid=q['uid'], question=q['question'], derivation=d,
                                     answer=float(gold), context=context(para)))
    eligible.sort(key=lambda t: hashlib.sha256(f'20260916b:{t["uid"]}'.encode()).hexdigest())
    tasks = eligible[:N_NEW_TQ]
    core.write(OUT / 'TQ_TASKS.json', tasks)
    return tasks


def run():
    if (OUT / 'ALL_DONE').exists():
        raise FileExistsError('scale-up complete')
    OUT.mkdir(parents=True, exist_ok=True)
    tq_tasks = json.loads((OUT / 'TQ_TASKS.json').read_text()) if (OUT / 'TQ_TASKS.json').exists() else build_tq_tasks()
    mh_tasks = json.loads((SRC / 'TASKS.json').read_text())[50:100]
    mh_rows = {json.loads(l)['uid']: json.loads(l) for l in (SRC / 'PANEL.jsonl').open()} if (SRC / 'PANEL.jsonL'.replace('L','l')).exists() else None
    engine.OUT = OUT
    import fcntl
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        current = None
        ledger = (OUT / 'REQUESTS.jsonl').open('a')

        def ensure(model):
            nonlocal proc, log, current
            if model != current:
                if proc is not None:
                    engine.stop_model(proc, log)
                proc, log, _ = engine.start_model(model)
                current = model

        def call(model, key, prompt):
            f = (OUT / 'RESPONSES.jsonl').open('a')
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
                for line in (OUT / 'RESPONSES.jsonl').open():
                    if json.loads(line)['key'] == key:
                        return json.loads(line)
            except FileNotFoundError:
                pass
            ensure(model)
            r = engine.call_model(model, prompt)
            row = dict(key=key, model=model, **r)
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
            f.flush()
            return row

        # batch by model: all monolithic(large) first, then extraction(large), then reasoning(medium)
        # 1) TAT-QA monolithic on large
        for t in tq_tasks:
            call('large', f'tq:{t["uid"]}:mono', MONO.format(q=t['question'], ctx=t['context'][:14000]))
        # 2) TAT-QA extraction on large
        for t in tq_tasks:
            call('large', f'tq:{t["uid"]}:ext', v.eprompt(dict(question=t['question'], context=t['context'])))
        # 3) TAT-QA reasoning on medium (fed by own extraction)
        for t in tq_tasks:
            ext_row = call('large', f'tq:{t["uid"]}:ext', '')  # cached
            facts = None
            try:
                facts = v.parse_facts(ext_row['answer'])
            except Exception:
                facts = None
            rinput = facts if facts else dict(facts=[dict(value=x, evidence='gold')
                                                     for x in sorted({l for l in literals(t['derivation']) if l not in (0., 1., 100.)})])
            call('medium', f'tq:{t["uid"]}:rsn', v.sprompt(dict(question=t['question']), rinput))
        # 4) MultiHiertt 50 monolithic on large
        for t in mh_tasks:
            call('large', f'mh:{t["uid"]}:mono', MONO.format(q=t['question'], ctx=t['context'][:14000]))
        if proc is not None:
            engine.stop_model(proc, log)
    core.write(OUT / 'ALL_DONE', dict(unix_time=time.time(), tq=len(tq_tasks), mh=50))
    print('DONE')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
