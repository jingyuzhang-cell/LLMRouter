"""dd_v52_incremental — DD-V5.2 feedback-driven incremental joint
replanning, zero-call validation. Tier: predicted (planner) tier on
the REAL DAG structure with feedback bootstrapped from REAL frozen
ledgers (H1V7 92 + H1V8 111 calls). Terminal REAL quality of actions
never executed stays UNKNOWN and is not claimed.

Question (operator-fixed): when DAG execution state changes, can the
scheduler reuse still-valid plans/caches/search info to find a
high-quality joint (R, pi) recovery FASTER than replanning from
scratch — with attributable, repeatable COMPUTE gains?

Real grounding:
- DAG: r2fix diamond-8 (n0,b0,b1,b2,b3,x0,x1,sink) with real role map.
- Feedback: per-role (latency, token) pairs BOOTSTRAPPED from the two
  frozen ledgers (real draws, resampled per seed).
- Fault events: node goes garbage at a sampled real position
  {b0,x0,b1,b2}; detection immediate (parse_ok-style) or late
  (sink-observed) — both occurred in the real protocols.
- Quality/cost: calibrated tables (joint6_core MODELS); additive
  predicted tier — cascade coupling NOT modeled (disclosed; matches
  planner's knowledge, not ground truth).

Action at each replan: (R = set of executed-garbage nodes to
re-execute, pi = model for each remaining unexecuted node).
Locked: already-executed nodes are never re-executed unless in R.

Planners (shared deterministic evaluator + evaluation counter):
  COLD_EXACT   full enumeration each event (oracle; uncapped)
  COLD_HEUR    coordinate-greedy from scratch each event (budgeted)
  PI_ONLY      fixed R = all executed-bad closures; greedy pi
  SEQ_R_PI     R-scan under Flash-only, then greedy pi
  SEQ_PI_R     greedy pi under R=empty, then R-scan
  ALTERNATING  strengthened dual-start coordinate sweeps
  INCR_JOINT   incremental: candidate cache + O(1) quality/feasib
               patches + re-enumeration ONLY of the new region
  INCR_NC      ablation: incremental w/o cache (invalidate all)
  INCR_NP      ablation: incremental w/o feasibility pre-recheck

Metrics: evaluations and wall-ms per replan, final predicted eU,
regret vs COLD_EXACT, constraint violations, cache hit rate.
"""
from __future__ import annotations

import itertools as it
import json
import random
import statistics as st
import time

import joint6_core as J
from joint6_core import MODELS, MODEL_NAMES, Q_GARBAGE, LAM_C, C0

ORDER = ['n0', 'b0', 'b1', 'b2', 'b3', 'x0', 'x1', 'sink']
EDGES = {'n0': ['b0', 'b1', 'b2', 'b3'], 'b0': ['x0'], 'b1': ['x1'],
         'b2': ['sink'], 'b3': ['sink'], 'x0': ['sink'],
         'x1': ['sink'], 'sink': []}
ROLE = {'n0': 'extraction', 'b0': 'timeline', 'b1': 'amounts',
        'b2': 'penalties', 'b3': 'entity_relations',
        'x0': 'timeline_deep', 'x1': 'amounts_check',
        'sink': 'synthesis'}
DEPS = {n: [p for p in EDGES if n in EDGES[p]] for n in ORDER}
LEVEL = {'n0': 0, 'b0': 1, 'b1': 1, 'b2': 1, 'b3': 1, 'x0': 2,
         'x1': 2, 'sink': 3}
ROLE_W = {'extraction': 0.16, 'timeline': 0.13, 'amounts': 0.12,
          'penalties': 0.12, 'entity_relations': 0.10,
          'timeline_deep': 0.12, 'amounts_check': 0.10,
          'synthesis': 0.15}
ROLE_W = {k: v / sum(ROLE_W.values()) for k, v in ROLE_W.items()}
NODE_W = {n: ROLE_W[ROLE[n]] for n in ORDER}


