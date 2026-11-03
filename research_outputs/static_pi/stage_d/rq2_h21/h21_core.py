"""RQ2-H2.1 three-arm execution core (offline-testable; zero calls by default).

DAG (original, 7 nodes): e0,e1 -> t(e0), m(e0,e1) -> r(m), v(m,t) -> p(r,v)
Arm C replaces v with v_pre (deterministic code, reads only e0,e1,t) running
concurrently with m, then v_post (reads m + v_pre), which must emit all v facts.

The runner records per-node (start,end) wall-clock timestamps; makespan is the
end of p minus the start of the earliest node. Provider is injectable so the
same code runs with a mock (offline) or the real transport (after authorization).
"""
import threading, time, json

NODES = ('e0', 'e1', 't', 'm', 'r', 'v', 'p')
ARMS = ('A', 'B', 'C')
GLM, DS = 0, 1


def arm_models(arm):
    if arm == 'A':
        return {n: DS for n in NODES}
    if arm == 'B':
        return {n: (GLM if n in ('m', 'v') else DS) for n in NODES}
    if arm == 'C':
        # v is split: v_pre is code (no model), v_post is GLM
        return {n: (GLM if n in ('m', 'v_post') else DS) for n in ('e0', 'e1', 't', 'm', 'r', 'v_post', 'p')}
    raise ValueError(arm)


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []

    def mark(self, node, phase, t):
        with self.lock:
            self.events.append(dict(node=node, phase=phase, t=t))

    def window(self, node):
        s = [e['t'] for e in self.events if e['node'] == node and e['phase'] == 'start']
        e = [e['t'] for e in self.events if e['node'] == node and e['phase'] == 'end']
        return (min(s), max(e)) if s and e else (None, None)


def _run_node(rec, node, fn, deps, outputs):
    for d in deps:
        while d not in outputs:
            time.sleep(0.002)
    rec.mark(node, 'start', time.monotonic())
    out = fn(node, outputs)
    rec.mark(node, 'end', time.monotonic())
    outputs[node] = out
    return out


def run_execution(arm, task, call_model, v_pre_fn, v_post_fn, v_pre_deps=('e0', 'e1', 't')):
    """Execute one end-to-end run. call_model(node, model, inputs) -> output dict.
    v_pre_fn(inputs) -> verification table (deterministic code; must not see m).
    v_post_fn(inputs) -> v facts (must see m and v_pre)."""
    m = arm_models(arm)
    rec, out = Recorder(), {}
    t0 = time.monotonic()
    threads = []

    def spawn(node, deps):
        def fn(n, outputs):
            inputs = {d: outputs[d] for d in deps}
            return call_model(n, m[n], inputs)
        th = threading.Thread(target=_run_node, args=(rec, node, fn, deps, out))
        th.start(); threads.append(th)

    spawn('e0', [])
    spawn('e1', [])
    spawn('t', ['e0'])
    spawn('m', ['e0', 'e1'])

    if arm in ('A', 'B'):
        spawn('v', ['m', 't'])
    else:
        # v_pre runs as code, concurrently with m; inputs strictly whitelisted
        def vpre_node(n, outputs):
            inputs = {d: outputs[d] for d in v_pre_deps}   # no m by construction
            return v_pre_fn(inputs)
        th = threading.Thread(target=_run_node, args=(rec, 'v_pre', vpre_node, list(v_pre_deps), out))
        th.start(); threads.append(th)

    for th in threads:
        th.join()
    # second wave
    threads = []
    if arm in ('A', 'B'):
        spawn('r', ['m'])
        spawn('p', ['r', 'v'])
    else:
        spawn('r', ['m'])
        def vpost_node(n, outputs):
            inputs = {'m': outputs['m'], 'v_pre': outputs['v_pre']}
            return v_post_fn(inputs)
        th = threading.Thread(target=_run_node, args=(rec, 'v_post', vpost_node, ['m', 'v_pre'], out))
        th.start(); threads.append(th)
    for th in threads:
        th.join()
    # C: p waits for r and v_post (v_post was joined above)
    if arm == 'C':
        spawn('p', ['r', 'v_post'])
        for th in threads:
            th.join()

    t_end = time.monotonic()
    windows = {n: rec.window(n) for n in rec.events and {e['node'] for e in rec.events}}
    makespan = t_end - t0
    # overlap check for C: v_pre and m must overlap in wall clock
    overlap = None
    if arm == 'C':
        s1, e1_ = rec.window('v_pre'); s2, e2_ = rec.window('m')
        overlap = max(0.0, min(e1_, e2_) - max(s1, s2))
    return dict(arm=arm, outputs=out, windows=windows,
                makespan=makespan, vpre_m_overlap=overlap, models=m)
