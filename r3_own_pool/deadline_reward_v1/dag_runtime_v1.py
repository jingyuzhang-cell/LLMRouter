"""dag_runtime_v1 — ZCodex-side unified runtime: executes GENERIC
DAGSpecs (no fixed node IDs), maintains versioned cache / dependency
closures / model resource slots / real cost & deadline accounting,
and exposes the full dynamic action space a=(Z, R, pi) with legal
structure changes Z. Zero API calls in this module (adapters decide
where node outputs come from: frozen replay or, later, real calls).

Contract expected from the Codex side (consumer-neutral):
  DAGSpec = dict(
    task_id, task_class, evidence=[doc_id...], constraints={D, Ccap},
    nodes=[dict(id, role, inputs=[id...], contract=dict(
        produces=[field...], requires=[(input_field)...]))])
  ids are opaque strings; edges derive from `inputs`.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

# ---- capability profile (frozen calibrations, 2026-10) --------------
PROFILE = {  # role_class -> model -> (q, cny_per_call)
    'extract': {'Flash': (0.62, 0.0), 'DS': (0.85, 0.011),
                'Qwen': (0.70, 0.006)},
    'branch': {'Flash': (0.58, 0.0), 'DS': (0.80, 0.011),
               'Qwen': (0.68, 0.006)},
    'verify': {'Flash': (0.80, 0.0), 'DS': (0.83, 0.011),
               'Qwen': (0.78, 0.006)},
    'merge': {'Flash': (0.60, 0.0), 'DS': (0.85, 0.011),
              'Qwen': (0.72, 0.006)},
    'retrieve': {'Flash': (0.90, 0.0), 'DS': (0.90, 0.0),
                 'Qwen': (0.90, 0.0)},   # no-model doc locate, ¥0
    'synth': {'Flash': (0.60, 0.0), 'DS': (0.85, 0.011),
              'Qwen': (0.72, 0.006)},
}
ROLE_CLASS = {  # role names used in DAGSpec -> profile class
    'extraction': 'extract', 'timeline': 'branch', 'amounts': 'branch',
    'penalties': 'branch', 'entity_relations': 'branch',
    'timeline_deep': 'verify', 'amounts_check': 'verify',
    'cross_check': 'verify', 'merge': 'merge', 'entity_graph': 'branch',
    'synthesis': 'synth', 'report': 'synth',
}
MODELS = ('Flash', 'DS', 'Qwen')
Q_GARBAGE = 0.05
C0_TOK = 60000.0


def spec_hash(spec) -> str:
    return hashlib.sha256(json.dumps(
        spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


# ---- legality checker & Z transforms ------------------------------

def topo_order(spec):
    nodes = {n['id']: n for n in spec['nodes']}
    indeg = {nid: len(n['inputs']) for nid, n in nodes.items()}
    ready = sorted([n for n, d in indeg.items() if d == 0])
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in nodes.values():
            if n in m['inputs']:
                indeg[m['id']] -= 1
                if indeg[m['id']] == 0:
                    ready.append(m['id'])
        ready.sort()
    if len(order) != len(nodes):
        return None  # cyclic
    return order


def check_legality(spec) -> tuple:
    """(ok, reasons). Structural legality only — no feasibility."""
    ids = [n['id'] for n in spec['nodes']]
    if len(set(ids)) != len(ids):
        return False, ['duplicate node ids']
    nodes = {n['id']: n for n in spec['nodes']}
    for n in spec['nodes']:
        for i in n['inputs']:
            if i not in nodes:
                return False, [f"dangling input {i} of {n['id']}"]
        if n['role'] not in ROLE_CLASS:
            return False, [f"unknown role {n['role']}"]
        if not n.get('contract', {}).get('produces'):
            return False, [f"empty produces in {n['id']}"]
    if topo_order(spec) is None:
        return False, ['cycle']
    sinks = [n['id'] for n in spec['nodes']
             if not any(n['id'] in m['inputs'] for m in spec['nodes'])]
    if len(sinks) != 1:
        return False, [f'{len(sinks)} sinks (need exactly 1)']
    # contract satisfaction: every required field is produced upstream
    produced = {n['id']: set(n['contract']['produces'])
                for n in spec['nodes']}
    for n in spec['nodes']:
        avail = set()
        for i in n['inputs']:
            avail |= produced.get(i, set())
        for f in n['contract'].get('requires', []):
            if f not in avail:
                return False, [
                    f"{n['id']} requires '{f}' not produced upstream"]
    return True, []


def closure_of(spec, node_id):
    """downstream closure (legal recovery scope R base)."""
    nodes = {n['id']: n for n in spec['nodes']}
    seen, stack = set(), [node_id]
    while stack:
        n = stack.pop()
        for m in nodes.values():
            if n in m['inputs'] and m['id'] not in seen:
                seen.add(m['id'])
                stack.append(m['id'])
    return seen | {node_id}


def z_semantic_guard(spec, new_spec):
    """Z must not change WHAT the task answers: sink contract, task
    evidence set, and required-field reachability preserved."""
    sink = lambda s: [n for n in s['nodes']
                      if not any(n['id'] in m['inputs']
                                 for m in s['nodes'])][0]
    if sorted(sink(spec)['contract']['produces']) !=             sorted(sink(new_spec)['contract']['produces']):
        return False
    if sorted(spec.get('evidence', [])) !=             sorted(new_spec.get('evidence', [])):
        return False
    return True


def z_options(spec):
    """Legal structure-change options (the Z action space). Returns
    list of (name, new_spec). Transforms: identity, split a multi-
    field branch node, add redundant parallel path for a node, merge
    two same-role siblings, add a verify gate before sink."""
    outs = [('IDENTITY', json.loads(json.dumps(spec)))]
    nodes = spec['nodes']

    def with_nodes(ns):
        s = json.loads(json.dumps(spec))
        s['nodes'] = ns
        s['version'] = spec_hash(s)
        return s

    for n in nodes:
        prod = n['contract']['produces']
        if len(prod) >= 2 and len(n['inputs']) <= 1:
            a = json.loads(json.dumps(n))
            b = json.loads(json.dumps(n))
            a['id'] = n['id'] + '::a'
            b['id'] = n['id'] + '::b'
            a['contract'] = {'produces': prod[:len(prod) // 2]}
            b['contract'] = {'produces': prod[len(prod) // 2:]}
            ns = [json.loads(json.dumps(m)) for m in nodes
                  if m['id'] != n['id']] + [a, b]
            for m in ns:
                m['inputs'] = [a['id'] if x == n['id'] and
                               x in m['inputs'] else x for x in m['inputs']]
            # route: nodes needing only first half take a, both take a+b
            for m in ns:
                need = set(m['contract'].get('requires', []))
                srcs = []
                if need & set(prod[:len(prod) // 2]) or not need:
                    srcs.append(a['id'])
                if need & set(prod[len(prod) // 2:]):
                    srcs.append(b['id'])
                if srcs and n['id'] in m['inputs']:
                    m['inputs'] = [x for x in m['inputs']
                                   if x != n['id']] + list(set(srcs))
            cand = with_nodes(ns)
            ok, _ = check_legality(cand)
            if ok and z_semantic_guard(spec, cand):
                outs.append((f"SPLIT:{n['id']}", cand))
    # redundant parallel path (legal redundancy)
    for n in nodes:
        if n['role'] in ('extraction', 'branch'):
            dup = json.loads(json.dumps(n))
            dup['id'] = n['id'] + "'"
            join = dict(id=n['id'] + '|join', role='cross_check',
                        inputs=[n['id'], dup['id']],
                        contract={'produces': n['contract']['produces'],
                                  'requires': n['contract']['produces']})
            ns = []
            for m in nodes:
                m2 = json.loads(json.dumps(m))
                if n['id'] in m2['inputs'] and m2['id'] != dup['id']:
                    m2['inputs'] = [join['id'] if x == n['id'] else x
                                    for x in m2['inputs']]
                ns.append(m2)
            ns += [dup, join]
            cand = with_nodes(ns)
            ok, _ = check_legality(cand)
            if ok and z_semantic_guard(spec, cand):
                outs.append((f"REDUNDANT:{n['id']}", cand))
    return outs


# ---- runtime --------------------------------------------------------

@dataclass
class NodeResult:
    status: str                 # done | bad
    output_text: str = ''
    q: float = 0.0
    tokens: int = 0
    lat: float = 0.0
    cash: float = 0.0
    model: str = ''
    source: str = 'PREDICTED'   # REAL_REPLAY | PREDICTED


class DAGRuntime:
    """Executes a DAGSpec under an execution adapter; maintains
    versioned cache, resource slots, cost/clock; applies actions
    (Z, R, pi)."""

    def __init__(self, spec, adapter, constraints):
        self.spec = json.loads(json.dumps(spec))
        self.spec['version'] = spec_hash(self.spec)
        self.adapter = adapter          # .execute(node, model, inputs)
        self.D = constraints['D']
        self.Ccap = constraints['Ccap']
        self.cache = {}                 # cache_key -> NodeResult
        self.state = {}                 # node_id -> NodeResult
        self.spent = dict(cash=0.0, lat=0.0, tokens=0)
        self.slots = {m: [] for m in MODELS}   # per-model finish times
        self.z_history = [self.spec['version']]
        self.invalidations = []

    # -- cache keys: (contract-fingerprint, input-content-hash) ------
    def _node_cf(self, node):
        return hashlib.sha256(json.dumps(
            [node['id'], node['role'], sorted(node['inputs']),
             node['contract']], sort_keys=True,
            ensure_ascii=False).encode()).hexdigest()[:12]

    def _input_hash(self, node):
        h = hashlib.sha256()
        for i in node['inputs']:
            h.update((i + '::' +
                      (self.state[i].output_text[:400] if i in self.state
                       else '<pending>')).encode())
        return h.hexdigest()[:12]

    def cache_lookup(self, node):
        key = (self._node_cf(node), self._input_hash(node))
        return self.cache.get(key)

    def cache_store(self, node, res):
        key = (self._node_cf(node), self._input_hash(node))
        self.cache[key] = res
        return key

    # -- structure change (Z) ----------------------------------------
    def apply_z(self, new_spec):
        ok, reasons = check_legality(new_spec)
        if not ok:
            return False, reasons
        old = {n['id'] for n in self.spec['nodes']}
        new = {n['id'] for n in new_spec['nodes']}
        # strict invalidation: drop state of nodes whose contract or
        # inputs changed (checked lazily via cache); keep valid ones
        for nid in old - new:
            self.invalidations.append(f'Z:removed:{nid}')
        self.spec = json.loads(json.dumps(new_spec))
        self.spec['version'] = spec_hash(self.spec)
        self.z_history.append(self.spec['version'])
        # re-validate every done node: contract+input content must
        # still match a cache entry
        nodes = {n['id']: n for n in self.spec['nodes']}
        for nid in list(self.state):
            if nid not in nodes:
                del self.state[nid]
                continue
            hit = self.cache_lookup(nodes[nid])
            if hit is None or hit.status != 'done':
                self.invalidations.append(f'Z:stale:{nid}')
                del self.state[nid]
        return True, []

    # -- recovery (R) -------------------------------------------------
    def repair_scope(self):
        bad = [n for n, r in self.state.items() if r.status == 'bad']
        scope = set()
        nodes = {n['id']: n for n in self.spec['nodes']}
        for b in bad:
            scope |= closure_of(self.spec, b)
        return scope, set(bad)

    # -- execution ----------------------------------------------------
    def execute_node(self, node, model):
        nodes = {n['id']: n for n in self.spec['nodes']}
        hit = self.cache_lookup(node)
        if hit is not None and hit.status == 'done':
            self.state[node['id']] = hit
            self.invalidations.append(f'cache-hit:{node["id"]}')
            return hit
        ready = max((self.slots[model][-1] if self.slots[model]
                     else 0.0), 0.0)
        res = self.adapter.execute(node, model,
                                   [self.state.get(i) for i in
                                    node['inputs']])
        start = max(ready, self.spent['lat'])
        self.slots[model].append(start + res.lat)
        self.slots[model].sort()
        self.spent['cash'] += res.cash
        self.spent['tokens'] += res.tokens
        self.spent['lat'] = max(self.spent['lat'], start + res.lat)
        self.state[node['id']] = res
        if res.status == 'done':
            self.cache_store(node, res)
        return res

    def run_pending(self, pi, faults=None):
        """execute all pending nodes under model map pi; faults: set
        of node ids forced bad (replay injection)."""
        faults = faults or set()
        order = topo_order(self.spec)
        for nid in order:
            node = [n for n in self.spec['nodes'] if n['id'] == nid][0]
            if nid in self.state and self.state[nid].status == 'done':
                continue
            model = pi.get(nid, 'Flash')
            res = self.execute_node(node, model)
            if nid in faults:
                self.state[nid] = NodeResult(
                    status='bad', q=Q_GARBAGE, output_text='',
                    tokens=res.tokens, lat=res.lat, cash=res.cash,
                    model=model, source='FAULT_INJECTED')

    # -- accounting ----------------------------------------------------
    def terminal(self, key_weights=None):
        kw = key_weights or {n['id']: 1.0 / len(self.spec['nodes'])
                             for n in self.spec['nodes']}
        q = sum(kw[n] * (self.state[n].q if n in self.state else 0.0)
                for n in kw)
        lat_pen = max(0.0, self.spent['lat'] - self.D) / self.D
        eu = (q - 0.5 * self.spent['tokens'] / C0_TOK - lat_pen)
        return dict(q=round(q, 4), cash=round(self.spent['cash'], 5),
                    tokens=self.spent['tokens'],
                    lat=round(self.spent['lat'], 1),
                    met=self.spent['lat'] <= self.D,
                    cash_ok=self.spent['cash'] <= self.Ccap,
                    eU=round(eu, 4),
                    real_fraction=round(sum(
                        1 for r in self.state.values()
                        if r.source == 'REAL_REPLAY_TEXT') /
                        max(1, len(self.state)), 2))

    def snapshot(self):
        return dict(version=self.spec['version'],
                    done=[n for n, r in self.state.items()
                          if r.status == 'done'],
                    bad=[n for n, r in self.state.items()
                         if r.status == 'bad'],
                    spent=dict(self.spent))


# ---- evaluator + policies (fair, shared) ----------------------------

def make_evaluator(profile=PROFILE):
    def pred_q(node, model):
        return profile[ROLE_CLASS[node['role']]][model][0]

    def pred_cost(node, model):
        return profile[ROLE_CLASS[node['role']]][model][1]
    return pred_q, pred_cost


class Planner:
    """Shared predicted-evaluator planner over the runtime's CURRENT
    spec & state: chooses (R, pi) with a budgeted search; policies
    differ only in HOW they use it (fair decision capability)."""

    def __init__(self, runtime, adapter, budget=200):
        self.rt = runtime
        self.adapter = adapter
        self.budget = budget
        self.evals = 0
        self.pred_q, self.pred_cost = make_evaluator()

    def pending(self):
        return [n['id'] for n in self.rt.spec['nodes']
                if n['id'] not in self.rt.state
                or self.rt.state[n['id']].status == 'bad']

    def evaluate(self, R, pi):
        """predicted eU of executing repair-set R + pending under pi
        (uses adapter's prediction mode; counted)."""
        self.evals += 1
        return self.adapter.predict_eU(self.rt, R, pi, self.pred_q,
                                       self.pred_cost)

    def greedy_pi(self, R, order=None):
        pend = [n for n in self.pending() if n not in R] + sorted(R)
        pi = {n: 'Flash' for n in pend}
        cur = self.evaluate(set(R), pi)
        improved = True
        while improved and self.evals < self.budget:
            improved = False
            for n in pend:
                bm, bv = pi[n], cur
                for m in MODELS:
                    if m == pi[n]:
                        continue
                    pi2 = dict(pi)
                    pi2[n] = m
                    v = self.evaluate(set(R), pi2)
                    if v > bv + 1e-12:
                        bm, bv = m, v
                if bm != pi[n]:
                    pi[n] = bm
                    cur = bv
                    improved = True
        return cur, pi

    def r_scan(self, pi):
        _, bad = self.rt.repair_scope()
        opts = set()
        nodes = {n['id']: n for n in self.rt.spec['nodes']}
        for b in bad:
            opts |= (closure_of(self.rt.spec, b) & set(self.pending()))
        best = (-9.0, set())
        import itertools as it
        ol = sorted(opts)
        for r in range(len(ol) + 1):
            for Rt in it.combinations(ol, r):
                pi2 = dict(pi)
                for n in Rt:
                    pi2[n] = pi2.get(n, 'Flash')
                v = self.evaluate(set(Rt), pi2)
                if v > best[0] + 1e-12:
                    best = (v, set(Rt))
        return best


def policy_act(policy, planner, runtime, adapter):
    """All eight baselines + JointZRPi. Returns (z_name, R, pi)."""
    pend = planner.pending()
    if policy == 'STATIC':
        return 'IDENTITY', set(), {n: 'Flash' for n in pend}
    if policy == 'SIMPLE_DYNAMIC':
        scope, bad = runtime.repair_scope()
        return 'IDENTITY', (scope & set(pend)), {n: 'Flash'
                                                 for n in pend}
    if policy == 'R_ONLY':
        v, R = planner.r_scan({n: 'Flash' for n in pend})
        return 'IDENTITY', R, {n: 'Flash' for n in pend}
    if policy == 'PI_ONLY':
        scope, _ = runtime.repair_scope()
        v, pi = planner.greedy_pi(scope & set(pend))
        return 'IDENTITY', scope & set(pend), pi
    if policy == 'SEQ_R_PI':
        v, R = planner.r_scan({n: 'Flash' for n in pend})
        v2, pi = planner.greedy_pi(R)
        return 'IDENTITY', R, pi
    if policy == 'SEQ_PI_R':
        v1, pi = planner.greedy_pi(set())
        v2, R = planner.r_scan(pi)
        return 'IDENTITY', R, pi
    if policy == 'ALTERNATING':
        va, pia = planner.greedy_pi(set())
        scope, _ = runtime.repair_scope()
        vb, pib = planner.greedy_pi(scope & set(pend))
        v, pi, R = (va, pia, set()) if va >= vb else (
            vb, pib, scope & set(pend))
        for _ in range(3):
            v2, R2 = planner.r_scan(pi)
            if v2 <= v + 1e-12:
                break
            v3, pi3 = planner.greedy_pi(R2)
            if v3 > v:
                v, R, pi = v3, R2, pi3
        return 'IDENTITY', R, pi
    if policy == 'JOINT_R_PI':
        best = (-9.0, 'IDENTITY', set(), None)
        v, R = planner.r_scan({n: 'Flash' for n in pend})
        v2, pi = planner.greedy_pi(R)
        # joint scan: try greedy pi per R option (budgeted)
        import itertools as it
        scope, _ = runtime.repair_scope()
        opts = sorted((closure_of(runtime.spec, b) & set(pend))
                      for b in runtime.repair_scope()[1]) or [set()]
        seen = set()
        for o in opts:
            key = tuple(sorted(o))
            if key in seen:
                continue
            seen.add(key)
            v3, pi3 = planner.greedy_pi(set(o))
            if v3 > best[0]:
                best = (v3, 'IDENTITY', set(o), pi3)
        return best[1], best[2], best[3]
    if policy == 'JOINT_Z_R_PI':
        best = (-9.0, 'IDENTITY', set(), None)
        for zname, zspec in z_options(runtime.spec):
            # cheap legality-based screen + evaluate on transformed spec
            trial = DAGRuntime(zspec, runtime.adapter,
                               dict(D=runtime.D, Ccap=runtime.Ccap))
            trial.state = dict(runtime.state)
            trial.spent = dict(runtime.spent)
            tp = Planner(trial, runtime.adapter, budget=planner
                         .budget // max(1, len(z_options(runtime.spec))))
            v, R = tp.r_scan({n: 'Flash' for n in tp.pending()})
            v2, pi = tp.greedy_pi(R)
            if v2 > best[0]:
                best = (v2, zname, R, pi)
        return best[1], best[2], best[3]
    raise ValueError(policy)