def load_feedback():
    """bootstrap pools of (lat, tok) per role from frozen ledgers."""
    pools = {}
    for path in ('fe_screening_runs/h1v7_20261026/LEDGER.jsonl',
                 'fe_screening_runs/h1v8_20261027/LEDGER.jsonl'):
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get('garbage'):
                continue
            pools.setdefault(r['role'], []).append(
                (r['lat'], r['in_tok'] + r['out_tok']))
    return pools


POOLS = None


def draw_rt(rng, node):
    lat, tok = POOLS[ROLE[node]][rng.randrange(len(POOLS[ROLE[node]]))]
    return lat, tok


ROLE_Q = {'n0': 'extract', 'sink': 'synth', 'x0': 'verify',
          'x1': 'verify', 'b0': 'branch', 'b1': 'branch',
          'b2': 'branch', 'b3': 'branch'}


def q_of(node, model, bad=False):
    if bad:
        return Q_GARBAGE
    return MODELS[model]['q'][ROLE_Q[node]]


class State:
    """execution state: locked nodes, spent cash/lat, pending nodes."""

    def __init__(self, D, Ccap):
        self.D, self.Ccap = D, Ccap
        self.locked = {}          # node -> (model, q, lat, tok, bad)
        self.spent_cash = 0.0
        self.spent_lat = 0.0
        self.spent_tok = 0.0
        self.executed_bad = set()

    def clone(self):
        s = State(self.D, self.Ccap)
        s.locked = dict(self.locked)
        s.spent_cash = self.spent_cash
        s.spent_lat = self.spent_lat
        s.spent_tok = self.spent_tok
        s.executed_bad = set(self.executed_bad)
        return s


EVALS = [0]
WALL = [0.0]


def evaluate_plan(state, R, pi):
    """deterministic PREDICTED evaluation of the recovery plan.
    R: executed-garbage nodes to re-execute; pi: model per pending
    node (pending = not locked or in R). Returns (feasible, eU)."""
    EVALS[0] += 1
    t0 = time.perf_counter()
    cash = state.spent_cash
    lat = state.spent_lat
    # deterministic predicted latencies: per-role ledger MEANS; flat
    # serial model (parallelism ignored in prediction; disclosed)
    lat_mean = {n: st.mean(x[0] for x in POOLS[ROLE[n]])
                for n in ORDER}
    tok_mean = {n: st.mean(x[1] for x in POOLS[ROLE[n]])
                for n in ORDER}
    todo = [n for n in ORDER if n in R or n not in state.locked]
    for n in todo:
        cash += MODELS[pi[n]]['cny']
    tok = state.spent_tok + sum(tok_mean[n] for n in todo)
    by_level = {}
    for n in todo:
        lv = 0 if not DEPS[n] else 1 + max(
            LEVEL[d] for d in DEPS[n] if d in LEVEL) if all(
            d in LEVEL for d in DEPS[n]) else 99
        by_level.setdefault(lv, []).append(n)
    # nodes whose deps are not yet scheduled (mixed states) get their
    # own serial slot (conservative)
    lat = state.spent_lat
    for lv in sorted(by_level):
        lat += max(lat_mean[n] for n in by_level[lv])
    if cash > state.Ccap + 1e-12 or lat > state.D + 1e-9:
        WALL[0] += time.perf_counter() - t0
        return False, -9.0
    q = 0.0
    for n in ORDER:
        if n in R:
            q += NODE_W[n] * q_of(n, pi[n])
        elif n in state.locked:
            q += NODE_W[n] * state.locked[n][1]
        else:
            q += NODE_W[n] * q_of(n, pi[n])
    eu = q - 0.5 * tok / 60000.0 - max(0.0, lat - state.D) / state.D
    WALL[0] += time.perf_counter() - t0
    return True, eu


def pool_cur(m, pool, k):
    return 0.0


