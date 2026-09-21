"""Math500 six-arm runner — parallel version (4 concurrent calls per model batch).

Protocol identical to the frozen CROSS_DOMAIN_MATH_PROTOCOL.json; only the
execution engine changed (vLLM serves --max-num-seqs 4, so 4 concurrent
requests are within the frozen serving configuration). Stage-batched,
resumable from cache, deployable-only failure detection.
"""
import fcntl
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .cross_domain_math import (OUT, MONO, EXTRACT, SOLVE, VERIFY, N_TASKS,
                                HEADROOM, GATE, close, extract_mono_value)

CLOSURE = {'X': ['S', 'V'], 'S': ['V'], 'V': []}
_lock = threading.Lock()


def append(path, obj):
    with _lock:
        with path.open('a') as f:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())


def parse_math_facts(answer):
    text = (answer or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    dec = json.JSONDecoder()
    for i, c in enumerate(text):
        if c != '{':
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
            facts = [dict(value=float(f['value'])) for f in obj.get('facts', [])]
            if 0 < len(facts) <= 24:
                return dict(facts=facts), False
        except Exception:
            continue
    return dict(facts=[]), True


def solve_out(answer, facts):
    try:
        expr = v.decode(answer)['expression']
    except Exception:
        return None, None, True
    try:
        return exec_calc(expr, facts), expr, False
    except Exception:
        return None, expr, True


def verify_value(answer):
    try:
        text = (answer or '').strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return float(json.loads(text)['value'])
    except Exception:
        return None


def cost_of(cache, key):
    r = cache.get(key)
    return float((r['response'].get('usage') or {}).get('total_tokens') or 0) if r else 0.0


class Caller:
    def __init__(self):
        self.proc = self.log = None; self.current = None; self.cache = {}
        if (OUT / 'RESPONSES.jsonl').exists():
            for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
                r = json.loads(l); self.cache[r['key']] = r
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _ensure_model(self, model):
        if model != self.current:
            if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model); self.current = model

    def batch(self, jobs):
        """jobs: list of (key, model, prompt), all one model. Cached keys skipped.
        Parallel (4 workers); returns after all complete."""
        todo = [(k, m, p) for k, m, p in jobs if k not in self.cache]
        if not todo:
            return
        self._ensure_model(todo[0][1])
        def one(job):
            key, model, prompt = job
            append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
            resp = engine.call_model(model, prompt)
            return key, model, resp
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(one, j) for j in todo]
            for f in as_completed(futs):
                key, model, resp = f.result()
                if resp.get('status') != 'delivered':
                    raise RuntimeError('Infrastructure failure: ' + key)
                rec = dict(key=key, model=model, response=resp)
                append(OUT / 'RESPONSES.jsonl', rec)
                self.cache[key] = rec

    def close(self):
        if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = None
        try: fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception: pass
        self.lock.close()


