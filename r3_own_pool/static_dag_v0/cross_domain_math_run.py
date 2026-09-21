"""Math500 six-arm runner. Stage-batched, resumable, deployable-only detection.

Arm outcomes are computed identically to the frozen protocol; call order is
batched by model for wall-clock efficiency and never affects any decision
(all decisions are functions of per-task state and frozen task order).
"""
import fcntl
import json
import os
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .cross_domain_math import (OUT, MONO, EXTRACT, SOLVE, VERIFY, N_TASKS,
                                HEADROOM, GATE, close, extract_mono_value)

CLOSURE = {'X': ['S', 'V'], 'S': ['V'], 'V': []}


def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())


def parse_math_facts(answer):
    """Lenient frozen parser for the math facts JSON contract."""
    text = (answer or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    dec = json.JSONDecoder()
    for i, c in enumerate(text):
        if c != '{':
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
            facts = []
            for f in obj.get('facts', []):
                val = float(f['value'])
                facts.append(dict(value=val))
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

    def call(self, key, model, prompt):
        if key in self.cache:
            if self.cache[key]['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return self.cache[key]
        if model != self.current:
            if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model); self.current = model
        append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
        self.cache[key] = rec
        if resp.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
        return rec

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
        # ---------- mono arms (batched by model) ----------
        for model in ('medium', 'large'):
            for t in tasks:
                k = f'M:{model[0]}:{t["index"]}'
                if k not in caller.cache:
                    caller.call(k, model, MONO.format(q=t['question']))
        for t in tasks:  # query router arm
            k = f'M:q:{t["index"]}'
            model = 'large' if t['tok_len'] > qr_thresh else 'medium'
            if k not in caller.cache:
                caller.call(k, model, MONO.format(q=t['question']))
        # ---------- shared initial DAG passes ----------
        for t in tasks:
            k = f'X:{t["index"]}'
            if k not in caller.cache:
                caller.call(k, 'large', EXTRACT.format(q=t['question']))
        facts = {}
        for t in tasks:
            f, bad = parse_math_facts(caller.cache[f'X:{t["index"]}']['response']['answer'])
            facts[t['index']] = dict(f=f, bad=bad)
        for t in tasks:
            k = f'S:{t["index"]}'
            if k not in caller.cache:
                caller.call(k, 'medium', SOLVE.format(q=t['question'], facts=json.dumps(facts[t['index']]['f']['facts'])))
        for t in tasks:
            k = f'V:{t["index"]}'
            if k not in caller.cache:
                _, expr, err = solve_out(caller.cache[f'S:{t["index"]}']['response']['answer'], facts[t['index']]['f'])
                caller.call(k, 'coder', VERIFY.format(q=t['question'], facts=json.dumps(facts[t['index']]['f']['facts']),
                                                      expr='UNPARSEABLE' if err else expr))
        # ---------- recovery arms (static, dynamic) ----------
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

            def do_call(node, model, key, st):
                i = key.split(':')[1]
                if node == 'X':
                    caller.call(key, model, EXTRACT.format(q=st['question']))
                    fnew, _ = parse_math_facts(caller.cache[key]['response']['answer'])
                    st['facts'] = fnew
                elif node == 'S':
                    caller.call(key, model, SOLVE.format(q=st['question'], facts=json.dumps(merged(st)['facts'])))
                else:
                    _, expr, err = s_out(st)
                    caller.call(key, model, VERIFY.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                                          expr='UNPARSEABLE' if err else (st['expr'] or 'UNPARSEABLE')))
                st['keys'].append(key)

            # stage 1: extraction failures
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
                for i, st, m in ev1:
                    if m != model: continue
                    key = f'X:{A}:{i}:efb'
                    do_call('X', m, key, st)
                    st['events'].append(dict(node='X', kind='efb', model=m, key=key, closure=CLOSURE['X']))
            # stage 2: solve refresh for e-fallback tasks, then solve failures
            for i, st, m in ev1:
                key = f'S:{A}:{i}:efb-d'
                do_call('S', 'medium', key, st)
                st['events'].append(dict(node='S', kind='refresh', model='medium', key=key, closure=[]))
            ev2 = []
            for t in tasks:
                i = t['index']; st = armstate[i]
                val, expr, err = s_out(st)
                st['expr'] = expr if not err else None
                if not err:
                    continue  # deployable: executable => no action (value errors undetectable)
                fb = 'coder' if arm == 'static' else 'large'
                if arm == 'dynamic':
                    budget = sum(cost_of(caller.cache, k) for k in state['static'][i]['keys']) * HEADROOM
                    rem = budget - sum(cost_of(caller.cache, k) for k in st['keys'])
                    if rem < GATE:
                        st['events'].append(dict(node='S', kind='esc', model='large', attempted=False,
                                                 gate=dict(rem=rem))); continue
                    ev2.append((i, st, 'large', dict(rem=rem)))
                else:
                    ev2.append((i, st, fb, None))
            for model in sorted({m for _, _, m, _ in ev2}):
                for i, st, m, gate in ev2:
                    if m != model: continue
                    key = f'S:{A}:{i}:sfb'
                    do_call('S', m, key, st)
                    st['events'].append(dict(node='S', kind='sfb', model=m, key=key, closure=CLOSURE['S'], gate=gate))
            # stage 3: verify refresh for tasks whose solve changed, then verify failures
            for t in tasks:
                i = t['index']; st = armstate[i]
                skeys = [k for k in st['keys'] if k.startswith('S')]
                if len(skeys) > 1:
                    key = f'V:{A}:{i}:rs-d'
                    do_call('V', 'coder', key, st)
                    st['events'].append(dict(node='V', kind='refresh', model='coder', key=key, closure=[]))
            ev3 = []
            for t in tasks:
                i = t['index']; st = armstate[i]
                val, expr, err = s_out(st)
                vv = v_val(st)
                fail_deployable = (vv is None) or (not err and not close(vv, val))
                if not fail_deployable:
                    continue
                fb = 'medium' if arm == 'static' else 'large'
                if arm == 'dynamic':
                    budget = sum(cost_of(caller.cache, k) for k in state['static'][i]['keys']) * HEADROOM
                    rem = budget - sum(cost_of(caller.cache, k) for k in st['keys'])
                    if rem < GATE:
                        st['events'].append(dict(node='V', kind='esc', model='large', attempted=False,
                                                 gate=dict(rem=rem))); continue
                    ev3.append((i, st, 'large', dict(rem=rem)))
                else:
                    ev3.append((i, st, fb, None))
            for model in sorted({m for _, _, m, _ in ev3}):
                for i, st, m, gate in ev3:
                    if m != model: continue
                    key = f'V:{A}:{i}:vfb'
                    do_call('V', m, key, st)
                    st['events'].append(dict(node='V', kind='vfb', model=m, key=key, closure=[], gate=gate))
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
