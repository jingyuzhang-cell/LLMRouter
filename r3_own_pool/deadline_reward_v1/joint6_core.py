"""joint6_core — Tier-1 enumeration-ground-truth platform for JOINT-v6.

Zero API calls; deterministic given seed.

Semantics (faithful to prior joint-action space):
  action = (R, pi): R = subset of faulty nodes to re-execute;
  pi assigns a model to every executed node (R plus optional healthy
  re-runs); healthy kept nodes reuse their outputs ('keep').
  Faulty unrepaired nodes contribute Q_GARBAGE.
  Constraints: cash cap on executed-node prices; deadline on
  prefix + list-schedule of executed nodes on per-model pools with
  concurrency kappa (same-model nodes serialize when kappa=1).

evaluate(R, pi) -> (feasible, eU); infeasible -> -9. All search
methods share one evaluation budget N_eval via a counter.

Methods: ORACLE (exhaustive, uncapped), STATIC, SEQ_R_PI, SEQ_PI_R,
ALTERNATING, PI_ONLY, RANDOM restarts, JOINT_V6 (best-first/DFS over
joint tree with admissible quality bound + Pareto-keep pruning).
"""
from __future__ import annotations

import itertools
import json
import random

MODELS = {
    'Flash': dict(cny=0.0, base_lat=6.7, kappa=1,
                  q=dict(extract=0.62, verify=0.80, synth=0.60,
                         branch=0.58)),
    'DS':    dict(cny=0.011, base_lat=2.4, kappa=1,
                  q=dict(extract=0.85, verify=0.83, synth=0.85,
                         branch=0.80)),
    'Qwen':  dict(cny=0.006, base_lat=4.1, kappa=1,
                  q=dict(extract=0.70, verify=0.78, synth=0.72,
                         branch=0.68)),
}
Q_GARBAGE = 0.05
LAM_C, C0 = 0.5, 0.10
MODEL_NAMES = list(MODELS)


class Inst:
    def __init__(self, n, roles, deps, keys, faults, prefix_lat, D, Ccap,
                 kappa_override=None):
        self.n, self.roles, self.deps = n, roles, deps
        self.keys, self.faults = keys, faults
        self.prefix_lat, self.D, self.Ccap = prefix_lat, D, Ccap
        self.kappa_override = kappa_override or {}

    def kappa(self, m):
        return self.kappa_override.get(m, MODELS[m]['kappa'])

    def mlat(self, m):
        return MODELS[m]['base_lat'] * (1.0 if self.kappa(m) >= 2 else 1.35)

    def eff_q(self, node, model):
        return MODELS[model]['q'][self.roles[node]]

    def q_keep(self, node):
        return MODELS['Flash']['q'][self.roles[node]]


def gen_inst(rng, n, k_faults, D, Ccap, kappa=None):
    roles = (['extract']
             + [rng.choice(['branch', 'branch', 'verify'])
                for _ in range(n - 2)] + ['synth'])
    deps = [[] for _ in range(n)]
    for i in range(1, n - 1):
        deps[i] = [rng.randrange(i)]
    deps[n - 1] = sorted(set(range(max(1, n - 3), n - 1)))
    kw = [rng.random() + 0.2 for _ in range(n)]
    s = sum(kw)
    keys = [x / s for x in kw]
    faults = set(rng.sample(range(1, n - 1), k_faults))
    return Inst(n, roles, deps, keys, faults,
                rng.choice([20.0, 30.0, 40.0]), D, Ccap, kappa)


def levels(inst):
    lv = [0] * inst.n
    for i in range(inst.n):
        lv[i] = 0 if not inst.deps[i] else 1 + max(lv[d] for d in
                                                   inst.deps[i])
    return lv


