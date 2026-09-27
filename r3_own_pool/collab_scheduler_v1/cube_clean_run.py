"""Reference Cube Stage 1 (B-prime): clean-state unified evaluator.

15 legal configs on the frozen200 200-task panel under s_clean. Unified
workflow objectives (Q_workflow, C_workflow, L_critical_path) — Q from each
topology's OWN final producer (SER: r-value; SERV/ParallelER-v/DynamicDAG:
v-value or r-value per topology output definition), C = sum of node tokens
(cold-run accounting from recorded usage, cache only avoids re-execution),
L = critical path (parallel e1/e2 -> max).

Clean dedup (frozen rule): DynamicDAG NONE and LOCAL_REROUTE share the
execution path without faults -> one evaluation, reported under both labels.
Cache boundary (frozen rule): only pure model executions cached, keyed by
(model, prompt_sha); seeded from frozen200/RESPONSES.jsonl (the heterogeneous
DynamicDAG initial path) + this run's own ledger.
"""
import fcntl
import hashlib
import json
import time
from pathlib import Path

from static_dag_v0 import run as engine
from static_dag_v0 import tool_aware_v1 as v
from static_dag_v0.multidag_dynamic import (VPROMPT, close, json_value,
                                            parse_facts_safe, value_of)

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/cube_clean'
F200 = ROOT / 'static_dag_v0/frozen200'

X_MAP = {
    'BALANCED': {'e': 'medium', 'r': 'large', 'v': 'medium'},
    'HETEROGENEOUS': {'e': 'large', 'r': 'medium', 'v': 'coder'},
    'QUALITY': {'e': 'large', 'r': 'large', 'v': 'large'},
}
TOPOS = ['SER', 'SERV', 'PARALLELER', 'DYNAMICDAG']


