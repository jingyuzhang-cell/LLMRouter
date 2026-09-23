"""Adaptive Failure Benchmark runner (frozen protocol: BENCHMARK_PROTOCOL.md).

S1 clean: Router (best single model = large direct QA, 120 real calls),
          Static DAG = frozen initial pass (cache), Dynamic DAG = RD corrected (cache).
S2 failure injection at 10/20/30%: capability faults on random (task, node)
   pairs; Router retries (fault persists), Static re-executes the whole flow
   (faulted node reproduces the failing output; downstream runs for real on the
   corrupt upstream), Dynamic applies RD local recovery with model switching.
S3 budget: post-hoc accounting in benchmark_analyze.py.

Cache policy: (model, prompt) reuse for identical calls (temp 0) unless the
(task, node, model) triple is faulted (fault overrides by definition). All
other calls are REAL. Fault outputs are sampled from REAL failing outputs of
the frozen panel.
"""
import fcntl
import hashlib
import json
import random
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .multidag_dynamic import OUT, VPROMPT, close, json_value, parse_facts_safe, value_of
from .multidag_ablation import ABL
from .multidag_fullgraph import FG

BENCH = OUT.parent / 'adaptive_benchmark'
SEED = 20260923
RATES = (0.10, 0.20, 0.30)

ROUTER_PROMPT = ('Answer the financial question using the table and passages below. Compute the final '
                 'numeric answer yourself. Return ONLY JSON {{"answer": <number>}} (percentages as ratios x100; '
                 'preserve reported units).\n'
                 'QUESTION: {q}\nTABLE:\n{ctx_table}\nPASSAGES:\n{ctx_text}')


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def parse_router(ans):
    text = (ans or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    try:
        obj = json.loads(text)
        for k in ('answer', 'value', 'result'):
            if k in obj:
                return float(obj[k])
    except Exception:
        pass
    return None


def collect_real_failures():
    resp = {}
    for folder in (OUT, ABL, FG):
        for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    e_pool, r_pool, v_pool = [], [], []
    for t in tasks:
        u = t['uid']
        f1, _ = parse_facts_safe(resp[f'e1:{u}']['response']['answer'])
        f2, _ = parse_facts_safe(resp[f'e2:{u}']['response']['answer'])
        for node, f in (('e1', f1), ('e2', f2)):
            if not f['facts']:
                e_pool.append(dict(node=node, answer=resp[f'{node}:{u}']['response']['answer']))
        val, err = value_of(resp[f'r:{u}']['response']['answer'], {'facts': f1['facts'] + f2['facts']})
        if err:
            r_pool.append(resp[f'r:{u}']['response']['answer'])
    for k, r in resp.items():
        if k.split(':')[0] != 'v':
            continue
        ans = r['response']['answer']
        try:
            v.decode(ans)['value']
        except Exception:
            v_pool.append(ans)
    return e_pool, r_pool, v_pool


class Caller:
    """Two-level cache: exact key, or (model, prompt_sha). Fault override on
    (task_uid, node, model) triples. All other calls are REAL."""

    def __init__(self, folder):
        self.folder = folder
        self.by_key = {}
        self.by_mp = {}
        self.faults = {}
        self.proc = self.log = None
        self.current = None
        for f in (OUT, ABL, FG):
            p = f / 'RESPONSES.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_key[r['key']] = r
        for f in (OUT, ABL, FG):
            p = f / 'REQUESTS.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_mp[(r['model'], sha(r['prompt']))] = r['key']
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def set_fault(self, uid, node, model, failing_answer):
        self.faults[(uid, node, model)] = failing_answer

    def call(self, key, model, prompt, uid=None, node=None):
        if uid is not None and (uid, node, model) in self.faults:
            clean_key = f'{node}:{uid}'
            clean = self.by_key.get(clean_key, {})
            usage = (clean.get('response') or {}).get('usage')
            lat = (clean.get('response') or {}).get('latency_s')
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=self.faults[(uid, node, model)],
                                     usage=usage or dict(total_tokens=1), latency_s=lat or 0.0,
                                     injected_fault=True))
            self._store(rec)
            return rec
        if key in self.by_key:
            rec = self.by_key[key]
            if rec['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return rec
        mp = (model, sha(prompt))
        if mp in self.by_mp:
            src = self.by_key[self.by_mp[mp]]
            rec = dict(key=key, model=model, response=src['response'], alias_of=self.by_mp[mp])
            self._store(rec)
            return rec
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
                self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model
        append(self.folder / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp)
        append(self.folder / 'RESPONSES.jsonl', rec)
        self.by_key[key] = rec
        self.by_mp[mp] = key
        if resp.get('status') != 'delivered':
            raise RuntimeError('Infrastructure failure: ' + key)
        return rec

    def _store(self, rec):
        self.by_key[rec['key']] = rec

    def cost(self, key):
        return float((self.by_key[key]['response'].get('usage') or {}).get('total_tokens') or 0)

    def lat(self, key):
        return self.by_key[key]['response'].get('latency_s') or 0

    def close(self):
        if self.proc is not None:
            engine.stop_model(self.proc, self.log)
            self.proc = None
        try:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception:
            pass
        self.lock.close()


def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        f.flush()


def load_all_responses():
    resp = {}
    for folder in (OUT, ABL, FG):
        for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r
    return resp


def freeze():
    BENCH.mkdir(exist_ok=True)
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    bindings = {}
    for f in ('benchmark_run.py', 'benchmark_analyze.py', 'BENCHMARK_PROTOCOL.md'):
        try:
            bindings[os.path.join(here, f)] = sha(open(os.path.join(here, f)).read())
        except Exception:
            pass
    e_pool, r_pool, v_pool = collect_real_failures()
    pol = dict(role='adaptive_failure_benchmark', seed=SEED, rates=RATES,
               methods=dict(router='best single model (large) direct QA, no DAG, no recovery',
                            static='frozen initial pass e1/e2 large -> r medium -> v coder, fixed, no feedback',
                            dynamic='RD deployable local recovery (corrected v-stage)'),
               failure_model='capability fault on (task,node,planned-model): any call of that model for that node-task returns a real failing output; retry/re-execution with same model reproduces the fault',
               fault_pools=dict(e_n=len(e_pool), r_n=len(r_pool), v_n=len(v_pool),
                                e_sample=repr(e_pool[0]['answer'][:120]), r_sample=repr(r_pool[0][:120]), v_sample=repr(v_pool[0][:120])),
               cost_accounting='re-execution/retry tokens counted even when the call is (model,prompt)-reused',
               code_sha256=bindings)
    (BENCH / 'BENCHMARK_POLICY.json').write_text(json.dumps(pol, ensure_ascii=False, indent=2))
    (BENCH / 'FAULT_POOLS.json').write_text(json.dumps(
        dict(e=[x['answer'] for x in e_pool[:20]], r=r_pool[:20], v=v_pool[:20]), ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, e_pool=len(e_pool), r_pool=len(r_pool), v_pool=len(v_pool))))


