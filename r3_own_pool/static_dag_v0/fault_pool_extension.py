"""DV/FR fault-scenario extension: enrich the candidate pool under faults.

Two new arms executed under the SAME fault injections (same seeds/rates/pools)
as the main benchmark, using the corrected Caller (persistent fault override
on (task,node,planned-model)) from multi_seed_run:

FR (Full Replay under faults): deployable detection identical to RD; every fired
  event (e fb / r esc / v esc) triggers a FULL-graph re-execution round (all four
  nodes; triggering node gets its recovery model, others keep current models),
  mirroring the clean multidag_fullgraph round structure (at most e/r/v rounds).

DV (Dynamic+Verifier under faults): RD stages plus the r second opinion (coder,
same facts); reasoning-failure signal = both execute and disagree -> r escalates
to large. Same memory rule, budget-free, one recovery attempt per node.

Output: adaptive_benchmark/fault_pool/fp{p}_s{seed}.json with per-task results
for both arms + the faulted map. Analysis in pool_analysis.py (separate).
"""
import json
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .multidag_dynamic import OUT, VPROMPT, close, json_value, parse_facts_safe, value_of
from .multidag_ablation import ABL
from .multidag_fullgraph import FG, PLANNED
from .multi_seed_run import Caller, build_faults
from .benchmark_run import BENCH, append

POOL_DIR = BENCH / 'fault_pool'
RATES = (0.1, 0.2, 0.3)
SEEDS = (20260923, 20260924, 20260925)


