"""fault30 executor (reference cube stage 2, s_fault30) — v2 hardened.

Implements FAULT30_POLICY.json exactly, with three v2 robustness upgrades
added after the 2026-09-27 23:58 external kill of v1:

  R1 restart-safe cache seeding: the prompt cache also loads fault30's OWN
     ledger (delivered, non-injected), so a restart never re-executes calls
     the previous attempt already made
  R2 stage-batched execution: within each (seed, config), calls run in
     dependency stages, each batched by model (sorted) — semantics identical
     to the sequential walk (decisions depend only on recorded outputs and
     task order; same structure as multi_seed_run), but vLLM restarts drop
     from ~per-task to ~per-stage
  R3 incremental checkpointing: every completed (seed, config) evaluation is
     appended to FAULT30_ROWS.jsonl immediately; FAULT30_RESULTS.json is
     assembled from the checkpoint, so a crash loses nothing completed

Policy semantics (unchanged from v1): bit-identical fault draws; persistent
capability faults keyed (task, node, planned_model) served with clean-ref
cost; mandatory real downstream re-execution; per-(seed, config) isolation;
ungated detection + LOCAL_REROUTE recovery; critical-path L.

GATED: default is a structural dry run (zero calls). Real execution requires
BOTH `--execute` AND env FAULT30_EXECUTE=1, with the GPU lock free.

Run:  python3 -m collab_scheduler_v1.fault30_run                    # dry
      FAULT30_EXECUTE=1 python3 -m collab_scheduler_v1.fault30_run --execute
"""
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
FZ = ROOT / 'static_dag_v0/frozen200'
BENCH = ROOT / 'static_dag_v0/adaptive_benchmark'
OUT = ROOT / 'collab_scheduler_v1/fault30_prep'
ROWS = OUT / 'FAULT30_ROWS.jsonl'

sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.fault30_protocol import (  # noqa: E402
    CONFIGS, SEEDS, RATE, Ledger, build_faults, map_fault_node, planned_models)
from static_dag_v0.multidag_dynamic import close, json_value, value_of  # noqa: E402


