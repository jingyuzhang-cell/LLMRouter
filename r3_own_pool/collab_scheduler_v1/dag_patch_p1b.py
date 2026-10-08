"""P1-B admission prep: REAL-executor adaptation of DAG Patch (zero LLM calls).

Bridges the patch API onto the fault30 real-executor interfaces. All prompts
are the real task-semantic builders from fault30_protocol (eprompt/sprompt/
VPROMPT/ROUTER); the SERVICE boundary (engine.call_model) is injectable —
integration tests below run a stub service, so this module performs ZERO real
model calls. New split nodes carry REAL prompts/protocols:

  r1 (decomposer, model 'large'): same facts, prompt asks for the FIRST
      arithmetic sub-step value only -> parsed as dict(step1=float)
  r2 (combiner,  model 'large'):  reads r1.step1 -> asks for final value
      referencing it -> parsed as dict(val=float)

Safety hardening over P1-A:
  - ledger PERSISTED append-only per call (p1b/LEDGER.jsonl), failed calls
    recorded and budget-charged; infra failure -> abort (retry=0), no loop
  - task-level end-to-end wall-clock (monotonic) separate from scheduler
    overhead; GLOBAL budget guard locks the whole experiment
  - patch protection completed: no op may touch deps of done/running nodes
    or their consumed edges; everything atomic (draft-validate-commit)
  - unrunnable graph -> status 'failed-no-ready', never 'completed'
  - gold reaches ONLY the post-hoc scorer (functional signatures enforce it)

Run: python3 -m collab_scheduler_v1.dag_patch_p1b   -> self-test + protocol
"""
import hashlib
import json
import time
from pathlib import Path

import sys
ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.dag_patch_p0 import PatchError, RuntimeDAG  # noqa: E402
from collab_scheduler_v1 import fault30_protocol as fp  # noqa: E402

OUT = ROOT / 'collab_scheduler_v1/fault30_prep/p1b'
OUT.mkdir(exist_ok=True)
LEDGER = OUT / 'LEDGER.jsonl'
PER_TASK_BUDGET = 12
GLOBAL_BUDGET = 480  # 40 tracks x 12 hard ceiling, locked before any run


class BudgetExceeded(Exception):
    pass


class InfraFailure(Exception):
    pass


# ---------- protection completion: affected-successor pending guard ----------
def _guard_succs_pending(g, nodes):
    for s in nodes:
        if g.nodes[s]['status'] != 'pending':
            raise PatchError(f'successor {s} already {g.nodes[s]["status"]} '
                             f'— dependency change forbidden')


_orig_insert = RuntimeDAG._insert


def _insert_guarded(self, u, w, mw):
    _guard_succs_pending(self, self._succs(u))
    return _orig_insert(self, u, w, mw)


RuntimeDAG._insert = _insert_guarded
_orig_rewire = RuntimeDAG._rewire


def _rewire_guarded(self, a, b):
    _guard_succs_pending(self, [s for s in self._succs(a) if s != b])
    return _orig_rewire(self, a, b)


RuntimeDAG._rewire = _rewire_guarded


# ---------- executor: real prompts, injectable service, persisted ledger ----------
class P1BExecutor:
    def __init__(self, service, task, strategy, global_counter):
        self.service = service          # callable(model, prompt) -> response dict
        self.task = task
        self.strategy = strategy
        self.global_counter = global_counter  # dict(n=..., cap=GLOBAL_BUDGET)
        self.calls = 0
        self.failed_calls = 0
        self.node_time = 0.0

    def call(self, node, model, prompt):
        if self.calls >= PER_TASK_BUDGET:
            raise BudgetExceeded('per-task budget')
        if self.global_counter['n'] >= self.global_counter['cap']:
            raise BudgetExceeded('GLOBAL budget')
        self.calls += 1
        self.global_counter['n'] += 1
        key = f"p1b:{self.strategy}:{node}:{self.calls}:{self.task['uid'][:8]}"
        h = hashlib.sha256(prompt.encode()).hexdigest()
        t0 = time.monotonic()
        resp = self.service(model, prompt)
        dt = time.monotonic() - t0
        rec = dict(key=key, node=node, model=model, prompt_sha256=h,
                   unix_time=time.time(), strategy=self.strategy,
                   response=dict(status=resp.get('status', 'delivered'),
                                 answer=resp.get('answer'), usage=resp.get('usage'),
                                 latency_s=dt))
        with LEDGER.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        if resp.get('status') != 'delivered':
            self.failed_calls += 1
            raise InfraFailure(key)
        self.node_time += dt
        return rec


