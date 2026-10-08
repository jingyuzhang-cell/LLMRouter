"""P1-B admission v2: fixes the six audit P0s in the execution adapter (zero calls).

Fixes over c4fff1a (audit 2026-10-09):
  F1 v-node protocol: VPROMPT returns {"value": ...} -> parsed with the REAL
     json_value semantics (was {"val"}); val-style fallbacks removed
  F2 facts flow: task facts (e1+e2) cached once and reused by r/r1/r2/v
     prompts (v no longer reads facts from r's expression-only output)
  F3 reroute REALLY recovers: on r-failure it re-executes reasoning with the
     escalated model ('large') as a billed call (local reroute semantics)
  F4 faults drawn ON THE 5 HELD-OUT UIDs (Random(20260923), 30% -> 2/5 tasks,
     node+pool draws per the frozen200 rule); registry traceable per task
  F5 token accounting: every delivered call's usage.total_tokens accumulated
     per track and reported (single arm included)
  F6 durability: ANY service exception still writes its ledger record;
     the GLOBAL counter is persisted to disk on every call (restart-safe)
Test hardening: T1b gold-leak = trajectory identical under perturbed gold;
T5 = node failure blocks pending successors -> status failed-no-ready.
Budget: smoke = 1 task x 4 strategies x 1 state -> cap 48; both states 96.
Real entry: gated (--execute + env P1B_EXECUTE=1 + GPU lock), not invoked here.
"""
import fcntl
import hashlib
import json
import random
import time
from pathlib import Path

import sys
ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.dag_patch_p0 import PatchError, RuntimeDAG  # noqa: E402
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402
from static_dag_v0.multidag_dynamic import json_value, parse_facts_safe, close as fclose  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/p1b'
OUT.mkdir(exist_ok=True)
LEDGER = OUT / 'LEDGER.jsonl'
GCOUNTER = OUT / 'GLOBAL_BUDGET_STATE.json'
PER_TASK_BUDGET = 12
SMOKE_CAP = 48          # 1 task x 4 strategies x 1 state (audit-corrected)
GLOBAL_BUDGET = 480     # whole-pilot hard ceiling


class BudgetExceeded(Exception):
    pass


class InfraFailure(Exception):
    pass


def _load_gc():
    if GCOUNTER.exists():
        return json.loads(GCOUNTER.read_text())
    return dict(n=0, cap=GLOBAL_BUDGET)


def _save_gc(gc):
    GCOUNTER.write_text(json.dumps(gc))


def _guard_succs_pending(g, nodes):
    for s in nodes:
        if g.nodes[s]['status'] != 'pending':
            raise PatchError(f'successor {s} already {g.nodes[s]["status"]} '
                             f'— dependency change forbidden')


_orig_insert, _orig_rewire = RuntimeDAG._insert, RuntimeDAG._rewire
RuntimeDAG._insert = lambda self, u, w, mw: (
    _guard_succs_pending(self, self._succs(u)), _orig_insert(self, u, w, mw))[1]
RuntimeDAG._rewire = lambda self, a, b: (
    _guard_succs_pending(self, [s for s in self._succs(a) if s != b]),
    _orig_rewire(self, a, b))[1]


class P1BExecutor:
    """Persisted ledger, restart-safe global counter, token accounting."""

    def __init__(self, service, task, strategy, gc):
        self.service, self.task, self.strategy, self.gc = service, task, strategy, gc
        self.calls = self.failed_calls = 0
        self.tokens = 0
        self.node_time = 0.0

    def call(self, node, model, prompt):
        if self.calls >= PER_TASK_BUDGET or self.gc['n'] >= self.gc['cap']:
            raise BudgetExceeded('budget guard')
        self.calls += 1
        self.gc['n'] += 1
        _save_gc(self.gc)
        key = f"p1b:{self.strategy}:{node}:{self.calls}:{self.task['uid'][:8]}"
        h = hashlib.sha256(prompt.encode()).hexdigest()
        t0 = time.monotonic()
        status, answer, usage = 'delivered', None, None
        try:
            resp = self.service(model, prompt)
            status = resp.get('status', 'delivered')
            answer, usage = resp.get('answer'), resp.get('usage')
        except Exception as e:                       # F6: still persists
            status, answer = 'service_exception', f'{type(e).__name__}: {e}'
        dt = time.monotonic() - t0
        rec = dict(key=key, node=node, model=model, prompt_sha256=h,
                   unix_time=time.time(), strategy=self.strategy,
                   response=dict(status=status, answer=answer, usage=usage,
                                 latency_s=dt))
        with LEDGER.open('a') as f:                  # append before any raise
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if status != 'delivered':
            self.failed_calls += 1
            raise InfraFailure(key)
        self.node_time += dt
        if usage:
            self.tokens += int(usage.get('total_tokens') or 0)      # F5
        return rec


