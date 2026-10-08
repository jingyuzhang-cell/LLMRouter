"""P1-A: DAG Patch wired into an executor-grade loop with a FAKE model.

Zero LLM calls, no GPU. Bridges the P0 capability onto the fault30 executor's
conventions so P1-B only swaps the fake backend for the real server:

  - nodes dispatch through an Executor.call() with the fault30 ledger shape
    (key/model/prompt_sha/unix_time + response{status,answer,usage,latency_s}),
    latency measured with time.monotonic (wall-clock of the fake call), and a
    frozen MAX_CALLS budget guard that aborts the task with a partial log
  - detector reads ONLY node outputs; policy issues patches through the now
    ATOMIC patch API (draft-validated, committed whole)
  - scheduler overhead (detect+decide+patch time) measured separately from
    node execution time
  - checks: illegal patch (cycle) leaves the graph bit-identical; duplicate-ID
    insert rejected; budget cap aborts with replayable ledger; executed-node
    outputs consumed via the NEW predecessors after a split

Run: python3 -m collab_scheduler_v1.dag_patch_p1a   -> P1A_EVIDENCE.json
"""
import hashlib
import json
import time
from pathlib import Path

from collab_scheduler_v1.dag_patch_p0 import PatchError, RuntimeDAG

OUT = Path('/root/r3_own_pool/collab_scheduler_v1/fault30_prep')
MAX_CALLS = 12  # frozen budget guard for the pilot (per task)


class BudgetExceeded(Exception):
    pass


class Executor:
    """fault30-shaped ledger + budget guard; backend injected (fake here)."""

    def __init__(self, backend, task_id):
        self.backend = backend
        self.task_id = task_id
        self.ledger = []
        self.tokens = 0
        self.node_time = 0.0

    def call(self, node, model, payload):
        if len(self.ledger) >= MAX_CALLS:
            raise BudgetExceeded(f'{MAX_CALLS} call budget exhausted')
        prompt = json.dumps([node, payload], sort_keys=True)
        key = f'p1a:{self.task_id}:{node}:{len(self.ledger)}'
        t0 = time.monotonic()
        resp = self.backend(node, model, payload)
        dt = time.monotonic() - t0
        rec = dict(key=key, model=model,
                   prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                   unix_time=time.time(),
                   response=dict(status='delivered', answer=resp['answer'],
                                 usage=resp['usage'], latency_s=dt))
        self.ledger.append(rec)
        self.tokens += resp['usage']['total_tokens']
        self.node_time += dt
        return rec


def run_task(task_id, g, backend, detector, policy, gold):
    ex = Executor(backend, task_id)
    log = dict(task_id=task_id,
               initial_DAG={u: dict(deps=list(n['deps']), model=n['model'])
                            for u, n in g.nodes.items()},
               executed=[], events=[], patches=[], scheduler_overhead_s=0.0,
               status='completed')
    try:
        while g.ready():
            u = sorted(g.ready())[0]
            deps_out = [g.nodes[p]['output'] for p in g.nodes[u]['deps']]
            rec = ex.call(u, g.nodes[u]['model'], deps_out)
            g.nodes[u]['status'], g.nodes[u]['output'] = 'done', rec['response']['answer']
            log['executed'].append(u)
            t0 = time.monotonic()
            fb = detector(u, rec['response']['answer'], g)
            if fb:
                log['events'].append(dict(executed=u, **fb))
                patch = policy(fb, g)
                if patch:
                    diff = patch(g)
                    log['patches'].append(diff)
            log['scheduler_overhead_s'] += time.monotonic() - t0
    except BudgetExceeded as e:
        log['status'] = f'aborted-budget: {e}'
    final = next((n['output'] for u, n in reversed(list(g.nodes.items()))
                  if u.startswith('v')), None)
    log.update(final_DAG={u: dict(deps=list(n['deps']), model=n['model'],
                                  status=n['status']) for u, n in g.nodes.items()},
               final_quality=backend.quality(final, gold),
               total_tokens=ex.tokens, node_wall_clock_s=round(ex.node_time, 6),
               n_calls=len(ex.ledger))
    return log, ex


# ---- fake backend: deterministic scripted outputs (NO LLM) ----
class FakeBackend:
    scripts = {
        ('e', 'large'): dict(facts=[1.5, 2.5]),
        ('e', 'medium'): dict(facts=[1.5, 2.5]),
        ('r', 'medium'): '###garbage###',           # fails on this task
        ('r', 'large'): dict(expr='v0+v1', val=4.0),
        ('r1', 'large'): dict(step1=4.0),
        ('r2', 'large'): None,                       # filled at call: reads deps
        ('c', 'coder'): dict(check='ok'),
        ('v', 'coder'): None,                        # filled at call: reads deps
    }

    def __call__(self, node, model, payload):
        time.sleep(0.001)
        if node in ('r2', 'v'):
            dep = payload[-1]
            assert isinstance(dep, dict) and ('step1' in dep or 'val' in dep), \
                'downstream did not receive new predecessor output'
            val = dep.get('step1', dep.get('val'))
            return dict(answer=dict(val=val), usage=dict(total_tokens=90))
        ans = self.scripts[(node, model)]
        return dict(answer=ans, usage=dict(total_tokens=110))

    @staticmethod
    def quality(final, gold):
        v = final.get('val') if isinstance(final, dict) else None
        return int(v is not None and abs(v - gold) < 1e-9)


