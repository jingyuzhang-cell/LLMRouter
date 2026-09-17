"""Monolithic no-decomposition baseline: one model, one prompt, direct answer.

Same 50 live-E2E tasks. Single call per task: question + full context, the
model answers directly in the required 'Answer: $LETTER/value' spirit; scored
against gold with the same tolerance. Isolates the execution utility of the
DAG decomposition (template) from model selection and adaptation.
"""
import argparse
import json
import re

from . import core
from . import run as engine
from .decompose_v1 import exec_calc  # noqa: F401 (scoring uses numeric extraction)

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
LIVE = core.ROOT / 'static_dag_v0/live_e2e'
OUT = LIVE / 'monolithic_baseline'
MODEL = 'large'
PROMPT = ('Answer the financial question using the report. Think as needed, then give ONLY the final numeric '
          'answer on the last line in the format: Answer: <number>\nQUESTION: {q}\nREPORT:\n{ctx}')


def extract_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '')
    if not m:
        m = re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except ValueError:
        return None


def run():
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('monolithic baseline complete')
    OUT.mkdir(parents=True)
    tasks = json.loads((SRC / 'TASKS.json').read_text())[:50]
    import fcntl
    rows = []
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            proc, log, _ = engine.start_model(MODEL)
            for t in tasks:
                r = engine.call_model(MODEL, PROMPT.format(q=t['question'], ctx=t['context'][:14000]))
                val = extract_value(r['answer'])
                ok = val is not None and abs(val - t['answer']) <= max(1e-4, 1e-4 * abs(t['answer']))
                rows.append(dict(uid=t['uid'], value=val, gold=t['answer'], success=bool(ok),
                                 tokens=(r.get('usage') or {}).get('total_tokens', 0),
                                 status=r['status']))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    import numpy as np
    summary = dict(n=50, model=MODEL,
                   task_success=float(np.mean([r['success'] for r in rows])),
                   produced_value_rate=float(np.mean([r['value'] is not None for r in rows])),
                   tokens_per_task=float(np.mean([r['tokens'] for r in rows])))
    core.write(OUT / 'RESULTS.json', dict(summary=summary, rows=rows,
                                          note='single prompt, no decomposition, no tools; same scoring as live E2E'))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