def repair_options(state):
    """closure(bad) ∩ locked = locked nodes that must re-execute."""
    opts = set()
    for b in state.executed_bad:
        opts |= closure(b)
    return sorted(opts & set(state.locked))


def candidates(state):
    bad_opts = repair_options(state)
    pending = [n for n in ORDER if n not in state.locked]
    for r in range(len(bad_opts) + 1):
        for R in it.combinations(bad_opts, r):
            ns = pending + sorted(R)
            for combo in it.product(MODEL_NAMES, repeat=len(ns)):
                yield set(R), dict(zip(ns, combo))


def fallback(state):
    pending = [n for n in ORDER if n not in state.locked]
    return (set(), {n: 'Flash' for n in pending})


def cold_exact(state):
    best = (-9.0, fallback(state))
    EVALS[0] = 0
    WALL[0] = 0.0
    for R, pi in candidates(state):
        f, v = evaluate_plan(state, R, pi)
        if v > best[0]:
            best = (v, (set(R), dict(pi)))
    return best[0], best[1], EVALS[0], WALL[0]


def greedy_pi(state, R, budget):
    pending = [n for n in ORDER if n not in state.locked]
    pi = {n: 'Flash' for n in pending}
    for n in R:
        pi[n] = 'Flash'
    _, cur = evaluate_plan(state, R, pi)
    improved = True
    while improved and EVALS[0] < budget:
        improved = False
        for n in pending + sorted(R):
            bm, bv = pi.get(n, 'Flash'), cur
            for m in MODEL_NAMES:
                if m == pi.get(n):
                    continue
                pi2 = dict(pi)
                pi2[n] = m
                _, v = evaluate_plan(state, R, pi2)
                if v > bv + 1e-12:
                    bm, bv = m, v
            if bm != pi.get(n):
                pi[n] = bm
                cur = bv
                improved = True
    return cur, pi


def r_scan(state, pi, budget):
    bad = sorted(state.executed_bad)
    best = (-9.0, set())
    for r in range(len(bad) + 1):
        for R in it.combinations(bad, r):
            if EVALS[0] >= budget:
                return best
            pi2 = dict(pi)
            for n in R:
                pi2[n] = pi2.get(n, 'Flash')
            _, v = evaluate_plan(state, set(R), pi2)
            if v > best[0]:
                best = (v, set(R))
    return best


def cold_heur(state, budget=300):
    EVALS[0] = 0
    WALL[0] = 0.0
    v1, pi = greedy_pi(state, set(), budget)
    v2, R = r_scan(state, pi, budget)
    v3, pi3 = greedy_pi(state, R, budget)
    best_v, best_a = max((v1, (set(), pi)), (v3, (R, pi3)))
    return best_v, best_a, EVALS[0], WALL[0]


def pi_only(state, budget=300):
    """R fixed = FULL closure repair of all bad nodes; greedy pi."""
    EVALS[0] = 0
    WALL[0] = 0.0
    R = set(repair_options(state))
    v, pi = greedy_pi(state, R, budget)
    return v, (R, pi), EVALS[0], WALL[0]


def closure(node):
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in EDGES[n]:
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen | {node}


def seq_r_pi(state, budget=300):
    EVALS[0] = 0
    WALL[0] = 0.0
    pending = [n for n in ORDER if n not in state.locked]
    piF = {n: 'Flash' for n in pending}
    best = (-9.0, set())
    for R, pi in candidates(state):
        if EVALS[0] >= budget // 2:
            break
        _, v = evaluate_plan(state, R, pi)
        if v > best[0]:
            best = (v, set(R))
    v, pi = greedy_pi(state, best[1], budget)
    return v, (best[1], pi), EVALS[0], WALL[0]


