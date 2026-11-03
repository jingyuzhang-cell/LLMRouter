"""joint6_verify v2 — M3: information has leverage on the pivot.

Zero API calls; deterministic given seed. Calibration from real data:
H1V8 showed same-condition coverage flips (cov 0.188<->0.562) ->
runtime signals are noisy with sigma_s ~= 0.17.

Hidden state: each faulty node i has true severity sev_i in [0, 0.75]
(quality if ACCEPTED = q_keep(i) - sev_i; if REPAIRED with model m =
q(i, m)). Free noisy signal s_i = sev_i + N(0, sigma_s). VERIFY(i)
reveals sev_i exactly, costs VERIFY_CNY cash and VERIFY_LAT seconds
(counted against both caps). The repair-vs-accept decision hinges on
sev_i -> information about it has decision value.

Methods (same planner for (R, pi) everywhere; only the information
policy differs):
  NEVER   no verifies; plan on posterior-mean severities
  THRESH  hard gate: repair iff s_i > theta_sev (no paid verifies) —
          the H1V8-style fixed threshold
  ALL     verify every faulty node first
  RANDV   verify a random half
  VOI     myopic: verify i iff P(pivotal) * E[value swing] >= verify
          cost, where pivotality is measured by re-planning under the
          posterior 15%/85% severity quantiles
"""
from __future__ import annotations

import itertools as it
import json
import random
import statistics as st

from joint6_core import (MODELS, MODEL_NAMES, Q_GARBAGE, LAM_C, C0,
                         Inst, levels)

SIGMA_S = 0.17          # H1V8-calibrated signal noise
VERIFY_CNY, VERIFY_LAT = 0.004, 2.5
SEV_LO, SEV_HI = 0.0, 0.75
Q_KEEP_BASE = 0.60       # believed/true base quality of a kept node


class VInst(Inst):
    def __init__(self, base, rng):
        self.__dict__.update(base.__dict__)
        self.sev = {i: SEV_LO + (SEV_HI - SEV_LO) * rng.random()
                    for i in self.faults}

    def acc_q(self, i, sev=None):
        """true quality of faulty node i if accepted (severity applies)."""
        s = self.sev[i] if sev is None else sev
        return max(0.02, Q_KEEP_BASE - s)


def sched_ok(inst, R, pi, extra_lat=0.0, extra_cash=0.0):
    exec_set = [i for i in range(inst.n) if pi.get(i, 'keep') != 'keep']
    cash = extra_cash + sum(MODELS[pi[i]]['cny'] for i in exec_set)
    if cash > inst.Ccap + 1e-12:
        return None, None
    lv = levels(inst)
    pool = {m: [] for m in MODEL_NAMES}
    fin = {}
    for i in sorted(exec_set, key=lambda x: (lv[x], x)):
        m = pi[i]
        ready = max((fin[d] for d in inst.deps[i] if d in fin),
                    default=0.0)
        k = inst.kappa(m)
        s0 = max(ready, pool[m][-k] if len(pool[m]) >= k else 0.0)
        f0 = s0 + inst.mlat(m)
        pool[m].append(f0)
        pool[m].sort()
        fin[i] = f0
    lat = inst.prefix_lat + extra_lat + (max(fin.values()) if fin else 0.0)
    if lat > inst.D + 1e-9:
        return None, None
    return cash, lat


EVAL_COUNT = [0]


def value(inst, R, pi, sev_hat, true=False, extra_lat=0.0,
          extra_cash=0.0):
    """eU under severity estimates sev_hat (or true sev if true)."""
    EVAL_COUNT[0] += 1
    cash, lat = sched_ok(inst, R, pi, extra_lat, extra_cash)
    if cash is None:
        return None
    q = 0.0
    for i in range(inst.n):
        if pi.get(i, 'keep') != 'keep':
            q += inst.keys[i] * MODELS[pi[i]]['q'][inst.roles[i]]
        elif i in inst.faults:
            if true:
                q += inst.keys[i] * inst.acc_q(i)
            else:
                q += inst.keys[i] * inst.acc_q(i, sev_hat.get(i, 0.0))
        else:
            q += inst.keys[i] * inst.q_keep(i)
    return q - LAM_C * cash / C0