class Executor:
    """Fault-aware caller with a pure-execution prompt cache (clean ledgers +
    fault30's own ledger + in-run) and per-(seed, config) fault registries."""

    def __init__(self, led, real, cost_fn, lat_fn):
        self.led = led
        self.real = real
        self.cost_fn = cost_fn
        self.lat_fn = lat_fn
        self.by_key = {}
        self.own_by_key = {}
        self.by_mp = dict(led.executed)  # (model, sha) -> executed key
        # R1: seed from fault30's own ledger so restarts reuse prior calls
        qp, rp = OUT / 'REQUESTS.jsonl', OUT / 'RESPONSES.jsonl'
        if qp.exists() and rp.exists():
            resp = {json.loads(l)['key']: json.loads(l)
                    for l in rp.read_text().splitlines() if l.strip()}
            for l in qp.read_text().splitlines():
                if not l.strip():
                    continue
                q = json.loads(l)
                r = resp.get(q['key'])
                if r is None:
                    continue
                response = r.get('response', {})
                if response.get('status') != 'delivered' or response.get('injected_fault'):
                    continue
                self.own_by_key[q['key']] = r
                self.by_mp.setdefault((q['model'], q['prompt_sha256']), q['key'])
        self.faults = {}
        self.proc = self.log = None
        self.current = None
        self.new_calls = 0
        self.reused_own = 0
        self.dry_new = 0
        self.lock = None

    def set_fault(self, uid, node, model, failing, usage, lat):
        self.faults[(uid, node, model)] = (failing, usage, lat)

    def clear_faults(self):
        self.faults = {}

    def _record(self, key, model, src_key):
        for store in (self.by_key, self.own_by_key):
            rec = store.get(src_key)
            if rec is not None:
                return dict(key=key, model=model, alias_of=src_key,
                            response=rec['response'])
        return dict(key=key, model=model, alias_of=src_key,
                    response=dict(status='delivered',
                                  answer=self.led.answer(src_key),
                                  usage=dict(total_tokens=self.cost_fn(src_key) or 0),
                                  latency_s=self.lat_fn(src_key) or 0.0))

    def call(self, key, model, prompt, uid=None, node=None):
        if uid is not None and (uid, node, model) in self.faults:
            failing, cu, cl = self.faults[(uid, node, model)]
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer=failing,
                                     usage=cu or dict(total_tokens=1),
                                     latency_s=cl or 0.0, injected_fault=True))
            self.by_key[key] = rec
            return rec
        mp = (model, hashlib.sha256(prompt.encode()).hexdigest())
        src_key = self.by_mp.get(mp)
        if src_key is not None:
            if src_key in self.own_by_key:
                self.reused_own += 1
            rec = self._record(key, model, src_key)
            self.by_key[key] = rec
            return rec
        if not self.real:
            self.dry_new += 1
            rec = dict(key=key, model=model,
                       response=dict(status='delivered', answer='',
                                     usage=dict(total_tokens=0), latency_s=0.0,
                                     dry_new=True))
            self.by_key[key] = rec
            self.by_mp[mp] = key
            return rec
        from static_dag_v0 import run as engine
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model
        with (OUT / 'REQUESTS.jsonl').open('a') as f:
            f.write(json.dumps(dict(key=key, model=model,
                                    prompt_sha256=mp[1], unix_time=time.time())) + '\n')
        resp = engine.call_model(model, prompt)
        if resp.get('status') != 'delivered':
            raise RuntimeError('Infrastructure failure: ' + key)
        rec = dict(key=key, model=model, response=resp)
        with (OUT / 'RESPONSES.jsonl').open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        self.by_key[key] = rec
        self.by_mp[mp] = key
        self.new_calls += 1
        return rec

    def answer(self, key):
        return self.by_key[key]['response']['answer']

    def cost(self, key):
        return float(self.by_key[key]['response'].get('usage', {}).get('total_tokens') or 0)

    def lat(self, key):
        return float(self.by_key[key]['response'].get('latency_s') or 0)

    def run_stage(self, jobs):
        """R2: execute one dependency stage's jobs grouped by model (sorted)."""
        for model in sorted({j['model'] for j in jobs}):
            for j in jobs:
                if j['model'] == model:
                    j['go']()

    def acquire_gpu(self):
        from static_dag_v0 import run as engine
        engine.OUT = OUT
        self.lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self):
        if self.proc is not None:
            from static_dag_v0 import run as engine
            engine.stop_model(self.proc, self.log)
            self.proc = None
        if self.lock is not None:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_UN)
            finally:
                self.lock.close()