def evaluate(inst, R, pi, counter):
    """pi: node -> model or 'keep'; executed = {pi != 'keep'};
    require R subset of executed."""
    counter[0] += 1
    exec_set = [i for i in range(inst.n) if pi.get(i, 'keep') != 'keep']
    for i in R:
        if pi.get(i, 'keep') == 'keep':
            return False, -9.0
    cash = sum(MODELS[pi[i]]['cny'] for i in exec_set)
    if cash > inst.Ccap + 1e-12:
        return False, -9.0
    lv = levels(inst)
    pool = {m: [] for m in MODEL_NAMES}
    finish = {}
    for i in sorted(exec_set, key=lambda x: (lv[x], x)):
        m = pi[i]
        ready = max((finish[d] for d in inst.deps[i] if d in finish),
                    default=0.0)
        k = inst.kappa(m)
        start = max(ready, pool[m][-k] if len(pool[m]) >= k else 0.0)
        fin = start + inst.mlat(m)
        pool[m].append(fin)
        pool[m].sort()
        finish[i] = fin
    lat = inst.prefix_lat + (max(finish.values()) if finish else 0.0)
    if lat > inst.D + 1e-9:
        return False, -9.0
    q = 0.0
    for i in range(inst.n):
        if pi.get(i, 'keep') != 'keep':
            q += inst.keys[i] * inst.eff_q(i, pi[i])
        elif i in inst.faults:
            q += inst.keys[i] * Q_GARBAGE
        else:
            q += inst.keys[i] * inst.q_keep(i)
    eU = q - LAM_C * cash / C0 - max(0.0, lat - inst.D) / inst.D
    return True, eU


def evaluate_soft(inst, R, pi, counter):
    """Smooth-constraint surrogate for line search only: same objective
    shape but cash/latency overshoot penalized smoothly instead of -9,
    so infeasible starts have an improving direction toward feasibility.
    Counts against the shared budget (it consumes the same simulator)."""
    counter[0] += 1
    exec_set = [i for i in range(inst.n) if pi.get(i, 'keep') != 'keep']
    cash = sum(MODELS[pi[i]]['cny'] for i in exec_set)
    lv = levels(inst)
    pool = {m: [] for m in MODEL_NAMES}
    finish = {}
    for i in sorted(exec_set, key=lambda x: (lv[x], x)):
        m = pi[i]
        ready = max((finish[d] for d in inst.deps[i] if d in finish),
                    default=0.0)
        k = inst.kappa(m)
        start = max(ready, pool[m][-k] if len(pool[m]) >= k else 0.0)
        fin = start + inst.mlat(m)
        pool[m].append(fin); pool[m].sort()
        finish[i] = fin
    lat = inst.prefix_lat + (max(finish.values()) if finish else 0.0)
    q = 0.0
    for i in range(inst.n):
        if pi.get(i, 'keep') != 'keep':
            q += inst.keys[i] * inst.eff_q(i, pi[i])
        elif i in inst.faults:
            q += inst.keys[i] * Q_GARBAGE
        else:
            q += inst.keys[i] * inst.q_keep(i)
    return (q - LAM_C * cash / C0
            - 4.0 * max(0.0, cash - inst.Ccap) / C0
            - 4.0 * max(0.0, lat - inst.D) / inst.D)


def window(inst):
    """healthy nodes eligible for optional re-run (sink region)."""
    return sorted(set(range(max(1, inst.n - 3), inst.n - 1)))


def oracle(inst, counter, cap=400000):
    best = (-9.0, None)
    dirty = sorted(inst.faults)
    for r in range(len(dirty) + 1):
        for Rt in itertools.combinations(dirty, r):
            R = set(Rt)
            extra_pool = [i for i in window(inst) if i not in R]
            for e in range(0, min(3, len(extra_pool) + 1)):
                for ex in itertools.combinations(extra_pool, e):
                    nodes = sorted(R | set(ex))
                    for combo in itertools.product(MODEL_NAMES,
                                                  repeat=len(nodes)):
                        pi = {i: 'keep' for i in range(inst.n)}
                        for i, m in zip(nodes, combo):
                            pi[i] = m
                        _, v = evaluate(inst, R, pi, counter)
                        if v > best[0]:
                            best = (v, (set(R), dict(pi)))
                        if counter[0] > cap:
                            return best
    return best


