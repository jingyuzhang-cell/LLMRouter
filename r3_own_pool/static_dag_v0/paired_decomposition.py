"""Strictly paired decomposition benchmark on the frozen conf-200 panel.

Fixes the evidence hole flagged by the claim audit: the historical Mono-vs-DAG
comparisons (MH +14.0pp / TAT-QA -9.38pp) mixed input conditions and contained
gold-fact fallbacks in some collections, so they cannot support a clean
"does decomposition help" claim.

Arms (all strictly paired: same 200 frozen tasks, same full contexts, same
generation config; extraction failure => task fails, no retry, no gold):
  Mono-L   : single large model answers directly from the full report
             (frozen MONO prompt byte-identical to scale_up_collect).
  DAG-L/L  : extraction(large, full ctx) -> reasoning(large)   [frozen cells
             E_large->R_large of the cross-model matrix]
  DAG-L/M  : extraction(large, full ctx) -> reasoning(medium)  [E_large->R_medium]

Pre-registered contrasts:
  C1  Mono-L vs DAG-L/L      : does decomposition itself add value?
  C2  DAG-L/L vs DAG-L/M     : does heterogeneous stage allocation add value?
Strata: derivation op count, frozen as 2 ops / 3-4 ops / 5+ ops.
One-shot; no prompt, model, or threshold may change after results are seen.
"""
import fcntl
import hashlib
import json
import os
import re
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .confirmation_200 import OUT as CONF1
from .cross_model_matrix import OUT as CM

OUT = core.ROOT / 'static_dag_v0/paired_decomposition_200'
MONO = ('Answer the financial question using the report. Think as needed, then give ONLY the final numeric '
        'answer on the last line in the format: Answer: <number>\nQUESTION: {q}\nREPORT:\n{ctx}')


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def extract_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '') or \
        re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except Exception:
        return None


def n_ops(program):
    return len(re.findall(r'(?:add|subtract|multiply|divide)\(', program or ''))


def stratum(k):
    return '2ops' if k <= 2 else ('3-4ops' if k <= 4 else '5+ops')


def freeze():
    pol = json.loads((CONF1 / 'CONF_POLICY.json').read_text())
    tasks = pol['tasks']
    policy = dict(
        role='paired_decomposition_benchmark_one_shot',
        n_tasks=len(tasks),
        arms=dict(
            mono_L='single large model, frozen MONO prompt (scale_up_collect byte-identical), full report context',
            dag_L_L='extraction(large)->reasoning(large); frozen cross-model cells; extraction failure => task fails',
            dag_L_M='extraction(large)->reasoning(medium); frozen cross-model cells; extraction failure => task fails'),
        contrasts=dict(C1='Mono-L vs DAG-L/L (decomposition value)', C2='DAG-L/L vs DAG-L/M (heterogeneous allocation value)'),
        strata='derivation op count: 2ops / 3-4ops / 5+ops',
        scoring='mono: extract_value close to gold; dag: exec_calc(expression, parse_facts(ext)) close to gold; identical close tolerance',
        generation='temperature 0, top_p 1, max_tokens 512',
        one_shot=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'PD_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, n=len(tasks))))


def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())


def run():
    if not (OUT / 'PD_POLICY.json').exists():
        freeze()
    pol = json.loads((CONF1 / 'CONF_POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'DONE.json').exists(): raise FileExistsError('paired decomposition complete')
    engine.OUT = OUT
    lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cache = {}
    if (OUT / 'RESPONSES.jsonl').exists():
        for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l); cache[r['key']] = r
    proc = logm = None
    t0 = time.time()
    try:
        for t in tasks:
            k = f'MONO:large:{t["uid"]}'
            if k in cache: continue
            if proc is None:
                proc, logm, _ = engine.start_model('large')
            append(OUT / 'REQUESTS.jsonl', dict(key=k, model='large',
                   prompt=MONO.format(q=t['question'], ctx=t['context'])))
            resp = engine.call_model('large', MONO.format(q=t['question'], ctx=t['context']))
            if resp.get('status') != 'delivered':
                resp = engine.call_model('large', MONO.format(q=t['question'], ctx=t['context']))
            append(OUT / 'RESPONSES.jsonl', dict(key=k, model='large', response=resp))
            cache[k] = dict(key=k, model='large', response=resp)
        core.write(OUT / 'DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(cache)))
        print(json.dumps(dict(done=True, calls=len(cache))))
    finally:
        if proc is not None: engine.stop_model(proc, logm)
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()


if __name__ == '__main__':
    run()