def eval_config(cid, ex, led, tasks, faults, task_map):
    """Stage-batched evaluation of one (seed, config). Same calls, keys and
    decision rules as the sequential v1 walk; stage order A -> R1 -> (ER ->
    R2 -> R3) -> V1 -> (V2 -> V3) for LOCAL_REROUTE."""
    topo, fam, z, nodes = planned_models(cid)
    is_lr = z == 'LOCAL_REROUTE' and topo == 'DYNAMICDAG'
    st = {}
    for t in tasks:
        uid = t['uid']
        drawn = faults.get(uid)
        node = map_fault_node(drawn[0], topo) if drawn else None
        if node and node not in nodes:
            node = None
        st[uid] = dict(faulted=node is not None, node=node, facts={}, keys=[],
                       rkeys=[], vkeys=[], e_recovered=set())

    def k(uid, node, kind=None):
        return f'f30:{topo}:{fam}:{node}' + (f':{kind}' if kind else '') + f':{uid}'

    # ---- stage A: planned extraction (cache/injected; no server needed) ----
    jobs = []
    for t in tasks:
        uid = t['uid']
        if topo in ('SER', 'SERV'):
            def go(t=t, uid=uid):
                key = k(uid, 'e')
                ex.call(key, nodes['e'],
                        led.eprompt(t, t['ctx_table'] + '\n' + t['ctx_text']),
                        uid=uid if st[uid]['faulted'] else None, node='e')
                st[uid]['keys'].append(key)
                f, _ = led.parse_facts_safe(ex.answer(key))
                st[uid]['facts']['e'] = f
            jobs.append(dict(model=nodes['e'], go=go))
        else:
            for nd, ctx in (('e1', t['ctx_table']), ('e2', t['ctx_text'])):
                def go(t=t, uid=uid, nd=nd, ctx=ctx):
                    key = k(uid, nd)
                    ex.call(key, nodes[nd], led.eprompt(t, ctx),
                            uid=uid if st[uid]['faulted'] else None, node=nd)
                    st[uid]['keys'].append(key)
                    f, _ = led.parse_facts_safe(ex.answer(key))
                    st[uid]['facts'][nd] = f
                jobs.append(dict(model=nodes[nd], go=go))
    ex.run_stage(jobs)

    def merged(uid):
        if topo in ('SER', 'SERV'):
            return st[uid]['facts']['e']
        return {'facts': st[uid]['facts']['e1']['facts'] + st[uid]['facts']['e2']['facts']}

    # ---- stage R1: planned reasoning ----
    jobs = []
    for t in tasks:
        uid = t['uid']

        def go(uid=uid, t=t):
            key = k(uid, 'r')
            ex.call(key, nodes['r'], led.sprompt(t, merged(uid)),
                    uid=uid if st[uid]['faulted'] else None, node='r')
            st[uid]['keys'].append(key)
            st[uid]['rkeys'].append(key)
        jobs.append(dict(model=nodes['r'], go=go))
    ex.run_stage(jobs)

    def r_answer(uid):
        return ex.answer(st[uid]['rkeys'][-1])

    def r_value(uid, t):
        return value_of(r_answer(uid), merged(uid))

    def expr_of(uid, t):
        try:
            return led.v.decode(r_answer(uid))['expression']
        except Exception:
            return 'UNPARSEABLE'

    if is_lr:
        # ---- ER: e-recovery on empty facts (fault or natural), memory rule ----
        det = [t['uid'] for t in tasks
               if not st[t['uid']]['facts']['e1']['facts']
               or not st[t['uid']]['facts']['e2']['facts']]
        target = {uid: ('coder' if i == 0 else 'medium') for i, uid in enumerate(det)}
        jobs = []
        for uid in det:
            for nd in ('e1', 'e2'):
                if st[uid]['facts'][nd]['facts']:
                    continue

                def go(uid=uid, nd=nd):
                    t = task_map[uid]
                    old_facts = st[uid]['facts'][nd]['facts']
                    key = k(uid, nd, 'fb')
                    ex.call(key, target[uid],
                            led.eprompt(t, t['ctx_table'] if nd == 'e1' else t['ctx_text']),
                            uid=uid if st[uid]['faulted'] else None, node=nd)
                    st[uid]['keys'].append(key)
                    f, _ = led.parse_facts_safe(ex.answer(key))
                    st[uid]['facts'][nd] = f
                    # Track whether this fb actually CHANGED the facts
                    if f['facts'] != old_facts:
                        st[uid]['e_recovered'].add(nd)
                jobs.append(dict(model=target[uid], go=go))
        ex.run_stage(jobs)
        # ---- R2: r-refresh where e facts actually changed (descendant closure) ----
        chg = [t['uid'] for t in tasks if st[t['uid']]['e_recovered']]
        jobs = []
        for uid in chg:
            t = task_map[uid]

            def go(uid=uid, t=t):
                prev_answer = ex.answer(st[uid]['rkeys'][-1]) if st[uid]['rkeys'] else None
                key = k(uid, 'r', 'fbd')
                ex.call(key, nodes['r'], led.sprompt(t, merged(uid)),
                        uid=uid if st[uid]['faulted'] else None, node='r')
                st[uid]['keys'].append(key)
                st[uid]['rkeys'].append(key)
                new_answer = ex.answer(key)
                if new_answer != prev_answer:
                    st[uid]['r_changed'] = True
            jobs.append(dict(model=nodes['r'], go=go))
        ex.run_stage(jobs)
        # ---- R3: r-escalation on unparseable r (ungated) ----
        rerr = [t['uid'] for t in tasks if r_value(t['uid'], t)[1]]
        jobs = []
        for uid in rerr:
            t = task_map[uid]

            def go(uid=uid, t=t):
                prev_answer = ex.answer(st[uid]['rkeys'][-1]) if st[uid]['rkeys'] else None
                key = k(uid, 'r', 'esc')
                ex.call(key, 'large', led.sprompt(t, merged(uid)),
                        uid=uid if st[uid]['faulted'] else None, node='r')
                st[uid]['keys'].append(key)
                st[uid]['rkeys'].append(key)
                new_answer = ex.answer(key)
                if new_answer != prev_answer:
                    st[uid]['r_changed'] = True
            jobs.append(dict(model='large', go=go))
        ex.run_stage(jobs)
        # FINAL-state comparison: compare LAST r answer to ORIGINAL (pre-recovery)
        # r answer. Overrides the process-accumulated r_changed flag so that
        # R2=B, R3=A (restored to original) correctly yields r_changed=False.
        for t in tasks:
            uid = t['uid']
            if len(st[uid]['rkeys']) > 1:
                original = ex.answer(st[uid]['rkeys'][0])
                final = ex.answer(st[uid]['rkeys'][-1])
                # save process-level flag BEFORE overwriting with final state
                old_changed = st[uid].get('r_changed', False)
                st[uid]['r_process_changed'] = st[uid].get(
                    'r_process_changed', False) or old_changed
                st[uid]['r_changed'] = (final != original)

    # ---- stage V1: planned verification ----
    if 'v' in nodes:
        jobs = []
        for t in tasks:
            uid = t['uid']

            def go(uid=uid, t=t):
                key = k(uid, 'v')
                ex.call(key, nodes['v'],
                        led.vprompt(t, merged(uid)['facts'], expr_of(uid, t)),
                        uid=uid if st[uid]['faulted'] else None, node='v')
                st[uid]['keys'].append(key)
                st[uid]['vkeys'].append(key)
            jobs.append(dict(model=nodes['v'], go=go))
        ex.run_stage(jobs)

        if is_lr:
            # ---- V2: v-refresh where r output actually changed (descendant closure) ----
            # r_changed set populated in R2/R3 stages when r re-execution
            # produced a different answer than the previous r call
            rch = [t['uid'] for t in tasks if st[t['uid']].get('r_changed', False)]
            jobs = []
            for uid in rch:
                t = task_map[uid]

                def go(uid=uid, t=t):
                    key = k(uid, 'v', 'fbd')
                    ex.call(key, nodes['v'],
                            led.vprompt(t, merged(uid)['facts'], expr_of(uid, t)),
                            uid=uid if st[uid]['faulted'] else None, node='v')
                    st[uid]['keys'].append(key)
                    st[uid]['vkeys'].append(key)
                jobs.append(dict(model=nodes['v'], go=go))
            ex.run_stage(jobs)
            # ---- V3: v-escalation on v failure ----
            vfail = []
            for t in tasks:
                uid = t['uid']
                vv = json_value(ex.answer(st[uid]['vkeys'][-1]))
                rv, rre = r_value(uid, t)
                if (vv is None) or (not rre and not close(vv, rv)):
                    vfail.append(uid)
            jobs = []
            for uid in vfail:
                t = task_map[uid]

                def go(uid=uid, t=t):
                    key = k(uid, 'v', 'esc')
                    ex.call(key, 'large',
                            led.vprompt(t, merged(uid)['facts'], expr_of(uid, t)),
                            uid=uid if st[uid]['faulted'] else None, node='v')
                    st[uid]['keys'].append(key)
                    st[uid]['vkeys'].append(key)
                jobs.append(dict(model='large', go=go))
            ex.run_stage(jobs)

    # ---- scoring (critical-path L as in cube_clean) ----
    rows = {}
    for t in tasks:
        uid = t['uid']
        gold = t['answer']
        if 'v' in nodes:
            vv = json_value(ex.answer(st[uid]['vkeys'][-1]))
            ok = int(vv is not None and close(vv, gold))
        else:
            val, err = r_value(uid, t)
            ok = int(not err and close(val, gold))
        used = sum(ex.cost(kk) for kk in st[uid]['keys'])
        # Seven-layer accounting (protocol v3): distinguish logical vs physical
        logical_calls = len(st[uid]['keys'])
        injected_calls = sum(1 for kk in st[uid]['keys']
                             if ex.by_key.get(kk, {}).get('response', {})
                             .get('injected_fault'))
        real_calls = logical_calls - injected_calls
        cache_hits = sum(1 for kk in st[uid]['keys']
                         if ex.by_key.get(kk, {}).get('alias_of'))
        real_tokens = sum(ex.cost(kk) for kk in st[uid]['keys']
                          if not ex.by_key.get(kk, {}).get('response', {})
                          .get('injected_fault'))
        if topo in ('SER', 'SERV'):
            lats = [ex.lat(k(uid, 'e'))]
            if is_lr and k(uid, 'e', 'fb') in st[uid]['keys']:
                lats.append(ex.lat(k(uid, 'e', 'fb')))
        else:
            lats = []
            for nd in ('e1', 'e2'):
                base = ex.lat(k(uid, nd))
                if is_lr and k(uid, nd, 'fb') in st[uid]['keys']:
                    base = base + ex.lat(k(uid, nd, 'fb'))  # serial: attempt then recovery
                lats.append(base)
        l = max(lats) + sum(ex.lat(kk) for kk in st[uid]['rkeys']) \
            + sum(ex.lat(kk) for kk in st[uid]['vkeys'])
        rows[uid] = dict(ok=ok, used=used, lat=l, faulted=st[uid]['faulted'],
                         fault_node=st[uid]['node'], keys=st[uid]['keys'],
                         logical_calls=logical_calls, injected_calls=injected_calls,
                         real_calls=real_calls, cache_hits=cache_hits,
                         real_tokens=real_tokens,
                         r_changed_final=st[uid].get('r_changed', False),
                         r_process_changed=st[uid].get('r_process_changed', False))
    return rows