def _greedy_pi(inst, R, counter, budget, include_window=True):
    nodes = sorted(R) + ([i for i in window(inst) if i not in R]
                         if include_window else [])
    pi = {i: 'keep' for i in range(inst.n)}
    for i in R:
        pi[i] = 'Flash'
    cur = evaluate_soft(inst, R, pi, counter)
    improved = True
    while improved and counter[0] < budget:
        improved = False
        for i in nodes:
            opts = MODEL_NAMES if i in R else MODEL_NAMES + ['keep']
            bestm, bestv = pi[i], cur
            for m in opts:
                if m == pi[i]:
                    continue
                if m == 'keep' and i in R:
                    continue
                pi2 = dict(pi)
                pi2[i] = m
                v = evaluate_soft(inst, R, pi2, counter)
                if v > bestv + 1e-12:
                    bestm, bestv = m, v
            if bestm != pi[i]:
                pi[i] = bestm
                cur = bestv
                improved = True
            if counter[0] >= budget:
                break
    _, hard = evaluate(inst, R, pi, counter)
    return hard, pi


def _best_R_given(inst, pi, counter, budget):
    dirty = sorted(inst.faults)
    bestR, bestv = set(), -9.0
    for r in range(len(dirty) + 1):
        for Rt in itertools.combinations(dirty, r):
            if counter[0] >= budget:
                break
            _, v = evaluate(inst, set(Rt), pi, counter)
            if v > bestv:
                bestv, bestR = v, set(Rt)
    return bestv, bestR


def static_(inst, counter, budget):
    R = set(inst.faults)
    pi = {i: 'keep' for i in range(inst.n)}
    for i in R:
        pi[i] = 'Flash'
    _, v = evaluate(inst, R, pi, counter)
    return v, (R, pi)


def seq_r_pi(inst, counter, budget):
    dirty = sorted(inst.faults)
    piF = {i: 'keep' for i in range(inst.n)}
    bestR, bestv = set(), -9.0
    for r in range(len(dirty) + 1):
        for Rt in itertools.combinations(dirty, r):
            if counter[0] >= budget:
                break
            pi = dict(piF)
            for i in Rt:
                pi[i] = 'Flash'
            _, v = evaluate(inst, set(Rt), pi, counter)
            if v > bestv:
                bestv, bestR = v, set(Rt)
    v2, pi2 = _greedy_pi(inst, bestR, counter, budget)
    return max(bestv, v2), (bestR, pi2)


def seq_pi_r(inst, counter, budget):
    v1, pi = _greedy_pi(inst, set(), counter, budget)
    v2, R = _best_R_given(inst, pi, counter, budget)
    return max(v1, v2), (R, pi)


def alternating(inst, counter, budget):
    """Strengthened baseline (operator fairness rule): start from the
    better of accept-greedy / repair-greedy, then coordinate-sweep
    R <-> pi until no improvement or budget out."""
    va, pia = _greedy_pi(inst, set(), counter, budget)
    vr, pir = _greedy_pi(inst, set(inst.faults), counter, budget)
    if vr > va:
        v, pi, R = vr, pir, set(inst.faults)
    else:
        v, pi, R = va, pia, set()
    for _ in range(6):
        if counter[0] >= budget:
            break
        v2, R2 = _best_R_given(inst, pi, counter, budget)
        if v2 <= v + 1e-12:
            break
        R = R2
        v3, pi3 = _greedy_pi(inst, R, counter, budget)
        if v3 <= v2 + 1e-12:
            v = v2
            break
        v, pi = v3, pi3
    return v, (R, pi)


def pi_only(inst, counter, budget):
    R = set(inst.faults)
    v, pi = _greedy_pi(inst, R, counter, budget)
    return v, (R, pi)


def random_restart(inst, counter, budget, rng):
    dirty = sorted(inst.faults)
    bestv, bestA = -9.0, None
    while counter[0] < budget:
        R = set(i for i in dirty if rng.random() < 0.7)
        pi = {i: 'keep' for i in range(inst.n)}
        for i in R:
            pi[i] = rng.choice(MODEL_NAMES)
        for i in window(inst):
            if rng.random() < 0.3:
                pi[i] = rng.choice(MODEL_NAMES)
        _, v = evaluate(inst, R, pi, counter)
        if v > bestv:
            bestv, bestA = v, (set(R), dict(pi))
    return bestv, bestA


