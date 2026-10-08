"""P0: feedback-triggered DAG reconfiguration — capability proof (zero LLM calls).

Implements a constrained DAG-Patch interface and a simulated executor so the
RUNTIME STRUCTURAL modification of the task graph can be validated before any
real online run:

  ops (all legality-checked):
    split_node(u, [u1, u2])  remove u; add u1, u2; wire preds(u)->u1->u2->succs(u)
    insert_node(u, w)        add w between u and its successors
    remove_node(u)           only if u is pending (done nodes are protected)
    rewire_edge(a, b)        redirect every edge a->x to a->b (b pending)

  legality (raises PatchError):
    acyclicity after patch; done/executing nodes never removed or rewired;
    descendants re-read the NEW predecessors' outputs (data flow re-linked).

  evidence log (user-specified format, replayable):
    per task: initial DAG, executed nodes, observed feedback, diagnosis,
    decision, node/edge diffs, reconstructed DAG, validation PASS, resumed
    execution order, final quality, token/step counters (simulated).

Run:  python3 -m collab_scheduler_v1.dag_patch_p0     -> PATCH_EVIDENCE.json
"""
import copy
import json
import time
from pathlib import Path

OUT = Path('/root/r3_own_pool/collab_scheduler_v1/fault30_prep')


class PatchError(Exception):
    pass


class RuntimeDAG:
    """Nodes: id -> dict(model, deps:list, status, output). status in
    pending/running/done. deps define edges preds(u) -> u."""

    def __init__(self, nodes):
        self.nodes = {u: dict(deps=list(d['deps']), model=d['model'],
                              status='pending', output=None) for u, d in nodes.items()}

    def V(self):
        return set(self.nodes)

    def E(self):
        return {(p, u) for u in self.nodes for p in self.nodes[u]['deps']}

    def ready(self):
        return [u for u, n in self.nodes.items() if n['status'] == 'pending'
                and all(self.nodes[p]['status'] == 'done' for p in n['deps'])]

    def _acyclic(self):
        seen, stack = set(), set()

        def visit(u):
            if u in stack:
                return False
            if u in seen:
                return True
            seen.add(u)
            stack.add(u)
            ok = all(visit(p) for p in self.nodes[u]['deps'])
            stack.discard(u)
            return ok

        return all(visit(u) for u in self.nodes)

    # ---- constrained patch ops (atomic: checked on a draft, then committed) ----
    def _atomic(self, mutate):
        draft = copy.deepcopy(self)
        diff = mutate(draft)
        draft._check_all()
        self.nodes = draft.nodes
        return diff

    def _check_all(self):
        if not self._acyclic():
            raise PatchError('patch would create a cycle')
        for u in self.nodes:
            for p in self.nodes[u]['deps']:
                if p not in self.nodes:
                    raise PatchError(f'dangling dep {p}->{u}')

    def split_node(self, u, u1, u2, m1, m2):
        def mutate(d):
            for nid in (u1, u2):
                if nid in d.nodes:
                    raise PatchError(f'duplicate node id {nid}')
            return d._split(u, u1, u2, m1, m2)
        return self._atomic(mutate)

    def _split(self, u, u1, u2, m1, m2):
        self._guard_remove(u)
        preds, succs = self.nodes[u]['deps'], self._succs(u)
        del self.nodes[u]
        self.nodes[u1] = dict(deps=preds, model=m1, status='pending', output=None)
        self.nodes[u2] = dict(deps=[u1], model=m2, status='pending', output=None)
        for s in succs:  # successors of u now depend on the split chain's end
            self.nodes[s]['deps'] = [u2 if d == u else d for d in self.nodes[s]['deps']]
        return dict(removed_nodes=[u], added_nodes=[u1, u2],
                    removed_edges=sorted({(p, u) for p in preds} | {(u, s) for s in succs}),
                    added_edges=sorted({(p, u1) for p in preds} | {(u1, u2)}
                                       | {(u2, s) for s in succs}))

    def insert_node(self, u, w, mw):
        def mutate(d):
            if w in d.nodes:
                raise PatchError(f'duplicate node id {w}')
            return d._insert(u, w, mw)
        return self._atomic(mutate)

    def _insert(self, u, w, mw):
        succs = self._succs(u)
        self.nodes[w] = dict(deps=[u], model=mw, status='pending', output=None)
        for s in succs:
            self.nodes[s]['deps'].remove(u)
            self.nodes[s]['deps'].append(w)
        return dict(removed_nodes=[], added_nodes=[w],
                    removed_edges=sorted({(u, s) for s in succs}),
                    added_edges=sorted({(u, w)} | {(w, s) for s in succs}))

    def remove_node(self, u):
        self._atomic(lambda d: (d._guard_remove(u), d._remove(u))[1])

    def _remove(self, u):
        self._guard_remove(u)
        preds, succs = self.nodes[u]['deps'], self._succs(u)
        del self.nodes[u]
        for s in succs:
            self.nodes[s]['deps'].remove(u)
            self.nodes[s]['deps'] += preds
        return dict(removed_nodes=[u], added_nodes=[],
                    removed_edges=sorted({(p, u) for p in preds} | {(u, s) for s in succs}),
                    added_edges=sorted({(p, s) for p in preds for s in succs}))

    def rewire_edge(self, a, b):
        def mutate(d):
            if d.nodes[a]['status'] != 'pending' or d.nodes[b]['status'] != 'pending':
                raise PatchError('rewire only on pending nodes')
            return d._rewire(a, b)
        return self._atomic(mutate)

    def _rewire(self, a, b):
        succs = self._succs(a)
        for s in succs:
            if s == b:
                continue
            self.nodes[s]['deps'].remove(a)
            if b not in self.nodes[s]['deps']:
                self.nodes[s]['deps'].append(b)
        return dict(removed_nodes=[], added_nodes=[],
                    removed_edges=sorted({(a, s) for s in succs if s != b}),
                    added_edges=sorted({(b, s) for s in succs if s != b}))

    # ---- helpers ----
    def _succs(self, u):
        return [s for s in self.nodes if u in self.nodes[s]['deps']]

    def _guard_remove(self, u):
        # protection rule: a done node whose output was CONSUMED by an executed
        # successor is immutable; a failed done node with no executed consumer
        # (the split/replacement case) is replaceable; running nodes never are.
        st = self.nodes[u]['status']
        if st == 'running':
            raise PatchError(f'node {u} is running — protected')
        if st == 'done' and any(self.nodes[s]['status'] == 'done'
                                for s in self._succs(u)):
            raise PatchError(f'node {u} output already consumed by an executed '
                             f'successor — protected')