def plan(inst, sev_hat, extra_lat=0.0, extra_cash=0.0, start_full=True):
    """Greedy (R, pi) under severity estimates; shared by all methods.
    R-scan first (accept/repair per node under beliefs), then pi-greedy."""
    dirty = sorted(inst.faults)

    def v_of(R, pi):
        return value(inst, R, pi, sev_hat, extra_lat=extra_lat,
                     extra_cash=extra_cash)

    best = (-9.0, set(), None)
    for r in range(len(dirty) + 1):
        for Rt in it.combinations(dirty, r):
            pi = {i: 'keep' for i in range(inst.n)}
            for i in Rt:
                pi[i] = 'Flash'
            v = v_of(set(Rt), pi)
            if v is not None and v > best[0] + 1e-12:
                best = (v, set(Rt), pi)
    if best[2] is None:
        return None, None, None
    _, R, pi = best
    nodes = sorted(R) + [i for i in range(max(1, inst.n - 3), inst.n - 1)
                         if i not in R]
    cur = v_of(R, pi)
    improved = True
    while improved:
        improved = False
        for i in nodes:
            opts = MODEL_NAMES if i in R else MODEL_NAMES + ['keep']
            bm, bv = pi[i], cur
            for m in opts:
                if m == pi[i] or (m == 'keep' and i in R):
                    continue
                pi2 = dict(pi)
                pi2[i] = m
                v = v_of(R, pi2)
                if v is not None and v > bv + 1e-12:
                    bm, bv = m, v
            if bm != pi[i]:
                pi[i] = bm
                cur = bv
                improved = True
    return cur, R, pi


def posterior(inst, s):
    """posterior mean/quantiles of sev given signal s (uniform prior
    on [SEV_LO, SEV_HI], gaussian noise SIGMA_S)."""
    import math
    grid = [SEV_LO + (SEV_HI - SEV_LO) * k / 100.0
            for k in range(101)]
    w = [math.exp(-0.5 * ((g - s) / SIGMA_S) ** 2) for g in grid]
    tot = sum(w) or 1.0
    w = [x / tot for x in w]
    mean = sum(gi * wi for gi, wi in zip(grid, w))
    cum = 0.0
    q15 = q85 = mean
    for gi, wi in zip(grid, w):
        cum += wi
        if cum >= 0.15:
            q15 = gi
            break
    cum = 0.0
    for gi, wi in zip(grid, w):
        cum += wi
        if cum >= 0.85:
            q85 = gi
            break
    return mean, q15, q85