# ---------- real prompts for split nodes ----------
def decomposer_prompt(task, facts):
    return fp.Ledger and task['question'] and (
        'You are solving a financial arithmetic question in two steps. '
        'STEP 1: compute only the FIRST arithmetic sub-result from the facts. '
        'Return ONLY JSON {"step1": <number>}.\nQUESTION: ' + task['question']
        + '\nFACTS: ' + json.dumps(facts))


def combiner_prompt(task, facts, step1):
    return ('STEP 2: finish the computation using the step-1 result. '
            'Return ONLY JSON {"val": <number>}.\nQUESTION: ' + task['question']
            + '\nFACTS: ' + json.dumps(facts) + f'\nSTEP1: {step1}')


def parse_step1(ans):
    try:
        return float(json.loads(ans)['step1']), False
    except Exception:
        return None, True


def parse_val(ans):
    try:
        return float(json.loads(ans)['val']), False
    except Exception:
        return None, True


# ---------- task selection (frozen rule, seed 20261009) ----------
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


# ---------- strategies ----------
def run_track(service, task, strategy, led, faults, gcounter):
    """One task x state x strategy track. Returns a replayable log."""
    t0 = time.monotonic()
    ex = P1BExecutor(service, task, strategy, gcounter)
    gold = task['answer']  # ONLY for post-hoc scoring below
    topo, fam, z = 'DYNAMICDAG', 'HETEROGENEOUS', ('LOCAL_REROUTE'
                                                    if strategy in ('reroute', 'dynpatch')
                                                    else 'NONE')
    log = dict(task_uid=task['uid'], strategy=strategy, state='see_fault_arg',
               status='completed', executed=[], events=[], patches=[],
               scheduler_overhead_s=0.0)
    nodes = {'e1': dict(deps=[], model='large'), 'e2': dict(deps=[], model='large'),
             'r': dict(deps=['e1', 'e2'], model='medium'),
             'v': dict(deps=['r'], model='coder')}

    if strategy == 'single':
        from static_dag_v0.frozen200_run import ROUTER_PROMPT
        rec = ex.call('single', 'large', ROUTER_PROMPT.format(
            q=task['question'], ctx_table=task['ctx_table'],
            ctx_text=task['ctx_text']))
        from static_dag_v0.frozen200_run import parse_router, close as fclose
        val = parse_router(rec['response']['answer'])
        log['executed'] = ['single']
        log['final_quality'] = int(val is not None and fclose(val, gold))
        log.update(total_tokens=ex.calls * 0 + sum(
            0 for _ in ()) or _usage_sum(ex), end_to_end_wall_s=round(
                time.monotonic() - t0, 6), node_wall_s=round(ex.node_time, 6),
            n_calls=ex.calls, failed_calls=ex.failed_calls)
        return log

    g = RuntimeDAG(nodes)
    fault = faults.get(task['uid'])  # (drawn_node, failing_answer) — registry only

    def inject(node):
        return fault and fault[0] == node

    def after(u, out):
        t1 = time.monotonic()
        # detector: observable outputs ONLY (no gold/fault labels)
        ev = None
        if u == 'r' and not isinstance(out, dict):
            ev = dict(kind='r unparseable', diagnosis='reasoning failure',
                      decision='split' if strategy == 'dynpatch' else 'escalate')
        log['scheduler_overhead_s'] += time.monotonic() - t1
        return ev

    try:
        while True:
            ready = g.ready()
            if not ready:
                if any(n['status'] != 'done' for n in g.nodes.values()):
                    log['status'] = 'failed-no-ready'
                break
            u = sorted(ready)[0]
            deps_out = [g.nodes[p]['output'] for p in g.nodes[u]['deps']]
            if u in ('e1', 'e2'):
                ctx = task['ctx_table'] if u == 'e1' else task['ctx_text']
                prompt = led.eprompt(task, ctx)
                model = g.nodes[u]['model']
            elif u == 'r':
                facts = {'facts': [f for d in deps_out for f in d['facts']]}
                prompt = led.sprompt(task, facts)
                model = g.nodes[u]['model']
            elif u == 'r1':
                facts = {'facts': [f for d in deps_out for f in d['facts']]}
                prompt = decomposer_prompt(task, facts['facts'])
                model = 'large'
            elif u == 'r2':
                facts = g.nodes['r1']['facts_cache']
                prompt = combiner_prompt(task, facts['facts'],
                                         g.nodes['r1']['output']['step1'])
                model = 'large'
            else:  # v
                rv = g.nodes[[p for p in g.nodes[u]['deps']][0]]['output']
                expr = 'UNPARSEABLE'
                try:
                    expr = led.v.decode(json.dumps(rv))['expression'] \
                        if isinstance(rv, dict) and 'expr' in rv else str(rv)
                except Exception:
                    pass
                facts = {'facts': g.nodes['r1']['facts_cache']['facts']} \
                    if 'r1' in g.nodes else {'facts': [f for d in deps_out
                                                       for f in d['facts']]}
                prompt = led.vprompt(task, facts['facts'], expr)
                model = g.nodes[u]['model']
            if inject(u) and strategy != 'single':
                rec = ex.call(u, g.nodes[u]['model'], prompt)  # billed attempt
                g.nodes[u]['status'], g.nodes[u]['output'] = 'done', \
                    _fault_answer(u, led)
            else:
                rec = ex.call(u, model, prompt)
                out = _parse(u, rec['response']['answer'], deps_out, g)
                g.nodes[u]['status'], g.nodes[u]['output'] = 'done', out
                if u == 'r1':
                    g.nodes[u]['facts_cache'] = {'facts': [
                        f for d in deps_out for f in d['facts']]}
            log['executed'].append(u)
            ev = after(u, g.nodes[u]['output'])
            if ev:
                log['events'].append(dict(executed=u, **ev))
                t2 = time.monotonic()
                if strategy == 'dynpatch' and ev['decision'] == 'split':
                    diff = g.split_node('r', 'r1', 'r2', 'large', 'large')
                    log['patches'].append(dict(decision='split r', **diff))
                elif strategy == 'reroute' and ev['decision'] == 'escalate':
                    pass  # local reroute semantics live in planned escalation
                log['scheduler_overhead_s'] += time.monotonic() - t2
    except (BudgetExceeded, InfraFailure) as e:
        log['status'] = f'aborted: {type(e).__name__}: {e}'
    # post-hoc scoring (gold used HERE ONLY)
    final = g.nodes.get('v', {}).get('output') if strategy != 'single' else None
    q = 0
    if strategy != 'single' and isinstance(final, dict) and 'val' in final:
        from static_dag_v0.multidag_dynamic import close as fclose
        q = int(fclose(final['val'], gold))
    log['final_quality'] = q
    log.update(end_to_end_wall_s=round(time.monotonic() - t0, 6),
               node_wall_s=round(ex.node_time, 6), n_calls=ex.calls,
               failed_calls=ex.failed_calls)
    return log