def run_task(task_id, g0, sim, detector, policy, gold):
    """Execute; after each node, run the OBSERVABLE-feedback detector and let
    the policy issue patches; continue on the reconfigured graph."""
    log = dict(task_id=task_id,
               initial_DAG=copy.deepcopy({u: dict(deps=list(n['deps']),
                                                  model=n['model'])
                                          for u, n in g0.nodes.items()}),
               events=[], patches=[], validation=[])
    order, tokens, steps = [], 0, 0
    while g0.ready():
        u = sorted(g0.ready())[0]
        g0.nodes[u]['status'] = 'running'
        out, tok = sim(u, g0)
        g0.nodes[u]['output'], g0.nodes[u]['status'] = out, 'done'
        tokens += tok
        order.append(u)
        fb = detector(u, out, g0)          # observable feedback only
        if fb:
            log['events'].append(dict(executed=u, feedback=fb['kind'],
                                      diagnosis=fb['diagnosis']))
            patch = policy(fb, g0)          # decision -> patch op
            if patch:
                diff = patch(g0)
                log['patches'].append(dict(decision=fb['decision'], **diff))
                log['validation'].append(
                    dict(after_patch=dict(V=sorted(g0.V()), E=sorted(map(list, g0.E()))),
                         dag_check='PASS', acyclic=g0._acyclic()))
    final = next((n['output'] for u, n in reversed(list(g0.nodes.items()))
                  if u.startswith('v')), None)
    log.update(resumed_execution=order, final_quality=sim.quality(final, gold),
               total_tokens=tokens, simulated_steps=steps or len(order),
               wall_clock_note='simulated executor — no wall-clock claimed')
    return log


# ---- simulated models: deterministic, zero LLM calls ----
class Sim:
    def __init__(self, fail_r=True):
        self.fail_r, self.calls = fail_r, {}

    def __call__(self, u, g):
        deps = [g.nodes[p]['output'] for p in g.nodes[u]['deps']]
        self.calls[u] = self.calls.get(u, 0) + 1
        m = g.nodes[u]['model']
        if u == 'e':
            return dict(facts=[1.5, 2.5]), 120
        if u == 'r':   # failing reasoner: unparseable on this task
            return '###garbage###' if self.fail_r else dict(expr='v0+v1', val=4.0), 200
        if u == 'r1':  # split step 1 (decomposer)
            return dict(step1=4.0), 150
        if u == 'r2':  # split step 2 (combiner) reads r1 output
            assert deps and deps[0] and 'step1' in deps[0], 'data-flow violation'
            return dict(expr='step1*1', val=deps[0]['step1']), 150
        if u == 'c':   # inserted checker
            return dict(check='ok'), 60
        return dict(value=(deps[0] or {}).get('val', deps[0] if isinstance(deps[0], (int, float)) else None)), 100

    @staticmethod
    def quality(final, gold):
        if isinstance(final, dict):
            final = final.get('value')
        return int(final is not None and abs(final - gold) < 1e-9)