def run_method(inst, signals, method, rng, theta_sev=0.35):
    cash_v, lat_v = 0.0, 0.0
    sev_hat = {}
    quants = {}
    for i in inst.faults:
        m, q15, q85 = posterior(inst, signals[i])
        sev_hat[i] = m
        quants[i] = (q15, q85)
    if method == 'THRESH':
        # hard threshold on raw signal: repair iff s_i > theta_sev
        v, R, pi = plan(inst, {i: (0.0 if signals[i] > theta_sev
                                   else SEV_HI)},
                        start_full=False)
        if R is None:
            return None, 0.0, 0
        return value(inst, R, pi, sev_hat, true=True), 0.0, 0
    if method == 'ALL':
        for i in inst.faults:
            cash_v += VERIFY_CNY
            lat_v += VERIFY_LAT
            sev_hat[i] = inst.sev[i]
    elif method == 'RANDV':
        ks = max(1, len(inst.faults) // 2)
        for i in rng.sample(sorted(inst.faults), ks):
            cash_v += VERIFY_CNY
            lat_v += VERIFY_LAT
            sev_hat[i] = inst.sev[i]
    elif method == 'VOI':
        import math
        verified = set()
        while True:
            v0, _, pi0 = plan(inst, sev_hat, lat_v, cash_v)
            if pi0 is None:
                break
            v_before = v0
            best_i, best_evpi = None, 0.0
            for i in sorted(inst.faults):
                if i in verified:
                    continue
                # 5-point posterior grid for sev_i
                grid = [SEV_LO + (SEV_HI - SEV_LO) * k / 100.0
                        for k in range(101)]
                w = [math.exp(-0.5 * ((g - signals[i]) / SIGMA_S) ** 2)
                     for g in grid]
                tot = sum(w) or 1.0
                pts, cum = [], 0.0
                for g, wi in zip(grid, w):
                    cum += wi / tot
                    for target in (0.1, 0.3, 0.5, 0.7, 0.9):
                        if len(pts) < 5 and cum >= target and \
                                (not pts or pts[-1][0] < g - 1e-6):
                            pts.append((g, 0.2))
                v_after = 0.0
                for g, wg in pts:
                    sh = dict(sev_hat)
                    sh[i] = g
                    vg, _, _ = plan(inst, sh, lat_v, cash_v + VERIFY_CNY)
                    if vg is None:
                        vg = v_before - 0.5   # infeasible-after = bad
                    v_after += wg * vg
                evpi = v_after - v_before
                if evpi > VERIFY_CNY + 1e-9 and evpi - VERIFY_CNY > \
                        best_evpi:
                    best_evpi = evpi - VERIFY_CNY
                    best_i = i
            if best_i is None:
                break
            verified.add(best_i)
            cash_v += VERIFY_CNY
            lat_v += VERIFY_LAT
            sev_hat[best_i] = inst.sev[best_i]
    v, R, pi = plan(inst, sev_hat, lat_v, cash_v)
    if R is None:
        return None, cash_v, 0
    return value(inst, R, pi, sev_hat, true=True), cash_v, \
        int(cash_v / VERIFY_CNY)


def main():
    import joint6_core as J
    out = []
    for (D, Ccap, pref) in ((44.0, 0.012, 30.0), (43.0, 0.010, 30.0),
                            (42.0, 0.008, 29.0)):
        rows = {m: [] for m in ('NEVER', 'ALL', 'THRESH', 'RANDV', 'VOI')}
        cash = {m: [] for m in ('ALL', 'RANDV', 'VOI')}
        for seed in range(30):
            rng = random.Random(seed)
            base = J.gen_inst(rng, 8, 3, D, Ccap)
            base.prefix_lat = pref
            inst = VInst(base, rng)
            signals = {i: inst.sev[i] + rng.gauss(0, SIGMA_S)
                       for i in inst.faults}
            for m in rows:
                rng2 = random.Random(seed + 500)
                teu, vc, nv = run_method(inst, signals, m, rng2)
                rows[m].append(teu if teu is not None else -9.0)
                if m in cash:
                    cash[m].append(vc)
        rec = dict(D=D, Ccap=Ccap, prefix=pref)
        for m in rows:
            rec[m] = round(st.mean(rows[m]), 4)
        for m in cash:
            rec[m + '_cash'] = round(st.mean(cash[m]), 5)
        for other in ('THRESH', 'ALL', 'RANDV', 'NEVER'):
            w = sum(1 for s in range(30)
                    if rows['VOI'][s] > rows[other][s] + 1e-9)
            t = sum(1 for s in range(30)
                    if abs(rows['VOI'][s] - rows[other][s]) <= 1e-9)
            rec[f'VOI_vs_{other}'] = f'{w}/{t}/{30 - w - t}'
        out.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    json.dump(out, open('/root/r3_own_pool/deadline_reward_v1/'
                        'JOINT6_M3_VERIFY.json', 'w'),
              ensure_ascii=False, indent=1)
    print('done')


if __name__ == '__main__':
    main()