class Caller:
    def __init__(self):
        self.by_mp = {}
        self.by_key = {}
        seed = F200 / 'RESPONSES.jsonl'
        if seed.exists():
            for l in seed.read_text().splitlines():
                r = json.loads(l)
                self.by_key[r['key']] = r
        own = OUT / 'RESPONSES.jsonl'
        if own.exists():
            for l in own.read_text().splitlines():
                r = json.loads(l)
                self.by_key[r['key']] = r
        self.new_calls = []

    def cost(self, key):
        return float(self.by_key[key]['response'].get('usage', {}).get('total_tokens', 0) or 0)

    def lat(self, key):
        return float(self.by_key[key]['response'].get('latency_s', 0) or 0)

    def answer(self, key):
        return self.by_key[key]['response'].get('answer', '')


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.OUT = OUT
    pol = json.loads((F200 / 'FROZEN200_POLICY.json').read_text())
    tasks = pol['tasks']
    caller = Caller()
    req_path = OUT / 'REQUESTS.jsonl'
    resp_path = OUT / 'RESPONSES.jsonl'
    lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')

    def call(key, model, prompt):
        if key in caller.by_key:
            return
        mp = (model, hashlib.sha256(prompt.encode()).hexdigest())
        if mp in caller.by_mp:
            caller.by_key[key] = caller.by_mp[mp]
            return
        with req_path.open('a') as f:
            f.write(json.dumps(dict(key=key, model=model, prompt_sha256=mp[1],
                                    unix_time=time.time())) + '\n')
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp)
        with resp_path.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        caller.by_key[key] = rec
        caller.by_mp[mp] = rec
        caller.new_calls.append(key)

    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    proc = log = None
    current = None
    try:
        def ensure(model):
            nonlocal proc, log, current
            if model != current:
                if proc is not None:
                    engine.stop_model(proc, log)
                proc, log, _ = engine.start_model(model)
                current = model

        def batched(jobs):
            for model in sorted({m for m, _, _ in jobs}):
                ensure(model)
                for m, key, prompt in jobs:
                    if m == model:
                        call(key, model, prompt)

        # ---------- phase E: extraction prompts ----------
        jobs = []
        for t in tasks:
            uid = t['uid']
            full_ctx = t['ctx_table'] + '\n' + t['ctx_text']
            for fam, xm in X_MAP.items():
                em = xm['e']
                jobs.append((em, f'cube:SER:{fam}:e:{uid}',
                             v.eprompt(dict(question=t['question'], context=full_ctx))))
                for nd, ctx in (('e1', t['ctx_table']), ('e2', t['ctx_text'])):
                    jobs.append((em, f'cube:PAR:{fam}:{nd}:{uid}',
                                 v.eprompt(dict(question=t['question'], context=ctx))))
        batched(jobs)
        print('phase E done', flush=True)

        # ---------- phase R: reasoning ----------
        jobs = []
        rctx = {}
        for t in tasks:
            uid = t['uid']
            for fam, xm in X_MAP.items():
                em, rm = xm['e'], xm['r']
                f_ser, _ = parse_facts_safe(caller.answer(f'cube:SER:{fam}:e:{uid}'))
                rctx[(uid, fam, 'SER')] = f_ser
                jobs.append((rm, f'cube:SER:{fam}:r:{uid}',
                             v.sprompt(dict(question=t['question']), f_ser)))
                f1, _ = parse_facts_safe(caller.answer(f'cube:PAR:{fam}:e1:{uid}'))
                f2, _ = parse_facts_safe(caller.answer(f'cube:PAR:{fam}:e2:{uid}'))
                merged = {'facts': f1['facts'] + f2['facts']}
                rctx[(uid, fam, 'PAR')] = merged
                jobs.append((rm, f'cube:PAR:{fam}:r:{uid}',
                             v.sprompt(dict(question=t['question']), merged)))
        batched(jobs)
        print('phase R done', flush=True)

        # ---------- phase V: verification (SERV + DYNAMICDAG) ----------
        jobs = []
        for t in tasks:
            uid = t['uid']
            for fam, xm in X_MAP.items():
                vm = xm['v']
                for topo, pfx in (('SERV', 'SER'), ('DYNAMICDAG', 'PAR')):
                    facts = rctx[(uid, fam, pfx)]
                    rkey = f'cube:{pfx}:{fam}:r:{uid}'
                    expr_txt = 'UNPARSEABLE'
                    try:
                        expr_txt = v.decode(caller.answer(rkey))['expression']
                    except Exception:
                        pass
                    jobs.append((vm, f'cube:{topo}:{fam}:v:{uid}',
                                 VPROMPT.format(q=t['question'], facts=json.dumps(facts['facts']),
                                                expr=expr_txt)))
        batched(jobs)
        print('phase V done', flush=True)

        # ---------- scoring ----------
        results = {}
        for topo in TOPOS + ['SINGLE']:
            for fam in X_MAP:
                zs = ['NONE'] if topo != 'DYNAMICDAG' else ['NONE', 'LOCAL_REROUTE']
                for z in zs:
                    cid = f'{topo}__{fam}__{z}__FRESH'
                    if topo == 'SINGLE':
                        continue
                    qs, cs, ls = [], [], []
                    for t in tasks:
                        uid = t['uid']
                        xm = X_MAP[fam]
                        try:
                            if topo == 'SER':
                                val, err = value_of(caller.answer(f'cube:SER:{fam}:r:{uid}'),
                                                    rctx[(uid, fam, 'SER')])
                                q = int(not err and close(val, t['answer']))
                                c = caller.cost(f'cube:SER:{fam}:e:{uid}') + \
                                    caller.cost(f'cube:SER:{fam}:r:{uid}')
                                l = caller.lat(f'cube:SER:{fam}:e:{uid}') + \
                                    caller.lat(f'cube:SER:{fam}:r:{uid}')
                            elif topo == 'PARALLELER':
                                val, err = value_of(caller.answer(f'cube:PAR:{fam}:r:{uid}'),
                                                    rctx[(uid, fam, 'PAR')])
                                q = int(not err and close(val, t['answer']))
                                c = caller.cost(f'cube:PAR:{fam}:e1:{uid}') + \
                                    caller.cost(f'cube:PAR:{fam}:e2:{uid}') + \
                                    caller.cost(f'cube:PAR:{fam}:r:{uid}')
                                l = max(caller.lat(f'cube:PAR:{fam}:e1:{uid}'),
                                        caller.lat(f'cube:PAR:{fam}:e2:{uid}')) + \
                                    caller.lat(f'cube:PAR:{fam}:r:{uid}')
                            else:  # SERV / DYNAMICDAG (clean: shared path, both Z labels)
                                pfx = 'SER' if topo == 'SERV' else 'PAR'
                                vval = json_value(caller.answer(f'cube:{topo}:{fam}:v:{uid}'))
                                q = int(vval is not None and close(vval, t['answer']))
                                c = sum(caller.cost(f'cube:{pfx}:{fam}:{nd}:{uid}')
                                        for nd in (('e',) if pfx == 'SER' else ('e1', 'e2'))) + \
                                    caller.cost(f'cube:{pfx}:{fam}:r:{uid}') + \
                                    caller.cost(f'cube:{topo}:{fam}:v:{uid}')
                                lex = [caller.lat(f'cube:{pfx}:{fam}:{nd}:{uid}')
                                       for nd in (('e',) if pfx == 'SER' else ('e1', 'e2'))]
                                l = max(lex) + caller.lat(f'cube:{pfx}:{fam}:r:{uid}') + \
                                    caller.lat(f'cube:{topo}:{fam}:v:{uid}')
                        except Exception:
                            q, c, l = 0, 0.0, 0.0
                        qs.append(q)
                        cs.append(c)
                        ls.append(l)
                    results[cid] = dict(Q=round(sum(qs) / len(qs), 4),
                                        C=round(sum(cs) / len(cs), 1),
                                        L=round(sum(ls) / len(ls), 3), n=len(qs))
        (OUT / 'CUBE_CLEAN.json').write_text(json.dumps(
            dict(results=results, new_calls=len(caller.new_calls),
                 single_anchor='SINGLE__QUALITY__RETRY__FRESH measured in frozen200 '
                               '(Q 0.55, C 612.8, L 0.46)'), indent=1))
        print(json.dumps(dict(new_calls=len(caller.new_calls), results=results), indent=1))
    finally:
        if proc is not None:
            engine.stop_model(proc, log)
        fcntl.flock(lock, fcntl.LOCK_UN)


if __name__ == '__main__':
    run()