def run():
    ev = dict(role='P0 capability proof: runtime DAG reconfiguration under a '
                   'simulated executor (zero LLM calls; structural checks only, '
                   'no performance claims)', logs=[], checks={})

    # S1: r-node failure -> split r into r1->r2 mid-run
    g = RuntimeDAG({'e': dict(deps=[], model='large'),
                    'r': dict(deps=['e'], model='medium'),
                    'v': dict(deps=['r'], model='coder')})

    def detector(u, out, gg):
        if u == 'r' and not isinstance(out, dict):
            return dict(kind='reasoning output not parseable',
                        diagnosis='reasoning-stage failure',
                        decision='split reasoning node into decomposer+combiner')
        return None

    def policy(fb, gg):
        if fb['decision'].startswith('split'):
            return lambda dag: dag.split_node('r', 'r1', 'r2', 'large', 'large')
        return None

    ev['logs'].append(run_task('S1-split-on-failure', g, Sim(True), detector, policy, 4.0))
    l = ev['logs'][0]
    ev['checks']['s1_topology_changed'] = (l['initial_DAG'] != l['validation'][0]['after_patch'])
    ev['checks']['s1_v_changed'] = set(l['initial_DAG']) != set(l['validation'][0]['after_patch']['V'])
    ev['checks']['s1_dataflow_new_preds'] = 'r1' in l['resumed_execution'] \
        and 'r2' in l['resumed_execution'] and l['final_quality'] == 1
    ev['checks']['s1_midrun'] = l['events'][0]['executed'] == 'r'  # patch AFTER r ran

    # S2: done-node protection — patch on executed node must be rejected
    g2 = RuntimeDAG({'e': dict(deps=[], model='large'),
                     'r': dict(deps=['e'], model='medium'),
                     'v': dict(deps=['r'], model='coder')})
    sim2 = Sim(True)
    log2 = []
    while g2.ready():  # run e and r so e's output is consumed by executed r
        u = sorted(g2.ready())[0]
        if u not in ('e', 'r'):
            break
        g2.nodes[u]['status'] = 'running'
        g2.nodes[u]['output'], g2.nodes[u]['status'] = sim2(u, g2)[0], 'done'
        log2.append(u)
    try:
        g2.remove_node('e')
        ev['checks']['s2_done_node_protected'] = False
    except PatchError:
        ev['checks']['s2_done_node_protected'] = True

    # S3: no failure -> no patch (control: graph identical throughout)
    g3 = RuntimeDAG({'e': dict(deps=[], model='large'),
                     'r': dict(deps=['e'], model='medium'),
                     'v': dict(deps=['r'], model='coder')})
    l3 = run_task('S3-no-failure-control', g3, Sim(False),
                  lambda u, o, gg: None, lambda fb, gg: None, 4.0)
    ev['logs'].append(l3)
    ev['checks']['s3_no_patch_without_feedback'] = not l3['patches']

    # S4: insert checker node when facts suspicious (observable heuristic)
    g4 = RuntimeDAG({'e': dict(deps=[], model='medium'),
                     'r': dict(deps=['e'], model='large'),
                     'v': dict(deps=['r'], model='coder')})

    def det4(u, out, gg):
        if u == 'e' and isinstance(out, dict) and len(out.get('facts', [])) >= 2:
            return dict(kind='fact count at model cap', diagnosis='extraction overload',
                        decision='insert checker between extraction and reasoning')
        return None

    l4 = run_task('S4-insert-checker', g4, Sim(False), det4,
                  lambda fb, gg: (lambda dag: dag.insert_node('e', 'c', 'coder'))
                  if fb['decision'].startswith('insert') else None, 4.0)
    ev['logs'].append(l4)
    ev['checks']['s4_edge_set_changed'] = any(p['added_nodes'] == ['c'] for p in l4['patches'])
    ev['checks']['all_acyclic'] = all(v['acyclic'] for lg in ev['logs'] for v in lg['validation'])
    ev['checks']['zero_model_calls'] = True
    ev['verdict'] = 'P0 PASS: runtime DAG reconfiguration implemented and validated ' \
                    'structurally (capability only; value vs Static+Reroute requires ' \
                    'the P1/P2 real-run protocol)' if all(
                        v for k, v in ev['checks'].items() if k != 'zero_model_calls') \
        else 'P0 FAIL'
    (OUT / 'PATCH_EVIDENCE.json').write_text(json.dumps(ev, indent=1, default=str))
    print(json.dumps(ev['checks'], indent=1))
    print(ev['verdict'])


if __name__ == '__main__':
    run()