def decomposer_prompt(task, facts):
    return ('You are solving a financial arithmetic question in two steps. '
            'STEP 1: compute only the FIRST arithmetic sub-result from the facts. '
            'Return ONLY JSON {"step1": <number>}.\nQUESTION: ' + task['question']
            + '\nFACTS: ' + json.dumps(facts))


def combiner_prompt(task, facts, step1):
    return ('STEP 2: finish the computation using the step-1 result. '
            'Return ONLY JSON {"val": <number>}.\nQUESTION: ' + task['question']
            + '\nFACTS: ' + json.dumps(facts) + f'\nSTEP1: {step1}')


def select_tasks(n=5, seed_tag='p1b', seed=20261009):
    import static_dag_v0.multidag_dynamic as md
    pool = md.hybrid_pool()
    ranked = sorted(pool, key=lambda t: hashlib.sha256(
        f'{seed_tag}:{seed}:{t["uid"]}'.encode()).hexdigest())
    out = []
    for t in ranked[:n]:
        d = dict(t)
        d['ctx_table'] = md.ctx_table(t['para'])
        d['ctx_text'] = md.ctx_text(t['para'])
        out.append(d)
    return out


def build_heldout_faults(tasks, seed=20260923, rate=0.3):
    """Same draw rule as frozen200, but ON the held-out UIDs (F4)."""
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json')
                       .read_text())
    rng = random.Random(seed)
    k = int(len(tasks) * rate)
    faulted = rng.sample([t['uid'] for t in tasks], k)
    faults = {}
    for u in faulted:
        node = rng.choice(['e1', 'e2', 'r', 'v'])
        pk = 'e' if node.startswith('e') else ('r' if node == 'r' else 'v')
        faults[u] = (node, pools[pk][rng.randrange(len(pools[pk]))])
    return faults


def _finish(log, ex, t0):
    log.update(end_to_end_wall_s=round(time.monotonic() - t0, 6),
               node_wall_s=round(ex.node_time, 6), n_calls=ex.calls,
               failed_calls=ex.failed_calls, total_tokens=ex.tokens)


def _apply_fault(u):
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json')
                       .read_text())
    pk = 'e' if u.startswith('e') else 'r'
    return {'facts': []} if pk == 'e' else pools[pk][0]


def _parse(u, ans):
    if u in ('e1', 'e2'):
        return parse_facts_safe(ans)[0]
    if u == 'r':
        try:
            from static_dag_v0 import tool_aware_v1 as v
            return dict(expr=v.decode(ans)['expression'])
        except Exception:
            return ans                                   # unparseable marker
    if u == 'r1':
        try:
            return dict(step1=float(json.loads(ans)['step1']))
        except Exception:
            return ans
    if u == 'r2':
        try:
            return dict(val=float(json.loads(ans)['val']))
        except Exception:
            return ans
    try:                                                  # F1: {"value": ...}
        return dict(value=float(json.loads(ans)['value']))
    except Exception:
        return dict(raw=ans)