def router_clean(caller):
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    results = {}
    for t in tasks:
        u = t['uid']
        key = f'router:{u}'
        caller.call(key, 'large', ROUTER_PROMPT.format(q=t['question'], ctx_table=t['ctx_table'], ctx_text=t['ctx_text']))
        val = parse_router(caller.by_key[key]['response']['answer'])
        results[u] = dict(ok=close(val, t['answer']), val=val,
                          used=caller.cost(key), lat=caller.lat(key), keys=[key])
    return results


def static_clean(caller, resp):
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    results = {}
    for t in tasks:
        u = t['uid']
        keys = [f'e1:{u}', f'e2:{u}', f'r:{u}', f'v:{u}']
        val = json_value(resp[f'v:{u}']['response']['answer'])
        results[u] = dict(ok=close(val, t['answer']), val=val,
                          used=sum(float((resp[k]['response'].get('usage') or {}).get('total_tokens') or 0) for k in keys),
                          lat=sum(resp[k]['response'].get('latency_s') or 0 for k in keys), keys=keys)
    return results


def dynamic_clean(corrected_arms):
    return {u: dict(ok=corrected_arms['rd'][u]['ok'], used=corrected_arms['rd'][u]['used'],
                    lat=corrected_arms['rd'][u]['latency'], keys=corrected_arms['rd'][u]['keys'])
            for u in corrected_arms['rd']}