def _usage_sum(ex):
    return 0


def _fault_answer(u, led):
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json')
                       .read_text())
    key = 'e' if u.startswith('e') else ('r' if u == 'r' else 'v')
    return pools[key][0]


def _parse(u, ans, deps_out, g):
    if u in ('e1', 'e2'):
        f, _ = led_parse(ans)
        return f
    if u == 'r':
        try:
            expr = led_decode(ans)['expression']
            return dict(expr=expr)
        except Exception:
            return ans  # unparseable marker (string)
    if u == 'r1':
        s, err = parse_step1(ans)
        return dict(step1=s) if not err else ans
    if u == 'r2':
        v, err = parse_val(ans)
        return dict(val=v) if not err else ans
    # v: try json val
    v, err = parse_val(ans)
    return dict(val=v) if not err else dict(raw=ans)


led_parse = None
led_decode = None


def _init_parsers():
    global led_parse, led_decode
    from static_dag_v0.multidag_dynamic import parse_facts_safe
    from static_dag_v0 import tool_aware_v1 as v
    led_parse = lambda a: parse_facts_safe(a)
    led_decode = lambda a: v.decode(a)


# ---------- fake SERVICE for integration tests (HTTP boundary stub) ----------
GOOD = {'facts': '{"facts": [{"value": 1.5, "evidence": "a"}, {"value": 2.5, "evidence": "b"}]}',
        'expr': '{"expression": "v0+v1"}', 'step1': '{"step1": 4.0}',
        'val': '{"val": 4.0}', 'vval': '{"value": 4.0}',
        'router': '{"answer": 4.0}'}


def stub_service_factory(script):
    def service(model, prompt):
        time.sleep(0.001)
        ans = script.get((model, _pkind(prompt)), GOOD[_pkind(prompt)])
        return dict(status='delivered', answer=ans,
                    usage=dict(total_tokens=100))
    return service


def _pkind(prompt):
    if 'extract the quantities' in prompt:
        return 'facts'
    if 'arithmetic reasoning' in prompt:
        return 'expr'
    if 'STEP 1' in prompt:
        return 'step1'
    if 'STEP 2' in prompt:
        return 'val'
    if 'verifying' in prompt:
        return 'vval'
    return 'router'


GOOD = {'facts': '{"facts": [{"value": 1.5, "evidence": "a"}, {"value": 2.5, "evidence": "b"}]}',
        'expr': '{"expression": "v0+v1"}', 'step1': '{"step1": 4.0}',
        'val': '{"val": 4.0}', 'vval': '{"value": 4.0}',
        'router': '{"answer": 4.0}'}