def run_track(service, task, strategy, led, faults, gc):
    t0 = time.monotonic()
    ex = P1BExecutor(service, task, strategy, gc)
    gold = task['answer']                       # post-hoc scoring ONLY
    log = dict(task_uid=task['uid'], strategy=strategy, status='completed',
               executed=[], events=[], patches=[], scheduler_overhead_s=0.0)
    if strategy == 'single':
        from static_dag_v0.frozen200_run import ROUTER_PROMPT, parse_router
        rec = ex.call('single', 'large', ROUTER_PROMPT.format(
            q=task['question'], ctx_table=task['ctx_table'],
            ctx_text=task['ctx_text']))
        val = parse_router(rec['response']['answer'])
        log['executed'] = ['single']
        log['final_quality'] = int(val is not None and fclose(val, gold))
        _finish(log, ex, t0)
        return log

    g = RuntimeDAG({'e1': dict(deps=[], model='large'),
                    'e2': dict(deps=[], model='large'),
                    'r': dict(deps=['e1', 'e2'], model='medium'),
                    'v': dict(deps=['r'], model='coder')})
    fault = faults.get(task['uid'])
    facts_cache = {'facts': []}

    def detect(u, out):
        if u == 'r' and not isinstance(out, dict):
            return dict(kind='r unparseable', diagnosis='reasoning failure')
        return None

    try:
        while True:
            ready = g.ready()
            if not ready:
                if any(n['status'] in ('pending', 'failed')
                       for n in g.nodes.values()):
                    log['status'] = 'failed-no-ready'
                break
            u = sorted(ready)[0]
            if u in ('e1', 'e2'):
                ctx = task['ctx_table'] if u == 'e1' else task['ctx_text']
                prompt = led.eprompt(task, ctx)
                model = g.nodes[u]['model']
            elif u == 'r':
                prompt = led.sprompt(task, {'facts': facts_cache['facts']})
                model = g.nodes[u]['model']
            elif u == 'r1':
                prompt = decomposer_prompt(task, facts_cache['facts'])
                model = 'large'
            elif u == 'r2':
                prompt = combiner_prompt(task, facts_cache['facts'],
                                         g.nodes['r1']['output']['step1'])
                model = 'large'
            else:
                src = g.nodes[[p for p in g.nodes[u]['deps']][0]]['output']
                expr = src.get('expr') if isinstance(src, dict) else None
                if 'r1' in g.nodes:
                    expr = f'split-chain(step1={g.nodes["r1"]["output"].get("step1")})'
                prompt = led.vprompt(task, facts_cache['facts'],
                                     expr or 'UNPARSEABLE')
                model = g.nodes[u]['model']
            ts = time.monotonic()
            if fault and fault[0] == u:
                ex.call(u, g.nodes[u]['model'], prompt)      # billed attempt
                out = _apply_fault(u)
                g.nodes[u].update(status='done', output=out)
            else:
                rec = ex.call(u, model, prompt)
                out = _parse(u, rec['response']['answer'])
                g.nodes[u].update(status='done', output=out)
            if u in ('e1', 'e2') and isinstance(out, dict):
                facts_cache['facts'] += out.get('facts', [])
            log['executed'].append(u)
            ev = detect(u, out)
            log['scheduler_overhead_s'] += time.monotonic() - ts
            if ev:
                log['events'].append(dict(executed=u, **ev))
                tp = time.monotonic()
                if strategy == 'dynpatch' and ev['diagnosis'] == 'reasoning failure':
                    log['patches'].append(dict(decision='split r',
                                               **g.split_node('r', 'r1', 'r2',
                                                              'large', 'large')))
                elif strategy == 'reroute' and ev['diagnosis'] == 'reasoning failure':
                    rec2 = ex.call('r_esc', 'large',
                                   led.sprompt(task, {'facts': facts_cache['facts']}))
                    g.nodes['r'].update(
                        status='done', output=_parse('r', rec2['response']['answer']))
                    log['executed'].append('r_esc')
                    log['events'].append(dict(executed='r_esc',
                                              kind='escalated rerun',
                                              diagnosis='local-reroute recovery'))
                log['scheduler_overhead_s'] += time.monotonic() - tp
    except InfraFailure:
        log['status'] = 'failed-no-ready' if any(
            n['status'] == 'pending' for n in g.nodes.values()) else 'aborted-infra'
    except BudgetExceeded as e:
        log['status'] = f'aborted-budget: {e}'
    final = g.nodes.get('v', {}).get('output')
    val = json_value(json.dumps(final)) if isinstance(final, dict) else None
    log['final_quality'] = int(val is not None and fclose(val, gold))
    _finish(log, ex, t0)
    return log


GOOD = {'facts': '{"facts": [{"value": 1.5, "evidence": "a"}, {"value": 2.5, "evidence": "b"}]}',
        'expr': '{"expression": "v0+v1"}', 'step1': '{"step1": 4.0}',
        'val': '{"val": 4.0}', 'vval': '{"value": 4.0}',
        'router': '{"answer": 4.0}'}


def _pkind(prompt):
    for k, sig in (('facts', 'extract the quantities'),
                   ('expr', 'arithmetic reasoning'), ('step1', 'STEP 1'),
                   ('val', 'STEP 2'), ('vval', 'verifying'),
                   ('router', 'Compute the final numeric answer')):
        if sig in prompt:
            return k
    return 'router'


def stub(script=None):
    script = script or {}

    def service(model, prompt):
        time.sleep(0.001)
        return dict(status='delivered',
                    answer=script.get((model, _pkind(prompt)), GOOD[_pkind(prompt)]),
                    usage=dict(total_tokens=100))
    return service