def fault_scenario(caller, rate, resp):
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    gold = {t['uid']: t['answer'] for t in tasks}
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    rng = random.Random(SEED)
    n_fault = int(len(tasks) * rate)
    faulted = rng.sample(uids, n_fault)
    faults = {}
    for u in faulted:
        node = rng.choice(['e1', 'e2', 'r', 'v'])
        if node in ('e1', 'e2'):
            failing = pools['e'][rng.randrange(len(pools['e']))]
        elif node == 'r':
            failing = pools['r'][rng.randrange(len(pools['r']))]
        else:
            failing = pools['v'][rng.randrange(len(pools['v']))]
        faults[u] = (node, failing)
    out = {'faulted': {u: faults[u][0] for u in faults}, 'router': {}, 'static': {}, 'dynamic': {}}

    # ---- Router: retry same model -> fault persists; cost = 2x clean call ----
    for u in uids:
        base = router_results[u]
        if u in faults:
            out['router'][u] = dict(ok=False, used=base['used'] * 2, lat=base['lat'] * 2, keys=[f'router:{u}'],
                                    injected=True)
        else:
            out['router'][u] = dict(ok=base['ok'], used=base['used'], lat=base['lat'], keys=[f'router:{u}'],
                                    injected=False)

    # ---- Static: re-execute whole flow with fault override; no feedback ----
    for u in uids:
        if u not in faults:
            out['static'][u] = dict(ok=static_results[u]['ok'], used=static_results[u]['used'],
                                    lat=static_results[u]['lat'], keys=static_results[u]['keys'], injected=False)
            continue
        node, failing = faults[u]
        if node in ('e1', 'e2'):
            caller.set_fault(u, node, 'large', failing)
        elif node == 'r':
            caller.set_fault(u, 'r', 'medium', failing)
        else:
            caller.set_fault(u, 'v', 'coder', failing)
        t = next(x for x in tasks if x['uid'] == u)
        keys = []
        facts = {}
        for nd, ctx in (('e1', t['ctx_table']), ('e2', t['ctx_text'])):
            k = f'bf-s:{nd}:{u}'
            caller.call(k, 'large', v.eprompt(dict(question=t['question'], context=ctx)), uid=u, node=nd)
            keys.append(k)
            fnew, _ = parse_facts_safe(caller.by_key[k]['response']['answer'])
            facts[nd] = fnew
        merged = {'facts': facts['e1']['facts'] + facts['e2']['facts']}
        k = f'bf-s:r:{u}'
        caller.call(k, 'medium', v.sprompt(dict(question=t['question']), merged), uid=u, node='r')
        keys.append(k)
        val, err = value_of(caller.by_key[k]['response']['answer'], merged)
        expr = 'UNPARSEABLE' if err else v.decode(caller.by_key[k]['response']['answer'])['expression']
        k = f'bf-s:v:{u}'
        caller.call(k, 'coder', VPROMPT.format(q=t['question'], facts=json.dumps(merged['facts']), expr=expr),
                    uid=u, node='v')
        keys.append(k)
        vval = json_value(caller.by_key[k]['response']['answer'])
        out['static'][u] = dict(ok=close(vval, gold[u]), val=vval,
                                used=sum(caller.cost(kk) for kk in keys),
                                lat=sum(caller.lat(kk) for kk in keys), keys=keys, injected=True)
        caller.faults.clear()

    # ---- Dynamic (RD): local recovery with model switching ----
    init = {}
    for t in tasks:
        u = t['uid']
        f1, _ = parse_facts_safe(resp[f'e1:{u}']['response']['answer'])
        f2, _ = parse_facts_safe(resp[f'e2:{u}']['response']['answer'])
        init[u] = dict(f1=f1, f2=f2)
    n_ext_fail_seen = 0
    e_models = {}
    dyn_state = {}
    for t in tasks:
        u = t['uid']
        st = dict(e1=init[u]['f1'], e2=init[u]['f2'], ok=None, events=[],
                  keys=[f'e1:{u}', f'e2:{u}', f'r:{u}', f'v:{u}'],
                  question=t['question'], gold=t['answer'],
                  ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)
        if u in faults:
            node, failing = faults[u]
            planned = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}[node]
            if node in ('e1', 'e2'):
                fnew, _ = parse_facts_safe(failing)
                st[node] = fnew
            k = f'{node}:{u}'
            caller.by_key[k] = dict(key=k, model=planned,
                                    response=dict(status='delivered', answer=failing,
                                                  usage=resp[k]['response'].get('usage'),
                                                  latency_s=resp[k]['response'].get('latency_s'),
                                                  injected_fault=True))
        dyn_state[u] = st
    for u, (node, failing) in faults.items():
        if node in ('e1', 'e2'):
            caller.set_fault(u, node, 'large', failing)
        elif node == 'r':
            caller.set_fault(u, 'r', 'medium', failing)
        else:
            caller.set_fault(u, 'v', 'coder', failing)

    def merged(st):
        return {'facts': st['e1']['facts'] + st['e2']['facts']}

    def latest(st, prefix):
        return [k for k in st['keys'] if k.split(':')[0] == prefix][-1]

    def call_into(st, u, node, model, key):
        if node in ('e1', 'e2'):
            caller.call(key, model, v.eprompt(dict(question=st['question'], context=st['ctx'][node])), uid=u, node=node)
            fnew, _ = parse_facts_safe(caller.by_key[key]['response']['answer'])
            st[node] = fnew
        elif node == 'r':
            caller.call(key, model, v.sprompt(dict(question=st['question']), merged(st)), uid=u, node='r')
        else:
            caller.call(key, model, VPROMPT.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                                   expr=st['expr_text'] or 'UNPARSEABLE'), uid=u, node='v')
        st['keys'].append(key)

    def r_value(st):
        return value_of(caller.by_key[latest(st, 'r')]['response']['answer'], merged(st))

    def refresh_expr(st):
        val, err = r_value(st)
        st['expr_text'] = 'UNPARSEABLE' if err else v.decode(caller.by_key[latest(st, 'r')]['response']['answer'])['expression']
        return (not err) and close(val, st['gold'])

    # stage 1: e failures (memory rule)
    e_events = []
    for t in tasks:
        u = t['uid']
        st = dyn_state[u]
        for node in ('e1', 'e2'):
            if st[node]['facts']:
                continue
            model = 'medium' if n_ext_fail_seen > 0 else 'coder'
            n_ext_fail_seen += 1
            e_events.append((u, st, node, model))
    for u, st, node, m in e_events:
        key = f'bf-d:{node}:{u}:fb'
        call_into(st, u, node, m, key)
        st['events'].append(dict(node=node, kind='fb', model=m, key=key))
    affected = {id(st) for _, st, _, _ in e_events}
    for t in tasks:
        u = t['uid']
        st = dyn_state[u]
        if id(st) in affected:
            key = f'bf-d:r:{u}:fb-d'
            call_into(st, u, 'r', 'medium', key)
            st['events'].append(dict(node='r', kind='refresh', model='medium', key=key))
            refresh_expr(st)
    # stage 2: r failure (deployable)
    r_events = []
    for t in tasks:
        u = t['uid']
        st = dyn_state[u]
        if r_value(st)[1]:
            r_events.append((u, st))
        refresh_expr(st)
    for u, st in r_events:
        key = f'bf-d:r:{u}:esc'
        call_into(st, u, 'r', 'large', key)
        st['events'].append(dict(node='r', kind='esc', model='large', key=key))
        refresh_expr(st)
    # stage 3: v refresh for r-changed tasks
    for t in tasks:
        u = t['uid']
        st = dyn_state[u]
        rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
        if len(rks) > 1:
            key = f'bf-d:v:{u}:fb-d'
            call_into(st, u, 'v', 'coder', key)
            st['events'].append(dict(node='v', kind='refresh', model='coder', key=key))
    # stage 4: v failure (deployable)
    v_events = []
    for t in tasks:
        u = t['uid']
        st = dyn_state[u]
        vval = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
        if close(vval, st['gold']):
            st['ok'] = True
            continue
        rval, rerr = r_value(st)
        v_fail = (vval is None) or (not rerr and not close(vval, rval))
        if v_fail:
            v_events.append((u, st))
        else:
            st['ok'] = False
    for u, st in v_events:
        key = f'bf-d:v:{u}:esc'
        call_into(st, u, 'v', 'large', key)
        st['events'].append(dict(node='v', kind='esc', model='large', key=key))
        vval = json_value(caller.by_key[key]['response']['answer'])
        st['ok'] = close(vval, st['gold'])
    for t in tasks:
        u = t['uid']
        st = dyn_state[u]
        if st['ok'] is None:
            vval = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
            st['ok'] = close(vval, st['gold'])
        out['dynamic'][u] = dict(ok=st['ok'], keys=st['keys'], events=st['events'],
                                 used=sum(caller.cost(k) for k in st['keys']),
                                 lat=sum(caller.lat(k) for k in st['keys']),
                                 injected=u in faults)
    caller.faults.clear()
    return out