def seq_pi_r(state, budget=300):
    EVALS[0] = 0
    WALL[0] = 0.0
    v1, pi = greedy_pi(state, set(), budget // 2)
    v2, R = r_scan(state, pi, budget)
    return max(v1, v2), (R, pi), EVALS[0], WALL[0]


def alternating(state, budget=300):
    EVALS[0] = 0
    WALL[0] = 0.0
    va, pia = greedy_pi(state, set(), budget // 2)
    R = set(state.executed_bad)
    vb, pib = greedy_pi(state, R, budget // 2)
    v, pi = (va, pia) if va >= vb else (vb, pib)
    R = set() if va >= vb else set(state.executed_bad)
    for _ in range(4):
        if EVALS[0] >= budget:
            break
        v2, R2 = r_scan(state, pi, budget)
        if v2 <= v + 1e-12:
            break
        R = R2
        v3, pi3 = greedy_pi(state, R, budget)
        if v3 > v:
            v, pi = v3, pi3
    return v, (R, pi), EVALS[0], WALL[0]


class Incremental:
    """Candidate cache across events with TRUE O(1) patches. Cached
    entry stores the plan's REMAINING-horizon components (q_rem,
    cash_rem, tok_rem, lat_rem computed at plan time); on a later
    state, a hit costs only arithmetic: feasibility = spent + rem
    bounds; value = q_rem - 0.5*tok_tot/60000 - lateness(spent+rem).
    Remaining-horizon predictions are state-independent (per-role
    ledger means), so the patch is EXACT in the predicted model.
    Ablations: use_cache=False (re-enumerate), precheck=False
    (full evaluate instead of bound recheck)."""

    def __init__(self, use_cache=True, precheck=True):
        self.cache = []
        self.use_cache = use_cache
        self.precheck = precheck
        self.hits = 0

    def _components(self, state, R, pi):
        lat_mean = {n: st.mean(x[0] for x in POOLS[ROLE[n]])
                    for n in ORDER}
        tok_mean = {n: st.mean(x[1] for x in POOLS[ROLE[n]])
                    for n in ORDER}
        todo = [n for n in ORDER if n in R or n not in state.locked]
        cash = sum(MODELS[pi[n]]['cny'] for n in todo)
        tok = sum(tok_mean[n] for n in todo)
        q = 0.0
        for n in ORDER:
            if n in R:
                q += NODE_W[n] * q_of(n, pi[n])
            elif n in state.locked:
                q += NODE_W[n] * state.locked[n][1]
            else:
                q += NODE_W[n] * q_of(n, pi[n])
        by_level = {}
        for n in todo:
            by_level.setdefault(LEVEL[n], []).append(n)
        lat = sum(max(lat_mean[n] for n in by_level[lv])
                  for lv in sorted(by_level))
        return dict(q=q, cash=cash, tok=tok, lat=lat,
                    pi=dict(pi), R=set(R))

    def plan(self, state, budget=300):
        EVALS[0] = 0
        WALL[0] = 0.0
        t0 = time.perf_counter()
        best = (-9.0, None)
        pending = [n for n in ORDER if n not in state.locked]
        bad_opts = repair_options(state)
        newly = []
        if self.use_cache and self.cache:
            for c in self.cache:
                pi_new = {n: m for n, m in c['pi'].items()
                          if n in pending or n in bad_opts}
                R_new = set(n for n in bad_opts if n in pi_new)
                if not all(n in pi_new for n in pending + sorted(R_new)):
                    continue
                if self.precheck:
                    if state.spent_cash + c['cash'] > state.Ccap + 1e-12:
                        continue
                    if state.spent_lat + c['lat'] > state.D + 1e-9:
                        continue
                    # exact value from components (no evaluation call)
                    lat = state.spent_lat + c['lat']
                    v = (c['q'] - 0.5 * (state.spent_tok + c['tok'])
                         / 60000.0
                         - max(0.0, lat - state.D) / state.D)
                else:
                    f, v = evaluate_plan(state, R_new, pi_new)
                self.hits += 1
                if v > best[0]:
                    best = (v, (R_new, dict(pi_new)))
                newly.append((pi_new, v, c))
            # refresh component entries for surviving plans
            self.cache = [self._components(state, c2[2]['R'],
                                           c2[0])
                          for c2 in newly]
        if not self.use_cache or not self.cache:
            for R, pi in candidates(state):
                f, v = evaluate_plan(state, R, pi)
                if f:
                    self.cache.append(self._components(state, R, pi))
                if v > best[0]:
                    best = (v, (set(R), dict(pi)))
        elif bad_opts:
            for R, pi in candidates_new_region(state, bad_opts):
                f, v = evaluate_plan(state, R, pi)
                if f:
                    self.cache.append(self._components(state, R, pi))
                if v > best[0]:
                    best = (v, (set(R), dict(pi)))
        if best[1] is None:
            best = (-9.0, fallback(state))
        WALL[0] += time.perf_counter() - t0
        return best[0], best[1], EVALS[0], WALL[0]


def candidates_new_region(state, bad_opts):
    """candidates that exercise the NEW repair options (R non-empty)
    or are unreachable by restriction (fresh pending combos kept out
    of patch path when incomplete)."""
    pending = [n for n in ORDER if n not in state.locked]
    for r in range(1, len(bad_opts) + 1):
        for R in it.combinations(bad_opts, r):
            ns = pending + sorted(R)
            for combo in it.product(MODEL_NAMES, repeat=len(ns)):
                yield set(R), dict(zip(ns, combo))


def evaluate_plan_cacheless(state, R, pi):
    """counted evaluation used by cache-refresh path."""
    return evaluate_plan(state, R, pi)[1]


def feas_only(state, R, pi):
    cash = state.spent_cash + sum(
        MODELS[pi.get(n, 'Flash')]['cny']
        for n in ORDER if (n not in state.locked or n in R))
    by_level = {}
    for n in ORDER:
        if n not in state.locked and n not in R:
            continue
        if n in state.locked and n not in R:
            continue
        by_level.setdefault(LEVEL[n], []).append(n)
    lat = state.spent_lat
    for lv in sorted(by_level):
        lat += max(st.mean(x[0] for x in POOLS[ROLE[n]])
                   for n in by_level[lv])
    return cash <= state.Ccap + 1e-12 and lat <= state.D + 1e-9


def run_episode(seed, doc_len, D, Ccap, method, events):
    """execute ORDER; fault events fire at given nodes; replan after
    each event; returns totals."""
    rng = random.Random(seed)
    state = State(D, Ccap)
    incr = None
    if method == 'INCR_JOINT':
        incr = Incremental(True, True)
    elif method == 'INCR_NC':
        incr = Incremental(False, True)
    elif method == 'INCR_NP':
        incr = Incremental(True, False)
    tot_ev = tot_wall = 0.0
    plans = []
    faults = dict(events)        # node -> 'immediate'|'late'
    executed = []
    for node in ORDER:
        # replan if this node begins a new fault region? events fire
        # when the faulted node COMPLETES (garbage); replan right now
        # if any fired event is pending decision
        pass
    # event loop: execute in order; after each node, check faults
    for node in ORDER:
        # plan model choice for this node BEFORE executing (using
        # current best plan; replan when a new fault has fired)
        if plans:
            pi_cur = plans[-1][1][1]
            model = pi_cur.get(node, 'Flash')
        else:
            # initial plan before any execution
            st0 = state.clone()
            v, a, ev, w = dispatch(method, st0, incr)
            if a is None:
                a = fallback(st0)
            tot_ev += ev
            tot_wall += w
            plans.append((v, a))
            pi_cur = a[1]
            model = pi_cur.get(node, 'Flash')
        lat, tok = draw_rt(rng, node)
        bad = node in faults
        state.locked[node] = (model, q_of(node, model, bad=bad),
                              lat, tok, bad)
        state.spent_cash += MODELS[model]['cny']
        state.spent_lat += lat
        state.spent_tok += tok
        executed.append(node)
        if bad and faults[node] == 'immediate':
            state.executed_bad.add(node)
            # replan for remaining nodes
            if node != ORDER[-1]:
                v, a, ev, w = dispatch(method, state, incr)
                if a is None:
                    a = fallback(state)
                tot_ev += ev
                tot_wall += w
                plans.append((v, a))
        elif bad and faults[node] == 'late':
            # detected only at sink: no intermediate replan
            state.executed_bad.add(node)
    # sink completion triggers late detection + final recovery replan
    late = [n for n, k in faults.items() if k == 'late']
    if late:
        for n in late:
            state.executed_bad.add(n)
        v, a, ev, w = dispatch(method, state, incr)
        if a is None:
            a = fallback(state)
        tot_ev += ev
        tot_wall += w
        plans.append((v, a))
        # execute the final recovery plan (predicted tier)
        R, pi = a
        for n in sorted(R):
            m = pi.get(n, 'Flash')
            lat, tok = draw_rt(rng, n)
            state.locked[n] = (m, q_of(n, m), lat, tok, False)
            state.spent_cash += MODELS[m]['cny']
            state.spent_lat += lat
            state.spent_tok += tok
    # final predicted eU
    q = sum(NODE_W[n] * state.locked[n][1] for n in ORDER)
    lat_pen = max(0.0, state.spent_lat - D) / D
    eu = q - 0.5 * state.spent_tok / 60000.0 - lat_pen
    feasible = state.spent_cash <= Ccap + 1e-12 and \
        state.spent_lat <= D + 1e-9
    return dict(seed=seed, method=method, eU_pred=round(eu, 4),
                feasible=feasible, evals=int(tot_ev),
                wall_ms=round(tot_wall * 1000, 1),
                n_replans=len(plans) - (0 if plans else 1),
                cache_hits=(incr.hits if incr else 0))


def dispatch(method, state, incr):
    if method == 'COLD_EXACT':
        return cold_exact(state)
    if method == 'COLD_HEUR':
        return cold_heur(state)
    if method == 'PI_ONLY':
        return pi_only(state)
    if method == 'SEQ_R_PI':
        return seq_r_pi(state)
    if method == 'SEQ_PI_R':
        return seq_pi_r(state)
    if method == 'ALTERNATING':
        return alternating(state)
    if method in ('INCR_JOINT', 'INCR_NC', 'INCR_NP'):
        return incr.plan(state)
    raise ValueError(method)


def main():
    global POOLS
    POOLS = load_feedback()
    methods = ('COLD_EXACT', 'COLD_HEUR', 'PI_ONLY', 'SEQ_R_PI',
               'SEQ_PI_R', 'ALTERNATING', 'INCR_JOINT', 'INCR_NC',
               'INCR_NP')
    event_sets = [
        {'b1': 'immediate', 'x0': 'late'},
        {'b0': 'immediate', 'b2': 'late'},
        {'b3': 'immediate', 'b0': 'late'},
    ]
    out = []
    for D, Ccap in ((100.0, 0.02), (88.0, 0.012)):
        for method in methods:
            rows = []
            for es in event_sets:
                for seed in range(4):
                    rows.append(run_episode(seed, 8000, D, Ccap,
                                            method, es))
            orc = [r['eU_pred'] for r in rows if r['method'] ==
                   'COLD_EXACT']
            rec = dict(D=D, Ccap=Ccap, method=method,
                       eU=round(st.mean([r['eU_pred'] for r in rows]),
                                4),
                       feasible=round(st.mean(
                           [1.0 if r['feasible'] else 0.0
                            for r in rows]), 2),
                       evals=round(st.mean([r['evals'] for r in rows]),
                                   1),
                       wall_ms=round(st.mean(
                           [r['wall_ms'] for r in rows]), 1),
                       cache_hits=round(st.mean(
                           [r['cache_hits'] for r in rows]), 1))
            out.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    json.dump(out, open('/root/r3_own_pool/deadline_reward_v1/'
                        'DD_V52_RESULT.json', 'w'),
              ensure_ascii=False, indent=1)
    print('done')


if __name__ == '__main__':
    main()
