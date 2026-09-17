"""Live single-model baselines: Always Large / Always Medium on the same 50 tasks.

Same live chain as live_e2e (extraction -> reasoning, real calls, no verifier,
no feedback): one fixed model executes every node. Shares the live_e2e call
cache, so cells already executed by the routed arms are not re-billed. Scored
offline against gold answers.
"""
import argparse
import json

import numpy as np

from . import core
from . import run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
LIVE = core.ROOT / 'static_dag_v0/live_e2e'
OUT = LIVE / 'single_model_baselines'
N_TASKS = 50


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


class Runner:
    def __init__(self):
        self.cache = {}
        self.cache_file = LIVE / 'CALL_CACHE.jsonl'
        for line in self.cache_file.open():
            row = json.loads(line)
            k = tuple(row['key'].split('/')) if '/' in row['key'] else row['key']
            self.cache[k] = row['response']
        self.new_file = OUT / 'CALL_CACHE_BASELINES.jsonl'
        self.tokens = {'AlwaysLarge': 0, 'AlwaysMedium': 0}
        self.calls = {'AlwaysLarge': 0, 'AlwaysMedium': 0}
        self.latency = {'AlwaysLarge': 0.0, 'AlwaysMedium': 0.0}
        self.current, self.proc, self.log = None, None, None

    def _ensure(self, model):
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model

    def call(self, model, key, prompt, arm):
        if key in self.cache:
            return self.cache[key]
        self._ensure(model)
        r = engine.call_model(model, prompt)
        self.tokens[arm] += (r.get('usage') or {}).get('total_tokens', 0)
        self.calls[arm] += 1
        self.latency[arm] += r.get('latency_s', 0.0)
        self.cache[key] = r
        with self.new_file.open('a') as f:
            f.write(json.dumps(dict(key='/'.join(map(str, key)), model=model, response=r),
                               ensure_ascii=False) + '\n')
        return r


def run():
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('baselines already complete')
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = json.loads((SRC / 'TASKS.json').read_text())[:N_TASKS]
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    by_task = {}
    for n in nodes_all:
        by_task.setdefault(n['task_uid'], []).append(n)
    runner = Runner()
    import fcntl
    rows = []
    with (core.ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            for arm, model in [('AlwaysLarge', 'large'), ('AlwaysMedium', 'medium')]:
                for t in tasks:
                    ns = by_task[t['uid']]
                    ext = next((n for n in ns if n['node_type'] == 'extraction'), None)
                    r_node = next(n for n in ns if n['node_type'] == 'reasoning')
                    facts = None
                    if ext:
                        r = runner.call(model, (ext['node_id'], model),
                                        v.eprompt(dict(question=t['question'], context=t['context'])), arm)
                        try:
                            facts = v.parse_facts(r['answer'])
                        except Exception:
                            facts = None
                    rinput = facts if facts else r_node['gold_facts']
                    rr = runner.call(model, (r_node['node_id'], model, 'live'),
                                     v.sprompt(dict(question=t['question']), rinput), arm)
                    val = None
                    try:
                        val = exec_calc(v.decode(rr['answer'])['expression'], rinput)
                    except Exception:
                        pass
                    rows.append(dict(arm=arm, task_uid=t['uid'], value=val, gold=t['answer'],
                                     task_success=bool(close(val, t['answer']))))
        finally:
            if runner.proc is not None:
                engine.stop_model(runner.proc, runner.log)
    summary = {}
    for arm in ('AlwaysMedium', 'AlwaysLarge'):
        sub = [r for r in rows if r['arm'] == arm]
        summary[arm] = dict(task_success=float(np.mean([r['task_success'] for r in sub])),
                            tokens=runner.tokens[arm], calls=runner.calls[arm],
                            service_seconds=round(runner.latency[arm], 1))
    core.write(OUT / 'RESULTS.json', dict(summary=summary, n_tasks=N_TASKS,
                                          shared_cache='cells already in live_e2e cache are not re-billed; '
                                                       'fresh calls logged separately'))
    (OUT / 'ROWS.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    print(json.dumps(summary, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