def load_resp():
    resp = {}
    for f in (OUT, ABL, FG):
        for l in (f / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r
    return resp


def run_combo(seed, rate, tasks, resp):
    sub = POOL_DIR / f'fp{int(rate*100)}_s{seed}'
    sub.mkdir(parents=True, exist_ok=True)
    caller = Caller(sub)
    t0 = time.time()
    try:
        faults = build_faults(seed, rate, tasks)
        gold = {t['uid']: t['answer'] for t in tasks}
        # register persistent faults + replace initial keys
        for u, (node, failing) in faults.items():
            ck = f'{node}:{u}'
            caller.by_key[ck] = dict(key=ck, model=PLANNED[node],
                                     response=dict(status='delivered', answer=failing,
                                                   usage=resp[ck]['response'].get('usage'),
                                                   latency_s=resp[ck]['response'].get('latency_s'),
                                                   injected_fault=True))
            caller.set_fault(u, node, PLANNED[node], failing,
                             clean_usage=resp[ck]['response'].get('usage'),
                             clean_lat=resp[ck]['response'].get('latency_s'))
        init = {}
        for t in tasks:
            u = t['uid']
            f1, _ = parse_facts_safe(caller.by_key[f'e1:{u}']['response']['answer'])
            f2, _ = parse_facts_safe(caller.by_key[f'e2:{u}']['response']['answer'])
            init[u] = dict(f1=f1, f2=f2)

        def make_state():
            st = {}
            for t in tasks:
                u = t['uid']
                st[u] = dict(e1=init[u]['f1'], e2=init[u]['f2'], ok=None, events=[], rounds=[],
                             keys=[f'e1:{u}', f'e2:{u}', f'r:{u}', f'v:{u}'],
                             node_model=dict(PLANNED), question=t['question'], gold=t['answer'],
                             ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)
            return st

        def merged(st):
            return {'facts': st['e1']['facts'] + st['e2']['facts']}

        def latest(st, pfx):
            return [k for k in st['keys'] if k.split(':')[0] == pfx][-1]

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
            st['node_model'][node] = model

        def r_value(st):
            return value_of(caller.by_key[latest(st, 'r')]['response']['answer'], merged(st))

        def refresh_expr(st):
            val, err = r_value(st)
            st['expr_text'] = 'UNPARSEABLE' if err else v.decode(caller.by_key[latest(st, 'r')]['response']['answer'])['expression']
            return (not err) and close(val, st['gold'])

        def final_ok(st, u):
            if st['ok'] is None:
                vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
                st['ok'] = close(vv, gold[u])
            return st['ok']

        # ================= FR arm =================
        fr = make_state()
        n_seen = 0
        e_jobs = []
        for t in tasks:
            u = t['uid']
            st = fr[u]
            for node in ('e1', 'e2'):
                if st[node]['facts']:
                    continue
                m = 'medium' if n_seen > 0 else 'coder'
                n_seen += 1
                e_jobs.append((u, node, m))
        e_tasks = sorted({u for u, _, _ in e_jobs})
        job_model = {(u, n): m for u, n, m in e_jobs}

        def exec_round(ts, tag, override):
            for node in ('e1', 'e2', 'r', 'v'):
                by_m = {}
                for u in ts:
                    st = fr[u]
                    m = override(u, node) or st['node_model'][node]
                    by_m.setdefault(m, []).append(u)
                for m in sorted(by_m):
                    for u in by_m[m]:
                        st = fr[u]
                        key = f'{node}:fx:{u}:{tag}'
                        call_into(st, u, node, m, key)
                if node == 'r':
                    for u in ts:
                        st = fr[u]
                        st['expr_text'] = None
                        refresh_expr(st)

        if e_tasks:
            exec_round(e_tasks, 'e', lambda u, node: job_model.get((u, node)))
        r_tasks = [t['uid'] for t in tasks if r_value(fr[t['uid']])[1]]
        if r_tasks:
            exec_round(r_tasks, 'r', lambda u, node: 'large' if node == 'r' else None)
        v_tasks = []
        for t in tasks:
            u = t['uid']
            st = fr[u]
            vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
            if close(vv, t['answer']):
                st['ok'] = True
                continue
            rv, rerr = r_value(st)
            if (vv is None) or (not rerr and not close(vv, rv)):
                v_tasks.append(u)
            else:
                st['ok'] = False
        if v_tasks:
            exec_round(v_tasks, 'v', lambda u, node: 'large' if node == 'v' else None)
        fr_out = {}
        for t in tasks:
            u = t['uid']
            st = fr[u]
            fr_out[u] = dict(ok=final_ok(st, u),
                             used=sum(caller.cost(k) for k in st['keys']),
                             lat=sum(caller.lat(k) for k in st['keys']),
                             keys=st['keys'], n_round_keys=sum(1 for k in st['keys'] if ':fx:' in k))

        # ================= DV arm =================
        dv = make_state()
        n_seen2 = 0
        for t in tasks:
            u = t['uid']
            st = dv[u]
            for node in ('e1', 'e2'):
                if st[node]['facts']:
                    continue
                m = 'medium' if n_seen2 > 0 else 'coder'
                n_seen2 += 1
                call_into(st, u, node, m, f'{node}:dvx:{u}:fb')
        aff = {t['uid'] for t in tasks if len([k for k in dv[t['uid']]['keys'] if k.split(':')[0] in ('e1', 'e2')]) > 4}
        for t in tasks:
            u = t['uid']
            st = dv[u]
            if u in aff:
                call_into(st, u, 'r', 'medium', f'r:dvx:{u}:fb-d')
                refresh_expr(st)
        esc = []
        for t in tasks:
            u = t['uid']
            st = dv[u]
            rv, rerr = r_value(st)
            fail = rerr
            if not rerr:
                caller.call(f'r2:dvx:{u}', 'coder', v.sprompt(dict(question=st['question']), merged(st)), uid=u, node='r')
                st['keys'].append(f'r2:dvx:{u}')
                sv, serr = value_of(caller.by_key[f'r2:dvx:{u}']['response']['answer'], merged(st))
                if not serr and not close(rv, sv):
                    fail = True
            if fail:
                esc.append(u)
            refresh_expr(st)
        for u in esc:
            st = dv[u]
            call_into(st, u, 'r', 'large', f'r:dvx:{u}:esc')
            refresh_expr(st)
        for t in tasks:
            u = t['uid']
            st = dv[u]
            rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
            if len(rks) > 1:
                call_into(st, u, 'v', 'coder', f'v:dvx:{u}:fb-d')
        vesc = []
        for t in tasks:
            u = t['uid']
            st = dv[u]
            vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
            if close(vv, t['answer']):
                st['ok'] = True
                continue
            rv, rerr = r_value(st)
            if (vv is None) or (not rerr and not close(vv, rv)):
                vesc.append(u)
            else:
                st['ok'] = False
        for u in vesc:
            st = dv[u]
            call_into(st, u, 'v', 'large', f'v:dvx:{u}:esc')
            vv = json_value(caller.by_key[latest(st, 'v')]['response']['answer'])
            st['ok'] = close(vv, gold[u])
        dv_out = {}
        for t in tasks:
            u = t['uid']
            st = dv[u]
            dv_out[u] = dict(ok=final_ok(st, u),
                             used=sum(caller.cost(k) for k in st['keys']),
                             lat=sum(caller.lat(k) for k in st['keys']),
                             keys=st['keys'])

        core.write(sub / 'POOL_RESULT.json', dict(
            seed=seed, rate=rate, faulted={u: faults[u][0] for u in faults},
            fr=fr_out, dv=dv_out, wall_seconds=time.time() - t0))
        q = {m: round(sum(1 for u in fr_out if x[u]['ok']) / len(tasks), 4) for m, x in (('fr', fr_out), ('dv', dv_out))}
        print(json.dumps(dict(seed=seed, rate=rate, Q=q, wall=round(time.time() - t0)), ensure_ascii=False))
    finally:
        caller.close()


def run():
    resp = load_resp()
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    for rate in RATES:
        for seed in SEEDS:
            run_combo(seed, rate, tasks, resp)


if __name__ == '__main__':
    run()
