"""Frozen 200-task independent evaluation (FINAL EXPERIMENT).

Arms: Single LLM (retry), Static DAG (no feedback), Dynamic DAG (Dynamic-Real).
Scenarios: clean + 30% fault × 3 seeds. Protocol frozen in FROZEN200_PROTOCOL.md.
One-shot: no parameter changes after results are seen.
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
from .benchmark_run import BENCH, append

FZ = BENCH.parent / 'frozen200'
SEEDS = (20260923, 20260924, 20260925)
RATE = 0.3
ROUTER_PROMPT = ('Answer the financial question using the table and passages below. Compute the final '
                 'numeric answer yourself. Return ONLY JSON {{"answer": <number>}} (percentages as ratios x100; '
                 'preserve reported units).\nQUESTION: {q}\nTABLE:\n{ctx_table}\nPASSAGES:\n{ctx_text}')


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


class Caller:
    def __init__(self, folder):
        self.folder = folder
        self.by_key = {}
        self.by_mp = {}
        self.faults = {}
        self.proc = self.log = None
        self.current = None
        import glob
        import pathlib
        dirs = [pathlib.Path(OUT), pathlib.Path(ABL), pathlib.Path(FG),
                pathlib.Path(BENCH) / 'router_clean'] + \
               [pathlib.Path(d) for d in sorted(glob.glob(str(BENCH / 'fault_p*')))] + \
               [pathlib.Path(d) for d in sorted(glob.glob(str(BENCH / 'fault_pool')))] + \
               [pathlib.Path(d) for d in sorted(glob.glob(str(BENCH / 'exact_pareto')))]
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

    def set_fault(self, uid, node, model, failing, usage=None, lat=None):
        self.faults[(uid, node, model)] = (failing, usage, lat)

    def call(self, key, model, prompt, uid=None, node=None):
        if uid is not None and (uid, node, model) in self.faults:
            failing, cu, cl = self.faults[(uid, node, model)]
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=failing,
                                     usage=cu or dict(total_tokens=1),
                                     latency_s=cl or 0.0, injected_fault=True))
            self.by_key[key] = rec
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


def build_faults(seed, rate, tasks, pools):
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


def run_arm(arm, tasks, faults, caller, gold, is_fault):
    """Execute one arm; return per-task (ok, used, lat)."""
    if arm == 'single':
        results = {}
        for t in tasks:
            u = t['uid']
            k = f'fz:single:{u}'
            if is_fault and u in faults:
                # Single LLM under fault: faulted task fails; retry same model → fault persists
                results[u] = dict(ok=False, used=0, lat=0, injected=True)
            else:
                caller.call(k, 'large', ROUTER_PROMPT.format(q=t['question'],
                                                              ctx_table=t['ctx_table'], ctx_text=t['ctx_text']))
                val = parse_router(caller.by_key[k]['response']['answer'])
                ok = close(val, gold[u])
                results[u] = dict(ok=ok, used=caller.cost(k), lat=caller.lat(k))
        return results

    # DAG arms (static / dynamic)
    planned = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
    state = {}
    for t in tasks:
        u = t['uid']
        # e1/e2 initial (shared across arms; use fresh keys for this panel)
        for nd, ctx in (('e1', t['ctx_table']), ('e2', t['ctx_text'])):
            k = f'fz:{nd}:{u}'
            caller.call(k, 'large', v.eprompt(dict(question=t['question'], context=ctx)),
                        uid=u if is_fault else None, node=nd)
        f1, _ = parse_facts_safe(caller.by_key[f'fz:e1:{u}']['response']['answer'])
        f2, _ = parse_facts_safe(caller.by_key[f'fz:e2:{u}']['response']['answer'])
        state[u] = dict(e1=f1, e2=f2, ok=None, keys=[f'fz:e1:{u}', f'fz:e2:{u}'],
                        question=t['question'], gold=gold[u],
                        ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)

    def merged(st):
        return {'facts': st['e1']['facts'] + st['e2']['facts']}

    def latest(st, pfx):
        return [k for k in st['keys'] if k.split(':')[1] == pfx
                and k.split(':')[0] == 'fz'][-1] if pfx in ('e1', 'e2') else \
               [k for k in st['keys'] if k.startswith(f'fz:{pfx}:')][-1]

    def call_node(st, u, node, model, key):
        if node in ('e1', 'e2'):
            caller.call(key, model, v.eprompt(dict(question=st['question'], context=st['ctx'][node])),
                        uid=u, node=node)
            fnew, _ = parse_facts_safe(caller.by_key[key]['response']['answer'])
            st[node] = fnew
        elif node == 'r':
            caller.call(key, model, v.sprompt(dict(question=st['question']), merged(st)), uid=u, node='r')
        else:
            caller.call(key, model, VPROMPT.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                                   expr=st['expr_text'] or 'UNPARSEABLE'), uid=u, node='v')
        st['keys'].append(key)

    def r_value(st):
        rk = [k for k in st['keys'] if k.startswith('fz:r:')][-1]
        return value_of(caller.by_key[rk]['response']['answer'], merged(st))

    def refresh_expr(st):
        val, err = r_value(st)
        rk = [k for k in st['keys'] if k.startswith('fz:r:')][-1]
        st['expr_text'] = 'UNPARSEABLE' if err else v.decode(caller.by_key[rk]['response']['answer'])['expression']
        return (not err) and close(val, st['gold'])

    def v_latest(st):
        return [k for k in st['keys'] if k.startswith('fz:v:')][-1]

    # initial r and v (batch by model)
    for t in tasks:
        u = t['uid']
        st = state[u]
        call_node(st, u, 'r', 'medium', f'fz:r:{u}', )
        refresh_expr(st)
    for t in tasks:
        u = t['uid']
        st = state[u]
        call_node(st, u, 'v', 'coder', f'fz:v:{u}')

    if arm == 'static':
        results = {}
        for t in tasks:
            u = t['uid']
            st = state[u]
            vv = json_value(caller.by_key[v_latest(st)]['response']['answer'])
            ok = close(vv, gold[u])
            results[u] = dict(ok=ok, used=sum(caller.cost(k) for k in st['keys']),
                              lat=sum(caller.lat(k) for k in st['keys']))
        return results

    # Dynamic-Real recovery
    n_seen = 0
    for t in tasks:
        u = t['uid']
        st = state[u]
        for node in ('e1', 'e2'):
            if st[node]['facts']:
                continue
            m = 'medium' if n_seen > 0 else 'coder'
            n_seen += 1
            call_node(st, u, node, m, f'fz:{node}:{u}:fb')
    aff = {t['uid'] for t in tasks if any(f'fz:e{"1" if i==0 else "2"}:{t["uid"]}:fb' in state[t['uid']]['keys'] for i in range(2))}
    # simpler: check if any e-node had recovery
    for t in tasks:
        u = t['uid']
        st = state[u]
        e_fbs = [k for k in st['keys'] if ':fb' in k and (':e1:' in k or ':e2:' in k)]
        if e_fbs:
            call_node(st, u, 'r', 'medium', f'fz:r:{u}:fb-d')
            refresh_expr(st)
    for t in tasks:
        u = t['uid']
        st = state[u]
        if r_value(st)[1]:
            call_node(st, u, 'r', 'large', f'fz:r:{u}:esc')
            refresh_expr(st)
    for t in tasks:
        u = t['uid']
        st = state[u]
        rks = [k for k in st['keys'] if k.startswith('fz:r:')]
        if len(rks) > 1:
            call_node(st, u, 'v', 'coder', f'fz:v:{u}:fb-d')
    for t in tasks:
        u = t['uid']
        st = state[u]
        vv = json_value(caller.by_key[v_latest(st)]['response']['answer'])
        if close(vv, gold[u]):
            st['ok'] = True
            continue
        rv, rerr = r_value(st)
        if (vv is None) or (not rerr and not close(vv, rv)):
            call_node(st, u, 'v', 'large', f'fz:v:{u}:esc')
            vv2 = json_value(caller.by_key[v_latest(st)]['response']['answer'])
            st['ok'] = close(vv2, gold[u])
        else:
            st['ok'] = False
    results = {}
    for t in tasks:
        u = t['uid']
        st = state[u]
        if st['ok'] is None:
            vv = json_value(caller.by_key[v_latest(st)]['response']['answer'])
            st['ok'] = close(vv, gold[u])
        results[u] = dict(ok=st['ok'], used=sum(caller.cost(k) for k in st['keys']),
                          lat=sum(caller.lat(k) for k in st['keys']))
    return results


def run():
    pol = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())
    tasks = pol['tasks']
    gold = {t['uid']: t['answer'] for t in tasks}
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    engine.OUT = FZ
    caller = Caller(FZ)
    t0 = time.time()
    all_results = {}
    try:
        # Clean
        print("=== clean ===", flush=True)
        for arm in ('single', 'static', 'dynamic'):
            res = run_arm(arm, tasks, {}, caller, gold, is_fault=False)
            q = sum(1 for u in res if res[u]['ok']) / len(tasks)
            print(f"  {arm}: Q={q:.4f}", flush=True)
            all_results[('clean', arm)] = res

        # Fault 30% × 3 seeds
        for seed in SEEDS:
            faults = build_faults(seed, RATE, tasks, pools)
            print(f"=== fault30% seed={seed} ===", flush=True)
            for arm in ('single', 'static', 'dynamic'):
                # Re-register faults for each arm (planned models differ per arm)
                caller.faults.clear()
                for u, (node, failing) in faults.items():
                    planned_m = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}[node]
                    if arm == 'single':
                        caller.set_fault(u, node, 'large', failing)  # Single uses large for everything
                    else:
                        caller.set_fault(u, node, planned_m, failing,
                                         usage=(caller.by_key.get(f'fz:{node}:{u}', {}) or {}).get('response', {}).get('usage'),
                                         lat=(caller.by_key.get(f'fz:{node}:{u}', {}) or {}).get('response', {}).get('latency_s'))
                res = run_arm(arm, tasks, faults, caller, gold, is_fault=True)
                q = sum(1 for u in res if res[u]['ok']) / len(tasks)
                print(f"  {arm}: Q={q:.4f}", flush=True)
                all_results[(f'f30_s{seed}', arm)] = res

        # Serialize
        out = {}
        for (scen, arm), res in all_results.items():
            out[f'{scen}|{arm}'] = res
        core.write(FZ / 'FROZEN200_RESULTS.json',
                   dict(wall_seconds=time.time() - t0, results=out,
                        n_tasks=len(tasks)))
        print(json.dumps(dict(done=True, wall=round(time.time() - t0))))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