def load_checkpoint():
    done = set()
    if ROWS.exists():
        for l in ROWS.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                done.add((str(r['seed']), r['cid']))
    return done


def run():
    real = '--execute' in sys.argv and os.environ.get('FAULT30_EXECUTE') == '1'
    from collab_scheduler_v1 import cube_analyze
    tasks = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())['tasks']
    task_map = {t['uid']: t for t in tasks}
    pools = json.loads((BENCH / 'FAULT_POOLS.json').read_text())
    led = Ledger()
    _, cost_fn, lat_fn, *_ = cube_analyze.load_ledgers()
    ex = Executor(led, real, cost_fn, lat_fn)
    done = load_checkpoint()
    results = dict(policy=str((OUT / 'FAULT30_POLICY.json').resolve()),
                   mode='execute' if real else 'structural dry run (zero calls)',
                   seeds={})
    try:
        if real:
            ex.acquire_gpu()
        seeds_to_run = SEEDS if real else SEEDS[:1]
        for seed in seeds_to_run:
            faults = build_faults(seed, RATE, tasks, pools)
            for cid in CONFIGS:
                topo, fam, z, nodes = planned_models(cid)
                if (str(seed), cid) in done and real:
                    print(f'skip (checkpointed) seed {seed} {cid}', flush=True)
                    continue
                ex.clear_faults()
                for u, (node, failing) in faults.items():
                    mapped = map_fault_node(node, topo)
                    if not mapped or mapped not in nodes:
                        continue
                    ck = led.clean_key(topo, fam, mapped, u)
                    ex.set_fault(u, mapped, nodes[mapped], failing,
                                 usage=dict(total_tokens=cost_fn(ck) or 1),
                                 lat=lat_fn(ck) or 0.0)
                rows = eval_config(cid, ex, led, tasks, faults, task_map)
                if real:  # structural dry runs must never touch the checkpoint
                    with ROWS.open('a') as f:
                        f.write(json.dumps(dict(seed=seed, cid=cid, rows=rows)) + '\n')
                q = sum(r['ok'] for r in rows.values()) / len(rows)
                c = sum(r['used'] for r in rows.values()) / len(rows)
                l = sum(r['lat'] for r in rows.values()) / len(rows)
                print(f'seed {seed} {cid:46s} Q={q:.4f} C={c:.1f} L={l:.3f} '
                      f'new={ex.new_calls} reuse_own={ex.reused_own} '
                      f'dry_new={ex.dry_new}', flush=True)
                if not real:
                    break
            if not real:
                break
    finally:
        ex.release()
    if real:
        seeds_out = {}
        for l in ROWS.read_text().splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            seeds_out.setdefault(str(r['seed']), {})[r['cid']] = r['rows']
        results['seeds'] = seeds_out
        (OUT / 'FAULT30_RESULTS.json').write_text(json.dumps(results, indent=1))
        print('FAULT30_RESULTS.json written; total new_calls this process =',
              ex.new_calls)


if __name__ == '__main__':
    run()