def run():
    tasks = json.loads((OUT / 'frozen_math_tasks.json').read_text())
    pol = json.loads((OUT / 'CROSS_DOMAIN_MATH_PROTOCOL.json').read_text())
    import re
    qr_thresh = int(re.search(r'tok_len > (\d+)', pol['arms']['query_router']).group(1))
    if (OUT / 'DONE.json').exists(): raise FileExistsError('math six-arm complete')
    engine.OUT = OUT
    caller = Caller()
    t0 = time.time()
    try:
        # ---------- mono arms ----------
        for model in ('medium', 'large'):
            caller.batch([(f'M:{model[0]}:{t["index"]}', model, MONO.format(q=t['question'])) for t in tasks])
        qr = [(f'M:q:{t["index"]}', 'large' if t['tok_len'] > qr_thresh else 'medium', MONO.format(q=t['question'])) for t in tasks]
        for model in ('medium', 'large'):
            caller.batch([j for j in qr if j[1] == model])
        # ---------- shared initial DAG passes ----------
        caller.batch([(f'X:{t["index"]}', 'large', EXTRACT.format(q=t['question'])) for t in tasks])
        facts = {}
        for t in tasks:
            f, bad = parse_math_facts(caller.cache[f'X:{t["index"]}']['response']['answer'])
            facts[t['index']] = dict(f=f, bad=bad)
        caller.batch([(f'S:{t["index"]}', 'medium',
                       SOLVE.format(q=t['question'], facts=json.dumps(facts[t['index']]['f']['facts']))) for t in tasks])
        vjobs = []
        for t in tasks:
            _, expr, err = solve_out(caller.cache[f'S:{t["index"]}']['response']['answer'], facts[t['index']]['f'])
            vjobs.append((f'V:{t["index"]}', 'coder',
                          VERIFY.format(q=t['question'], facts=json.dumps(facts[t['index']]['f']['facts']),
                                        expr='UNPARSEABLE' if err else expr)))
        caller.batch(vjobs)
        # ---------- recovery arms ----------
        state = {arm: {} for arm in ('static', 'dynamic')}
        for arm in state:
            for t in tasks:
                i = t['index']
                state[arm][i] = dict(facts=dict(facts[i]['f']), keys=[f'X:{i}', f'S:{i}', f'V:{i}'],
                                     events=[], expr=None, question=t['question'], gold=t['gold'])
        n_ext_fail_seen = 0
        for arm in ('static', 'dynamic'):
            A = 's' if arm == 'static' else 'd'
            armstate = state[arm]

            def merged(st):
                return st['facts']

            def s_out(st):
                return solve_out(caller.cache[[k for k in st['keys'] if k.startswith('S')][-1]]['response']['answer'], merged(st))

            def v_val(st):
                return verify_value(caller.cache[[k for k in st['keys'] if k.startswith('V')][-1]]['response']['answer'])

            def apply_X(key, st):
                fnew, _ = parse_math_facts(caller.cache[key]['response']['answer'])
                st['facts'] = fnew; st['keys'].append(key)

            def apply_S(key, st):
                st['keys'].append(key)

            def apply_V(key, st):
                st['keys'].append(key)

            # stage 1: extraction failures (memory rule for dynamic)
            ev1 = []
            for t in tasks:
                st = armstate[t['index']]
                if st['facts']['facts']:
                    continue
                if arm == 'dynamic':
                    model = 'medium' if n_ext_fail_seen > 0 else 'coder'
                    n_ext_fail_seen += 1
                else:
                    model = 'coder'
                ev1.append((t['index'], st, model))
            for model in sorted({m for _, _, m in ev1}):
                jobs = [(f'X:{A}:{i}:efb', model, EXTRACT.format(q=st['question'])) for i, st, m in ev1 if m == model]
                caller.batch(jobs)
                for i, st, m in ev1:
                    if m != model: continue
                    apply_X(f'X:{A}:{i}:efb', st)
                    st['events'].append(dict(node='X', kind='efb', model=m, key=f'X:{A}:{i}:efb', closure=CLOSURE['X']))
            # stage 2: solve refresh for e-fallback tasks
            if ev1:
                jobs = [(f'S:{A}:{i}:efb-d', 'medium',
                         SOLVE.format(q=st['question'], facts=json.dumps(merged(st)['facts']))) for i, st, _ in ev1]
                caller.batch(jobs)
                for i, st, _ in ev1:
                    apply_S(f'S:{A}:{i}:efb-d', st)
                    st['events'].append(dict(node='S', kind='refresh', model='medium', key=f'S:{A}:{i}:efb-d', closure=[]))
            ev2 = []
            for t in tasks:
                i = t['index']; st = armstate[i]
                val, expr, err = s_out(st)
                st['expr'] = expr if not err else None
                if not err:
                    continue
                if arm == 'dynamic':
                    budget = sum(cost_of(caller.cache, k) for k in state['static'][i]['keys']) * HEADROOM
                    rem = budget - sum(cost_of(caller.cache, k) for k in st['keys'])
                    if rem < GATE:
                        st['events'].append(dict(node='S', kind='esc', model='large', attempted=False, gate=dict(rem=rem)))
                        continue
                    ev2.append((i, st, 'large', dict(rem=rem)))
                else:
                    ev2.append((i, st, 'coder', None))
            for model in sorted({m for _, _, m, _ in ev2}):
                jobs = [(f'S:{A}:{i}:sfb', model, SOLVE.format(q=st['question'], facts=json.dumps(merged(st)['facts'])))
                        for i, st, m, _ in ev2 if m == model]
                caller.batch(jobs)
                for i, st, m, gate in ev2:
                    if m != model: continue
                    apply_S(f'S:{A}:{i}:sfb', st)
                    st['events'].append(dict(node='S', kind='sfb', model=m, key=f'S:{A}:{i}:sfb', closure=CLOSURE['S'], gate=gate))
            # stage 3: verify refresh for changed solve outputs
            vrefresh = [t['index'] for t in tasks if len([k for k in armstate[t['index']]['keys'] if k.startswith('S')]) > 1]
            if vrefresh:
                jobs = []
                for i in vrefresh:
                    st = armstate[i]
                    _, expr, err = s_out(st)
                    jobs.append((f'V:{A}:{i}:rs-d', 'coder',
                                 VERIFY.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                               expr='UNPARSEABLE' if err else expr)))
                caller.batch(jobs)
                for i in vrefresh:
                    apply_V(f'V:{A}:{i}:rs-d', armstate[i])
                    armstate[i]['events'].append(dict(node='V', kind='refresh', model='coder', key=f'V:{A}:{i}:rs-d', closure=[]))
            ev3 = []
            for t in tasks:
                i = t['index']; st = armstate[i]
                val, expr, err = s_out(st)
                vv = v_val(st)
                fail_deployable = (vv is None) or (not err and not close(vv, val))
                if not fail_deployable:
                    continue
                if arm == 'dynamic':
                    budget = sum(cost_of(caller.cache, k) for k in state['static'][i]['keys']) * HEADROOM
                    rem = budget - sum(cost_of(caller.cache, k) for k in st['keys'])
                    if rem < GATE:
                        st['events'].append(dict(node='V', kind='esc', model='large', attempted=False, gate=dict(rem=rem)))
                        continue
                    ev3.append((i, st, 'large', dict(rem=rem)))
                else:
                    ev3.append((i, st, 'medium', None))
            for model in sorted({m for _, _, m, _ in ev3}):
                jobs = []
                for i, st, m, _ in ev3:
                    if m != model: continue
                    _, expr, err = s_out(st)
                    jobs.append((f'V:{A}:{i}:vfb', model,
                                 VERIFY.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                               expr='UNPARSEABLE' if err else (st['expr'] or 'UNPARSEABLE'))))
                caller.batch(jobs)
                for i, st, m, gate in ev3:
                    if m != model: continue
                    apply_V(f'V:{A}:{i}:vfb', st)
                    st['events'].append(dict(node='V', kind='vfb', model=m, key=f'V:{A}:{i}:vfb', closure=[], gate=gate))
            for t in tasks:
                st = armstate[t['index']]
                st['ok'] = close(v_val(st), t['gold'])
                st['used'] = sum(cost_of(caller.cache, k) for k in st['keys'])
        raw = dict(wall_seconds=time.time() - t0,
                   static={str(k): s for k, s in state['static'].items()},
                   dynamic={str(k): s for k, s in state['dynamic'].items()},
                   ext_bad={str(t['index']): facts[t['index']]['bad'] for t in tasks})
        core.write(OUT / 'RAW_TAIL.json', raw)
        core.write(OUT / 'DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(caller.cache)))
        print(json.dumps(dict(done=True, calls=len(caller.cache))))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