def joint_v6(inst, counter, budget):
    """DFS over joint tree with: (1) THREE warm starts (accept-greedy,
    repair-greedy, Flash R-scan) so feasibility is never missed;
    (2) cash-aware admissible bound: undecided nodes take the best
    model AFFORDABLE under remaining cap (independent relaxation =
    upper bound); (3) best-affordable-first child ordering; (4) budget
    guard reserving 1/3 for warm-up."""
    order = sorted(range(inst.n), key=lambda i: -inst.keys[i])
    dirty = sorted(inst.faults)
    ws_cap = counter[0] + budget // 3
    cands = []

    va, pia = _greedy_pi(inst, set(), counter, ws_cap)          # accept
    cands.append((va, (set(), pia)))
    vr, pir = _greedy_pi(inst, set(dirty), counter, ws_cap)     # repair
    cands.append((vr, (set(dirty), pir)))
    bestF, bestRF = -9.0, set()                                  # Flash scan
    for r in range(len(dirty) + 1):
        for Rt in itertools.combinations(dirty, r):
            if counter[0] >= ws_cap:
                break
            pi = {i: 'keep' for i in range(inst.n)}
            for i in Rt:
                pi[i] = 'Flash'
            _, v = evaluate(inst, set(Rt), pi, counter)
            if v > bestF:
                bestF, bestRF = v, set(Rt)
    piF = {i: 'keep' for i in range(inst.n)}
    for i in bestRF:
        piF[i] = 'Flash'
    cands.append((bestF, (bestRF, piF)))
    incumbent = [max(cands, key=lambda c: c[0])[0],
                 max(cands, key=lambda c: c[0])[1]]
    evals0 = counter[0]

    def committed_cash(pi_part, repaired, idx):
        c = 0.0
        for j, i in enumerate(order):
            if j < idx:
                m = pi_part.get(i, 'keep')
                if m != 'keep':
                    c += MODELS[m]['cny']
            elif i in inst.faults:
                c += min(MODELS[m]['cny'] for m in MODEL_NAMES)
        return c

    def bound(pi_part, repaired, idx):
        """Admissible upper bound: decided nodes exact; undecided healthy
        take max(q_keep, fractional-knapsack share); undecided faulty
        take fractional-knapsack of affordable repairs (cash relaxation,
        integrality dropped -> upper bound)."""
        qub = 0.0
        slack = inst.Ccap - committed_cash(pi_part, repaired, idx)
        if slack < -1e-12:
            return -1.0
        und_fault, und_healthy = [], []
        for j, i in enumerate(order):
            if j < idx:
                kw = inst.keys[i]
                m = pi_part.get(i, 'keep')
                if m != 'keep':
                    qub += kw * inst.eff_q(i, m)
                elif i in inst.faults and i not in repaired:
                    qub += kw * Q_GARBAGE
                else:
                    qub += kw * inst.q_keep(i)
            elif i in inst.faults:
                und_fault.append(i)
            else:
                und_healthy.append(i)
        # fractional knapsack over budget-quality upgrades
        items = []
        for i in und_fault:
            base = Q_GARBAGE
            best = max(MODELS[m]['q'][inst.roles[i]] for m in MODEL_NAMES)
            mc = min(MODELS[m]['cny'] for m in MODEL_NAMES
                     if MODELS[m]['q'][inst.roles[i]] == best) if best > base else 0.0
            items.append((inst.keys[i], base, best, mc))
        for i in und_healthy:
            base = inst.q_keep(i)
            best = max(MODELS[m]['q'][inst.roles[i]] for m in MODEL_NAMES)
            mc = min(MODELS[m]['cny'] for m in MODEL_NAMES
                     if MODELS[m]['q'][inst.roles[i]] == best)
            items.append((inst.keys[i], base, best, mc))
        # items where upgrade is free (Flash best or already best) get best
        for kw, base, best, mc in items:
            if mc <= 1e-12:
                qub += kw * best
        paid = [(kw, base, best, mc) for kw, base, best, mc in items
                if mc > 1e-12]
        paid.sort(key=lambda t: -(t[0] * (t[2] - t[1])) / t[3])
        rem = max(0.0, slack)
        for kw, base, best, mc in paid:
            if rem <= 1e-12:
                qub += kw * base
                continue
            frac = min(1.0, rem / mc)
            qub += kw * (base + frac * (best - base))
            rem -= frac * mc
        return qub

    def child_order(i, slack):
        ms = sorted(
            [m for m in MODEL_NAMES if MODELS[m]['cny'] <= max(0.0, slack)],
            key=lambda m: -MODELS[m]['q'][inst.roles[i]])
        ms += [m for m in MODEL_NAMES if m not in ms]
        if i in inst.faults:
            return [('rep', m) for m in ms] + [('gar', None)]
        return [('keep', None)] + [('run', m) for m in ms]

    def dfs(pi, repaired, idx):
        if counter[0] - evals0 >= budget - budget // 3:
            return
        if idx == len(order):
            R = set(repaired)
            _, v = evaluate(inst, R, dict(pi), counter)
            if v > incumbent[0]:
                incumbent[0] = v
                incumbent[1] = (set(R), dict(pi))
            return
        i = order[idx]
        slack = inst.Ccap - committed_cash(pi, repaired, idx)
        for kind, m in child_order(i, slack):
            pi2 = dict(pi)
            rep2 = repaired
            if kind == 'rep':
                pi2[i] = m
                rep2 = repaired | {i}
            elif kind == 'run':
                pi2[i] = m
            if bound(pi2, rep2, idx + 1) <= incumbent[0] + 1e-12:
                continue
            dfs(pi2, rep2, idx + 1)
            if counter[0] - evals0 >= budget - budget // 3:
                return

    dfs({i: 'keep' for i in range(inst.n)}, frozenset(), 0)
    return incumbent[0], incumbent[1]


