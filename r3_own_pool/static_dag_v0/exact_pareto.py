"""Exact Pareto Analysis on a Restricted Workflow Configuration Space (frozen protocol).

18 configs: (m_r, m_v) in {medium,large,coder}^2 x Z in {none, local-switch}.
Fixed: Y=dag, e1=large, e2=large. Fault rate 30%, 3 seeds.
Z=local-switch uses EXACTLY the Dynamic-Real recovery rules (memory rule for e,
r->large, v->large, one attempt, descendant closure, ungated).
Pareto: (Q, -C, -L). Reliability reported separately.

Outputs: adaptive_benchmark/exact_pareto/CONFIG_RESULTS.json + PARETO_ANALYSIS.md
"""
import fcntl
import hashlib
import json
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .multidag_dynamic import OUT, VPROMPT, close, json_value, parse_facts_safe, value_of
from .multidag_ablation import ABL
from .multidag_fullgraph import FG
from .multi_seed_run import build_faults
from .benchmark_run import BENCH, append

PARETO_DIR = BENCH / 'exact_pareto'
MODELS = ('medium', 'large', 'coder')
SEEDS = (20260923, 20260924, 20260925)
RATE = 0.3
N_TASKS = 120


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class CacheCaller:
    """Model-batching caller with (model,prompt) dedup and fault overrides."""

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
               [pathlib.Path(d) for d in sorted(glob.glob(str(BENCH / 'fault_pool')))]
        for d in dirs:
            p = d / 'RESPONSES.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_key[r['key']] = r
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