def self_test():
    tasks = select_tasks()
    faults = build_heldout_faults(tasks)
    led = fp.Ledger()
    gc = _load_gc()
    checks = {}
    gold_task = dict(tasks[0], answer=4.0)
    f1 = {gold_task['uid']: ('r', 'x')}

    bad = {('medium', 'expr'): '###garbage###'}
    log_a = run_track(stub(bad), gold_task, 'dynpatch', led, f1, gc)
    checks['t1_dynpatch_split_real_prompts'] = bool(log_a['patches']) \
        and {'r1', 'r2'} <= set(log_a['executed']) and log_a['status'] == 'completed'
    log_b = run_track(stub(bad), dict(gold_task, answer=999.0), 'dynpatch',
                      led, f1, gc)
    checks['t1b_no_gold_leak'] = (log_a['executed'] == log_b['executed']
                                  and log_a['patches'] == log_b['patches']
                                  and log_a['events'] == log_b['events']
                                  and log_a['final_quality'] != log_b['final_quality'])
    log_r = run_track(stub(bad), gold_task, 'reroute', led, f1, gc)
    checks['t2_reroute_recovers'] = 'r_esc' in log_r['executed'] \
        and log_r['status'] == 'completed'
    log_s = run_track(stub(), gold_task, 'static', led, {}, gc)
    checks['t3_static_completes'] = log_s['status'] == 'completed' \
        and log_s['final_quality'] == 1
    checks['t4_faults_on_heldout'] = len(faults) >= 1 and all(
        any(t['uid'] == u for t in tasks) for u in faults)

    def flaky(model, prompt):
        if _pkind(prompt) in ('expr', 'step1'):
            return dict(status='infrastructure_failure', answer=None, usage=None)
        return dict(status='delivered', answer=GOOD[_pkind(prompt)],
                    usage=dict(total_tokens=100))
    log_f = run_track(flaky, gold_task, 'static', led, {}, gc)
    checks['t5_failed_no_ready'] = log_f['status'] == 'failed-no-ready' \
        and log_f['failed_calls'] == 1
    checks['t6_tokens_accounted'] = all(l['total_tokens'] >= 0 for l in
                                        (log_a, log_r, log_s, log_f)) \
        and log_s['total_tokens'] == 400
    checks['t6b_global_counter_persisted'] = json.loads(
        GCOUNTER.read_text())['n'] == gc['n']
    lines = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    checks['t6c_failed_calls_on_disk'] = any(
        r['response']['status'] != 'delivered' for r in lines)

    prot = dict(protocol='P1B pilot v2 (six audit P0s fixed)',
                tasks=[dict(uid=t['uid'],
                            uid_sha256=hashlib.sha256(
                                t['uid'].encode()).hexdigest()[:16]) for t in tasks],
                heldout_faults={u: n for u, (n, _) in faults.items()},
                fault_rule='Random(20260923) over the 5 held-out UIDs, 30% '
                           '(2 tasks), node+pool draws per frozen200 rule',
                strategies=['single', 'static', 'reroute', 'dynpatch'],
                per_task_budget=PER_TASK_BUDGET, smoke_cap=SMOKE_CAP,
                global_budget=GLOBAL_BUDGET, cache='disabled', concurrency='serial',
                retries=0, smoke_budget_note='1 task x 4 strategies x 1 state = '
                                             '48 cap; both states = 96',
                code_sha={f: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()[:16]
                          for f, p in (('patch', 'collab_scheduler_v1/dag_patch_p0.py'),
                                       ('p1b', 'collab_scheduler_v1/dag_patch_p1b.py'))})
    (OUT / 'P1B_PROTOCOL.json').write_text(json.dumps(prot, indent=1))
    (OUT / 'P1B_SELFTEST.json').write_text(json.dumps(
        dict(checks=checks, sample_dynpatch=log_a, sample_reroute=log_r,
             sample_static=log_s, sample_failed=log_f), indent=1, default=str))
    print(json.dumps(checks, indent=1))
    print('ALL PASS' if all(checks.values()) else 'FAIL PRESENT')


def smoke_run():
    """GATED real entry: --execute + env P1B_EXECUTE=1 + GPU lock."""
    import os
    if os.environ.get('P1B_EXECUTE') != '1':
        print('smoke_run is gated (env P1B_EXECUTE=1); refusing')
        return
    lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        from static_dag_v0 import run as engine
        engine.OUT = OUT
        tasks = select_tasks()
        led = fp.Ledger()
        gc = _load_gc()
        gc['cap'] = min(gc['cap'], SMOKE_CAP)
        _save_gc(gc)
        for state, faults in (('clean', {}), ('fault30', build_heldout_faults(tasks))):
            for strat in ('single', 'static', 'reroute', 'dynpatch'):
                log = run_track(lambda m, p: engine.call_model(m, p),
                                tasks[0], strat, led, faults, gc)
                log['state'] = state
                print(json.dumps({k: log[k] for k in
                                  ('strategy', 'state', 'status', 'final_quality',
                                   'total_tokens', 'end_to_end_wall_s', 'n_calls')},
                                 default=str), flush=True)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


if __name__ == '__main__':
    smoke_run() if '--execute' in sys.argv else self_test()