METHODS = dict(STATIC=static_, SEQ_R_PI=seq_r_pi, SEQ_PI_R=seq_pi_r,
               ALTERNATING=alternating, PI_ONLY=pi_only,
               JOINT_V6=joint_v6)


def run_cell(n, kf, D, Ccap, kappa, budget, seeds):
    import statistics as st
    rows = []
    for s in seeds:
        rng = random.Random(s)
        inst = gen_inst(rng, n, kf, D, Ccap, kappa)
        co = [0]
        orc_v, _ = oracle(inst, co, cap=400000)
        row = dict(seed=s, oracle=round(orc_v, 4))
        for name, fn in METHODS.items():
            c2 = [0]
            v, A = fn(inst, c2, budget)
            row[name] = round(v, 4)
            row[name + '_ev'] = c2[0]
        c3 = [0]
        v, _ = random_restart(inst, c3, budget, random.Random(s + 999))
        row['RANDOM'] = round(v, 4)
        rows.append(row)
    agg = dict(n=n, kf=kf, D=D, Ccap=Ccap,
               kappa={k: v for k, v in (kappa or {}).items()} or 'inf',
               budget=budget)
    for m in list(METHODS) + ['RANDOM']:
        agg[m] = round(st.mean(r[m] for r in rows), 4)
    for m in list(METHODS):
        agg[m + '_ev'] = round(st.mean(r[m + '_ev'] for r in rows), 1)
    agg['oracle'] = round(st.mean(r['oracle'] for r in rows), 4)
    agg['feasible_seeds'] = sum(1 for r in rows if r['oracle'] > -8)
    for m in ('SEQ_R_PI', 'SEQ_PI_R', 'ALTERNATING', 'PI_ONLY',
              'RANDOM', 'STATIC'):
        w = sum(1 for r in rows if r['JOINT_V6'] > r[m] + 1e-9)
        t = sum(1 for r in rows if abs(r['JOINT_V6'] - r[m]) <= 1e-9)
        agg[f'J_vs_{m}'] = f'{w}/{t}/{len(rows) - w - t}'
    return agg


def main():
    out = []
    grid = []
    for BUDGET in (100, 300):
        for n in (6, 8, 10):
            for kf in (2, 3):
                for (D, Ccap) in ((30, 0.05), (40, 0.03), (55, 0.02)):
                    for kap in (None, {'Flash': 2}):
                        grid.append((n, kf, D, Ccap, kap, BUDGET))
    for cell in grid:
        n, kf, D, Ccap, kap, bud = cell
        agg = run_cell(n, kf, D, Ccap, kap, bud, seeds=range(10))
        out.append(agg)
        print(json.dumps(agg, ensure_ascii=False), flush=True)
    with open('/root/r3_own_pool/deadline_reward_v1/J0INT6_T1_SWEEP.json',
              'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('sweep done:', len(out), 'cells')


if __name__ == '__main__':
    main()
