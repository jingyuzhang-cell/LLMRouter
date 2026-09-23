"""Multi-seed fault injection (frozen addendum in BENCHMARK_PROTOCOL.md).

Two additional seeds (20260924, 20260925) with the same procedure, pools and
policies as the original run (20260923). Calls reuse executed (model, prompt)
pairs at temperature 0; only new prompts are executed for real. Static and
Dynamic sections are batched BY MODEL within each stage (no per-task server
switching); decisions depend only on task-local state, so batching cannot
change any decision.

Outputs: adaptive_benchmark/fault_p{p}_seed{s}/FAULT_RESULT.json (same schema
as the original fault_p{p} dirs).
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
from .benchmark_run import BENCH, RATES, append, collect_real_failures

NEW_SEEDS = (20260924, 20260925)
CACHE_DIRS = [OUT, ABL, FG, BENCH / 'router_clean']


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Caller:
    def __init__(self, folder):
        self.folder = folder
        self.by_key = {}
        self.by_mp = {}
        self.proc = self.log = None
        self.current = None
        import glob
        import pathlib
        dirs = [pathlib.Path(d) for d in CACHE_DIRS] + [pathlib.Path(d) for d in sorted(glob.glob(str(BENCH / 'fault_p*')))]
        for d in dirs:
            p = d / 'RESPONSES.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_key[r['key']] = r
        for d in dirs:
            p = d / 'REQUESTS.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_mp.setdefault((r['model'], sha(r['prompt'])), r['key'])
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(self, key, model, prompt):
        if key in self.by_key:
            rec = self.by_key[key]
            if rec['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return rec
        mp = (model, sha(prompt))
        if mp in self.by_mp:
            src = self.by_key[self.by_mp[mp]]
            rec = dict(key=key, model=model, response=src['response'], alias_of=self.by_mp[mp])
            self.by_key[key] = rec
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


def build_faults(seed, rate, tasks):
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    rng = random.Random(seed)
    n_fault = int(len(tasks) * rate)
    faulted = rng.sample([t['uid'] for t in tasks], n_fault)
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
    return faults


def run_seed(seed):
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    resp = {}
    for d in CACHE_DIRS:
        for l in (d / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r
    gold = {t['uid']: t['answer'] for t in tasks}
    clean = json.loads((BENCH / 'CLEAN_RESULTS.json').read_text())
    for rate in RATES:
        sub = BENCH / f'fault_p{int(rate * 100)}_seed{seed}'
        sub.mkdir(exist_ok=True)
        caller = Caller(sub)
        t1 = time.time()
        faults = build_faults(seed, rate, tasks)
        out = {'faulted': {u: faults[u][0] for u in faults}, 'router': {}, 'static': {}, 'dynamic': {}}
        # ---- router: retry same model; fault persists ----
        for u in [t['uid'] for t in tasks]:
            base = clean['router'][u]
            if u in faults:
                out['router'][u] = dict(ok=False, used=base['used'] * 2, lat=base['lat'] * 2,
                                        keys=[f'router:{u}'], injected=True)
            else:
                out['router'][u] = dict(ok=base['ok'], used=base['used'], lat=base['lat'],
                                        keys=[f'router:{u}'], injected=False)
        # ---- static: whole-flow re-execution, batched by model in 3 passes ----
        planned = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
        static_jobs = {u: dict(keys=[], facts={}, expr=None) for u in faults}
        # pass 1: e1/e2 (large)
        for u in faults:
            t = next(x for x in tasks if x['uid'] == u)
            for nd, ctx in (('e1', t['ctx_table']), ('e2', t['ctx_text'])):
                k = f'bf-s:{nd}:{u}'
                caller.call(k, 'large', v.eprompt(dict(question=t['question'], context=ctx)))
                static_jobs[u]['keys'].append(k)
                fnew, _ = parse_facts_safe(caller.by_key[k]['response']['answer'])
                static_jobs[u]['facts'][nd] = fnew
        # pass 2: r (medium)
        for u in faults:
            t = next(x for x in tasks if x['uid'] == u)
            merged = {'facts': static_jobs[u]['facts']['e1']['facts'] + static_jobs[u]['facts']['e2']['facts']}
            k = f'bf-s:r:{u}'
            caller.call(k, 'medium', v.sprompt(dict(question=t['question']), merged))
            static_jobs[u]['keys'].append(k)
            val, err = value_of(caller.by_key[k]['response']['answer'], merged)
            static_jobs[u]['expr'] = 'UNPARSEABLE' if err else v.decode(caller.by_key[k]['response']['answer'])['expression']
            static_jobs[u]['merged'] = merged
        # pass 3: v (coder)
        for u in faults:
            t = next(x for x in tasks if x['uid'] == u)
            k = f'bf-s:v:{u}'
            caller.call(k, 'coder', VPROMPT.format(q=t['question'],
                                                   facts=json.dumps(static_jobs[u]['merged']['facts']),
                                                   expr=static_jobs[u]['expr']))
            static_jobs[u]['keys'].append(k)
            vval = json_value(caller.by_key[k]['response']['answer'])
            out['static'][u] = dict(ok=close(vval, gold[u]), val=vval,
                                    used=sum(caller.cost(kk) for kk in static_jobs[u]['keys']),
                                    lat=sum(caller.lat(kk) for kk in static_jobs[u]['keys']),
                                    keys=static_jobs[u]['keys'], injected=True)
        for t in tasks:
            u = t['uid']
            if u not in faults:
                out['static'][u] = dict(ok=clean['static'][u]['ok'], used=clean['static'][u]['used'],
                                        lat=clean['static'][u]['lat'], keys=clean['static'][u]['keys'],
                                        injected=False)
        # ---- dynamic (RD): local recovery; stage-batched by model ----
        init = {}
        for t in tasks:
            u = t['uid']
            f1, _ = parse_facts_safe(resp[f'e1:{u}']['response']['answer'])
            f2, _ = parse_facts_safe(resp[f'e2:{u}']['response']['answer'])
            init[u] = dict(f1=f1, f2=f2)
        dyn = {}
        for t in tasks:
            u = t['uid']
            dyn[u] = dict(e1=init[u]['f1'], e2=init[u]['f2'], ok=None, events=[],
                          keys=[f'e1:{u}', f'e2:{u}', f'r:{u}', f'v:{u}'],
                          question=t['question'], gold=t['answer'],
                          ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)
        # fault overrides on initial keys
        for u, (node, failing) in faults.items():
            if node in ('e1', 'e2'):
                fnew, _ = parse_facts_safe(failing)
                dyn[u][node] = fnew
            k = f'{node}:{u}'
            caller.by_key[k] = dict(key=k, model=planned[node],
                                    response=dict(status='delivered', answer=failing,
                                                  usage=resp[k]['response'].get('usage'),
                                                  latency_s=resp[k]['response'].get('latency_s'),
                                                  injected_fault=True))

        def merged(st):
            return {'facts': st['e1']['facts'] + st['e2']['facts']}

        def latest(st, prefix):
            return [k for k in st['keys'] if k.split(':')[0] == prefix][-1]

        def r_ans(st):
            return caller.by_key[latest(st, 'r')]['response']['answer']

        def r_value(st):
            return value_of(r_ans(st), merged(st))

        def refresh_expr(st):
            val, err = r_value(st)
            st['expr_text'] = 'UNPARSEABLE' if err else v.decode(r_ans(st))['expression']
            return (not err) and close(val, st['gold'])

        # stage 1: e failures (memory rule), batched by model
        n_seen = 0
        e_jobs = []
        for t in tasks:
            u = t['uid']
            st = dyn[u]
            for node in ('e1', 'e2'):
                if st[node]['facts']:
                    continue
                model = 'medium' if n_seen > 0 else 'coder'
                n_seen += 1
                e_jobs.append((u, node, model))
        for model in ('coder', 'medium'):
            for u, node, m in e_jobs:
                if m != model:
                    continue
                key = f'bf-d:{node}:{u}:fb'
                caller.call(key, m, v.eprompt(dict(question=dyn[u]['question'], context=dyn[u]['ctx'][node])))
                fnew, _ = parse_facts_safe(caller.by_key[key]['response']['answer'])
                dyn[u][node] = fnew
                dyn[u]['keys'].append(key)
                dyn[u]['events'].append(dict(node=node, kind='fb', model=m, key=key))
        affected = {u for u, _, _ in e_jobs}
        for u in affected:  # all medium
            key = f'bf-d:r:{u}:fb-d'
            caller.call(key, 'medium', v.sprompt(dict(question=dyn[u]['question']), merged(dyn[u])))
            dyn[u]['keys'].append(key)
            dyn[u]['events'].append(dict(node='r', kind='refresh', model='medium', key=key))
            refresh_expr(dyn[u])
        # stage 2: r failure (deployable), esc large
        r_esc = []
        for t in tasks:
            u = t['uid']
            if r_value(dyn[u])[1]:
                r_esc.append(u)
            refresh_expr(dyn[u])
        for u in r_esc:
            key = f'bf-d:r:{u}:esc'
            caller.call(key, 'large', v.sprompt(dict(question=dyn[u]['question']), merged(dyn[u])))
            dyn[u]['keys'].append(key)
            dyn[u]['events'].append(dict(node='r', kind='esc', model='large', key=key))
            refresh_expr(dyn[u])
        # stage 3: v refresh (coder) for r-changed
        for t in tasks:
            u = t['uid']
            rks = [k for k in dyn[u]['keys'] if k.split(':')[0] == 'r']
            if len(rks) > 1:
                key = f'bf-d:v:{u}:fb-d'
                caller.call(key, 'coder', VPROMPT.format(q=dyn[u]['question'],
                                                         facts=json.dumps(merged(dyn[u])['facts']),
                                                         expr=dyn[u]['expr_text'] or 'UNPARSEABLE'))
                dyn[u]['keys'].append(key)
                dyn[u]['events'].append(dict(node='v', kind='refresh', model='coder', key=key))
        # stage 4: v failure (deployable), esc large
        v_esc = []
        for t in tasks:
            u = t['uid']
            vval = json_value(caller.by_key[latest(dyn[u], 'v')]['response']['answer'])
            if close(vval, dyn[u]['gold']):
                dyn[u]['ok'] = True
                continue
            rval, rerr = r_value(dyn[u])
            if (vval is None) or (not rerr and not close(vval, rval)):
                v_esc.append(u)
            else:
                dyn[u]['ok'] = False
        for u in v_esc:
            key = f'bf-d:v:{u}:esc'
            caller.call(key, 'large', VPROMPT.format(q=dyn[u]['question'],
                                                     facts=json.dumps(merged(dyn[u])['facts']),
                                                     expr=dyn[u]['expr_text'] or 'UNPARSEABLE'))
            dyn[u]['keys'].append(key)
            dyn[u]['events'].append(dict(node='v', kind='esc', model='large', key=key))
            vval = json_value(caller.by_key[key]['response']['answer'])
            dyn[u]['ok'] = close(vval, dyn[u]['gold'])
        for t in tasks:
            u = t['uid']
            st = dyn[u]
            if st['ok'] is None:
                vval = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
                st['ok'] = close(vval, st['gold'])
            out['dynamic'][u] = dict(ok=st['ok'], keys=st['keys'], events=st['events'],
                                     used=sum(caller.cost(k) for k in st['keys']),
                                     lat=sum(caller.lat(k) for k in st['keys']),
                                     injected=u in faults)
        out['wall_seconds'] = time.time() - t1
        out['rate'] = rate
        core.write(sub / 'FAULT_RESULT.json', out)
        caller.close()
        q = {m: round(sum(1 for u in out[m] if out[m][u]['ok']) / len(tasks), 4) for m in ('router', 'static', 'dynamic')}
        print(json.dumps(dict(seed=seed, rate=rate, Q=q, wall=round(out['wall_seconds']),
                              new_calls=sum(1 for k in caller.by_key if k.startswith(('bf-s:', 'bf-d:')))), ensure_ascii=False))


def run():
    for seed in NEW_SEEDS:
        run_seed(seed)


if __name__ == '__main__':
    run()
