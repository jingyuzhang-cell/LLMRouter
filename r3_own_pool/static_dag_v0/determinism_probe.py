"""Determinism probe (diagnostic, not part of the FG arm).

Measures the session-level nondeterminism rate of each local model by re-running
a fixed sample of prompts already in the base panel cache, in a fresh server
session, with the identical generation parameters (temperature 0, top_p 1,
max_tokens 512). Sampling rule: first 20 tasks in frozen order; one prompt per
node kind per task: e1 (large), r (medium), v (coder).

Motivation: the FG arm's determinism audit found same-prompt answer divergences
concentrated in the 14B GPTQ model. This probe quantifies that rate per model.
"""
import fcntl
import json
import time

from . import core, run as engine
from .multidag_dynamic import OUT, append
from .multidag_fullgraph import FG

PROBE = FG / 'determinism_probe'
N_SAMPLE = 20


class Caller:
    def __init__(self):
        self.proc = self.log = None
        self.current = None
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(self, key, model, prompt):
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
                self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model
        append(PROBE / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        append(PROBE / 'RESPONSES.jsonl', dict(key=key, model=model, response=resp))
        if resp.get('status') != 'delivered':
            raise RuntimeError('Infrastructure failure: ' + key)
        return resp

    def close(self):
        if self.proc is not None:
            engine.stop_model(self.proc, self.log)
            self.proc = None
        try:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception:
            pass
        self.lock.close()


def run():
    PROBE.mkdir(exist_ok=True)
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks'][:N_SAMPLE]
    src_req = {}
    for l in (OUT / 'REQUESTS.jsonl').read_text().splitlines():
        r = json.loads(l)
        src_req[r['key']] = r
    src_ans = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        src_ans[r['key']] = r
    manifest = dict(role='determinism_probe_diagnostic', n=N_SAMPLE,
                    sampling='first 20 tasks in frozen order; prompts copied from base panel REQUESTS.jsonl',
                    pairs=[dict(task_uid=t['uid'], node=node, src_key=f'{node}:{t["uid"]}')
                           for t in tasks for node in ('e1', 'r', 'v')])
    (PROBE / 'PROBE_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    engine.OUT = PROBE
    caller = Caller()
    t0 = time.time()
    try:
        for node, model in (('e1', 'large'), ('r', 'medium'), ('v', 'coder')):
            for t in tasks:
                key = f'probe:{node}:{t["uid"]}'
                caller.call(key, model, src_req[f'{node}:{t["uid"]}']['prompt'])
    finally:
        caller.close()
    res = {}
    for l in (PROBE / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        res[r['key']] = r
    report = {}
    for node in ('e1', 'r', 'v'):
        div = 0
        for t in tasks:
            a = src_ans[f'{node}:{t["uid"]}']['response'].get('answer')
            b = res[f'probe:{node}:{t["uid"]}']['response'].get('answer')
            if a != b:
                div += 1
        report[node] = dict(n=N_SAMPLE, diverged=div, rate=round(div / N_SAMPLE, 3))
    report['wall_seconds'] = round(time.time() - t0, 1)
    report['note'] = 'temperature 0, top_p 1, max_tokens 512; same prompts, same weights (provenance-checked), fresh server sessions'
    core.write(PROBE / 'PROBE_RESULTS.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    run()