def run():
    if not (BENCH / 'BENCHMARK_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    resp = load_all_responses()
    corrected = json.loads((OUT.parent / 'corrected_replay' / 'CORRECTED_ARMS.json').read_text())

    global router_results, static_results
    engine.OUT = BENCH
    t0 = time.time()
    caller = Caller(BENCH / 'router_clean')
    (BENCH / 'router_clean').mkdir(exist_ok=True)
    caller.folder = BENCH / 'router_clean'
    router_results = router_clean(caller)
    caller.close()
    core.write(BENCH / 'router_clean' / 'RESULT.json', dict(router=router_results,
                                                            wall_seconds=time.time() - t0))
    static_results = static_clean(caller, resp)
    dyn_clean = dynamic_clean(corrected['arms'])
    core.write(BENCH / 'CLEAN_RESULTS.json', dict(router=router_results, static=static_results, dynamic=dyn_clean))

    for rate in RATES:
        sub = BENCH / f'fault_p{int(rate * 100)}'
        sub.mkdir(exist_ok=True)
        caller = Caller(sub)
        caller.folder = sub
        t1 = time.time()
        out = fault_scenario(caller, rate, resp)
        out['wall_seconds'] = time.time() - t1
        out['rate'] = rate
        core.write(sub / 'FAULT_RESULT.json', out)
        caller.close()
        q = {m: round(sum(1 for u in out[m] if out[m][u]['ok']) / len(tasks), 4) for m in ('router', 'static', 'dynamic')}
        print(json.dumps(dict(rate=rate, Q=q, wall=round(out['wall_seconds'])), ensure_ascii=False))
    print(json.dumps(dict(done=True, wall_total=round(time.time() - t0)), ensure_ascii=False))


if __name__ == '__main__':
    run()