def run_config(m_r, m_v, z, seed, tasks, faults, resp, caller):
    """Execute one (m_r, m_v, z) config; return per-task (ok, used, lat)."""
    uids = [t['uid'] for t in tasks]
    gold = {t['uid']: t['answer'] for t in tasks}
    planned = {'e1': 'large', 'e2': 'large', 'r': m_r, 'v': m_v}

    # register faults for this config's planned models
    for u, (node, failing) in faults.items():
        ck = f'{node}:{u}'
        cu = (resp.get(ck) or {}).get('response', {}).get('usage')
        cl = (resp.get(ck) or {}).get('response', {}).get('latency_s')
        caller.set_fault(u, node, planned[node], failing, usage=cu, lat=cl)

    state = {}
    for t in tasks:
        u = t['uid']
        f1, _ = parse_facts_safe(caller.by_key.get(f'e1:{u}', {}).get('response', {}).get('answer', ''))
        f2, _ = parse_facts_safe(caller.by_key.get(f'e2:{u}', {}).get('response', {}).get('answer', ''))
        state[u] = dict(e1=f1, e2=f2, ok=None, keys=[f'e1:{u}', f'e2:{u}', f'r:{u}', f'v:{u}'],
                        question=t['question'], gold=t['answer'],
                        ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)

    def merged(st):
        return {'facts': st['e1']['facts'] + st['e2']['facts']}

    def latest(st, pfx):
        return [k for k in st['keys'] if k.split(':')[0] == pfx][-1]

    def call_node(st, u, node, model, key):
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

    # ---- initial pass: e1/e2 cached, execute r(m_r) and v(m_v) ----
    for node, model in (('r', m_r), ('v', m_v)):
        by_m = {}
        for t in tasks:
            u = t['uid']
            st = state[u]
            if node == 'r':
                # check if initial r key already exists in cache with correct model
                k = f'r:{u}'
                if k in caller.by_key and node == 'r':
                    pass  # initial key from base panel; model may differ
            by_m.setdefault(model, []).append(u)
        for m in sorted(by_m):
            for u in by_m[m]:
                st = state[u]
                key = f'ep:{node}:{u}:{m_r}_{m_v}_{z}_{seed}'
                call_node(st, u, node, m, key)
        if node == 'r':
            for t in tasks:
                st = state[t['uid']]
                refresh_expr(st)

    # ---- Z=none: score and return ----
    if z == 'none':
        results = {}
        for t in tasks:
            u = t['uid']
            st = state[u]
            vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
            ok = close(vv, gold[u])
            results[u] = dict(ok=ok, used=sum(caller.cost(k) for k in st['keys']),
                              lat=sum(caller.lat(k) for k in st['keys']))
        return results

    # ---- Z=local-switch (Dynamic-Real rules, frozen) ----
    # stage 1: e failures (memory rule)
    n_seen = 0
    e_jobs = []
    for t in tasks:
        u = t['uid']
        st = state[u]
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
            st = state[u]
            key = f'ep:{node}:{u}:esw_{seed}'
            call_node(st, u, node, m, key)
    e_affected = {u for u, _, _ in e_jobs}
    for u in sorted(e_affected):
        st = state[u]
        key = f'ep:r:{u}:eref_{seed}'
        call_node(st, u, 'r', 'medium', key)
        refresh_expr(st)

    # stage 2: r failure → large
    r_esc = [t['uid'] for t in tasks if r_value(state[t['uid']])[1]]
    for u in sorted(r_esc):
        st = state[u]
        key = f'ep:r:{u}:resc_{seed}'
        call_node(st, u, 'r', 'large', key)
        refresh_expr(st)

    # stage 3: v refresh for r-changed tasks
    r_changed = set()
    for t in tasks:
        u = t['uid']
        st = state[u]
        rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
        if len(rks) > 1:
            r_changed.add(u)
            key = f'ep:v:{u}:vref_{seed}'
            call_node(st, u, 'v', 'coder', key)

    # stage 4: v failure → large
    v_esc = []
    for t in tasks:
        u = t['uid']
        st = state[u]
        vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
        if close(vv, gold[u]):
            st['ok'] = True
            continue
        rv, rerr = r_value(st)
        v_fail = (vv is None) or (not rerr and not close(vv, rv))
        if v_fail:
            v_esc.append(u)
        else:
            st['ok'] = False
    for u in sorted(v_esc):
        st = state[u]
        key = f'ep:v:{u}:vesc_{seed}'
        call_node(st, u, 'v', 'large', key)
        vv = json_value(caller.by_key[key]['response']['answer'])
        st['ok'] = close(vv, gold[u])

    results = {}
    for t in tasks:
        u = t['uid']
        st = state[u]
        if st['ok'] is None:
            vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
            st['ok'] = close(vv, gold[u])
        results[u] = dict(ok=st['ok'], used=sum(caller.cost(k) for k in st['keys']),
                          lat=sum(caller.lat(k) for k in st['keys']))
    return results


def run():
    PARETO_DIR.mkdir(parents=True, exist_ok=True)
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks'][:N_TASKS]
    engine.OUT = PARETO_DIR
    caller = CacheCaller(PARETO_DIR)

    # load reference responses for fault usage
    resp = {}
    for f in (OUT, ABL, FG):
        for l in (f / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r

    all_results = {}
    t0 = time.time()
    try:
        for m_r in MODELS:
            for m_v in MODELS:
                for z in ('none', 'switch'):
                    cfg = f'{m_r}_{m_v}_{z}'
                    all_results[cfg] = {}
                    for seed in SEEDS:
                        faults = build_faults(seed, RATE, tasks)
                        res = run_config(m_r, m_v, z, seed, tasks, faults, resp, caller)
                        q = sum(1 for u in res if res[u]['ok']) / len(tasks)
                        c = sum(res[u]['used'] for u in res) / len(tasks)
                        print(json.dumps(dict(cfg=cfg, seed=seed, Q=round(q, 4),
                                              tokens=round(c, 0))), flush=True)
                        all_results[cfg][seed] = res
        core.write(PARETO_DIR / 'CONFIG_RESULTS.json',
                   dict(wall_seconds=time.time() - t0, results=all_results))
        print(json.dumps(dict(done=True, wall=round(time.time() - t0))))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