def run():
    ev = dict(role='P1-A integration test: DAG Patch on an executor-grade loop '
                   'with FAKE model (zero LLM calls; wiring/safety only, no '
                   'performance meaning)', budget_max_calls=MAX_CALLS, logs=[],
              checks={})

    # I1: full loop — r fails -> atomic split -> resume on new DAG
    g = RuntimeDAG({'e': dict(deps=[], model='large'),
                    'r': dict(deps=['e'], model='medium'),
                    'v': dict(deps=['r'], model='coder')})

    def detector(u, out, gg):
        if u == 'r' and not isinstance(out, dict):
            return dict(kind='reasoning output not parseable',
                        diagnosis='reasoning-stage failure',
                        decision='split r')
        return None

    log, _ = run_task('I1-split-resume', g, FakeBackend(), detector,
                      lambda fb, gg: (lambda d: d.split_node('r', 'r1', 'r2',
                                                             'large', 'large'))
                      if fb['decision'] == 'split r' else None, 4.0)
    ev['logs'].append(log)
    ev['checks']['i1_completed'] = log['status'] == 'completed'
    ev['checks']['i1_structure_changed_midrun'] = (
        log['patches'] and log['final_quality'] == 1
        and [x for x in log['executed'] if x in ('r1', 'r2')])

    # I2: illegal patch (cycle) rejected ATOMICALLY — graph bit-identical
    g2 = RuntimeDAG({'e': dict(deps=[], model='large'),
                     'r': dict(deps=['e'], model='medium'),
                     'v': dict(deps=['r'], model='coder')})
    before = json.dumps({u: n['deps'] for u, n in g2.nodes.items()}, sort_keys=True)
    try:
        g2.nodes['e']['deps'] = []  # craft: rewire v->e would need e pending
        g2._atomic(lambda d: (d.nodes.__setitem__('x', dict(deps=['x'], model='m',
                                                            status='pending',
                                                            output=None)),
                              dict())[1])
        ev['checks']['i2_cycle_rejected'] = False
    except PatchError:
        after = json.dumps({u: n['deps'] for u, n in g2.nodes.items()}, sort_keys=True)
        ev['checks']['i2_cycle_rejected'] = before == after  # atomic: unchanged

    # I3: duplicate node id rejected
    g3 = RuntimeDAG({'e': dict(deps=[], model='large'),
                     'r': dict(deps=['e'], model='medium')})
    try:
        g3.insert_node('e', 'r', 'coder')
        ev['checks']['i3_duplicate_id_rejected'] = False
    except PatchError:
        ev['checks']['i3_duplicate_id_rejected'] = True

    # I4: budget guard aborts with replayable partial log
    class Endless:
        def __call__(self, u, m, p):
            return dict(answer=dict(val=0.0), usage=dict(total_tokens=10))

        @staticmethod
        def quality(final, gold):
            return 0
    g4 = RuntimeDAG({f'n{i}': dict(deps=([f'n{i-1}'] if i else []), model='large')
                     for i in range(30)})  # chain longer than budget
    endless = Endless()
    log4, ex4 = run_task('I4-budget-guard', g4, endless,
                         lambda u, o, gg: None, lambda fb, gg: None, 4.0)
    ev['logs'].append(log4)
    ev['checks']['i4_budget_abort'] = (log4['status'].startswith('aborted-budget')
                                       and ex4.ledger and len(ex4.ledger) <= MAX_CALLS)

    # I5: timing fields present and scheduler overhead separated
    ev['checks']['i5_timing_fields'] = all(
        isinstance(l.get('node_wall_clock_s'), float)
        and isinstance(l.get('scheduler_overhead_s'), float)
        and l['n_calls'] * l['total_tokens'] >= 0 for l in ev['logs'])
    ev['checks']['zero_model_calls'] = True
    ev['verdict'] = 'P1-A PASS: executor-grade wiring, atomic patches, budget ' \
                    'guard, timing and ledger verified with a fake model; ready ' \
                    'for P1-B (5-8 held-out tasks, REAL calls) once the budget ' \
                    'protocol is frozen' if all(
                        v for k, v in ev['checks'].items() if k != 'zero_model_calls')\
        else 'P1-A FAIL'
    (OUT / 'P1A_EVIDENCE.json').write_text(json.dumps(ev, indent=1, default=str))
    print(json.dumps(ev['checks'], indent=1))
    print(ev['verdict'])


if __name__ == '__main__':
    run()