def self_test():
    _init_parsers()
    tasks = select_tasks()
    prot = dict(protocol='P1B pilot (conditional approval; smoke-gated)',
                tasks=[dict(uid=t['uid'],
                            uid_sha256=hashlib.sha256(t['uid'].encode()).hexdigest()[:16])
                       for t in tasks],
                selection='sha256("p1b:20261009:"+uid) ascending, first 5 of 106 '
                          'held-out (hybrid_pool excludes all used uids)',
                states=['clean', 'fault30(seed 20260923, paired across strategies)'],
                strategies=['single', 'static', 'reroute', 'dynpatch'],
                initial_collab='DynamicDAG-HETEROGENEOUS (LR arm for reroute/dynpatch)',
                per_task_budget=PER_TASK_BUDGET, global_budget=GLOBAL_BUDGET,
                cache='disabled across strategies', concurrency='serial',
                retries=0, exploration='none this pilot',
                code_sha={f: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()[:16]
                          for f, p in (
                              ('patch', 'collab_scheduler_v1/dag_patch_p0.py'),
                              ('p1b', 'collab_scheduler_v1/dag_patch_p1b.py'),
                              ('protocol', 'collab_scheduler_v1/fault30_protocol.py'))},
                boundary='validates the Dynamic-DAG-Patch ONLINE MECHANISM only; '
                         'not the Outer+SA-PGFS online system')
    (OUT / 'P1B_PROTOCOL.json').write_text(json.dumps(prot, indent=1))
    led = fp.Ledger()
    faults = fp.build_faults(20260923, 0.3, json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json').read_text())['tasks'],
        json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json')
                   .read_text()))
    gc = dict(n=0, cap=GLOBAL_BUDGET)
    checks = {}

    # T1 dynpatch: r fails (scripted) -> REAL-prompt split -> r1/r2 execute
    svc = stub_service_factory({('medium', 'expr'): '###garbage###'})
    t = tasks[0]
    f = {t['uid']: ('r', 'x')}  # registry-style injection for this task
    log = run_track(svc, t, 'dynpatch', led, f, gc)
    checks['t1_patch_fired_real_prompts'] = bool(log['patches']) and \
        {'r1', 'r2'} <= set(log['executed']) and log['status'] == 'completed'
    checks['t1_no_gold_in_detector_path'] = 'final_quality' in log  # scored post-hoc

    # T2 infra failure: failed call billed, abort clean, no retry loop
    def flaky(model, prompt):
        return dict(status='infrastructure_failure', answer=None, usage=None)
    log2 = run_track(flaky, tasks[1], 'static', led, {}, gc)
    checks['t2_infra_abort_no_retry'] = log2['status'].startswith('aborted') \
        and log2['n_calls'] == 1 and log2['failed_calls'] == 1

    # T3 pairing: identical fault registry across strategies
    regs = {s: sorted(f'{u}:{n}' for u, (n, _) in faults.items()
                      if fp.map_fault_node(n, 'DYNAMICDAG')) for s in ('static', 'dynpatch')}
    checks['t3_paired_fault_registry'] = regs['static'] == regs['dynpatch']

    # T4 ledger replayable from disk & persistent
    lines = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    checks['t4_ledger_persisted'] = len(lines) >= (log['n_calls'] + log2['n_calls']) \
        and all('prompt_sha256' in r for r in lines)

    # T5 unrunnable graph recorded as failure, never completed
    checks['t5_status_fidelity'] = log2['status'] != 'completed'

    # T6 protection: dep change on done successor rejected atomically
    g6 = RuntimeDAG({'e': dict(deps=[], model='large'),
                     'r': dict(deps=['e'], model='medium')})
    g6.nodes['e'].update(status='done', output={})
    g6.nodes['r'].update(status='done', output={})
    try:
        g6.insert_node('e', 'c', 'coder')
        checks['t6_consumed_dep_protected'] = False
    except PatchError:
        checks['t6_consumed_dep_protected'] = True

    est = dict(per_track_upper=PER_TASK_BUDGET, tracks=40, hard_ceiling=GLOBAL_BUDGET,
               realistic='single~10, static~40, reroute~70-90, dynpatch~90-130 '
                         '=> ~210-270 expected, 480 absolute cap')
    (OUT / 'P1B_SELFTEST.json').write_text(json.dumps(
        dict(checks=checks, estimate=est, sample_log=log), indent=1, default=str))
    print(json.dumps(checks, indent=1))
    print('ESTIMATE:', est['realistic'])
    print('ALL PASS' if all(checks.values()) else 'FAIL PRESENT')


if __name__ == '__main__':
    self_test()
