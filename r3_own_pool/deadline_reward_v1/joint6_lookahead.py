"""joint6_lookahead — two-stage EVSI lookahead: verify -> posterior
update -> joint (R, pi) replan. The operator-designated single task
for this round. Zero API calls; Tier-1 only.

Hypothesis under test (operator-fixed):
  Under budget+deadline limits, severity uncertainty, and states where
  verification can change the optimal recovery plan, does folding
  VERIFY into the joint lookahead raise expected terminal net utility
  over a strong no-verify posterior joint baseline?

Key distinctions from the falsified myopic-EVPI attempt:
  - EVSI not EVPI: verify observation y = sev + N(0, sigma_v),
    sigma_v = 0.05 > 0 (imperfect verification).
  - honest expectation: plans after each hypothetical observation are
    evaluated under that observation's posterior (risk-neutral, exact
    by linearity in sev), weighted by the observation's predictive.
  - opportunity cost: every verify subtracts cash AND latency from all
    downstream plans (caps reduced inside plan()).
  - compute fairness: every value() call is counted; a budget-matched
    multi-start variant of the no-verify baseline is included.
  - mechanism accounting: we record whether verification actually
    changed the chosen (R, pi), and report value deltas conditional on
    plan-change vs no-change (gains must live where plans change).

Methods:
  PJ        Posterior Joint: plan on posterior means, no verifies
  PJ_MS     PJ + multi-start replanning, budget-matched to LA1's evals
  THRESH    hard signal threshold (H1V8-style gate)
  ALL       verify every fault, then plan
  RANDV     verify a random half
  COSTH     cost-aware heuristic: verify iff posterior (q85-q15)*key
            exceeds verify price
  MEVPI     the earlier myopic EVPI variant (kept for continuity)
  LA1       greedy sequential EVSI with joint replan (the candidate
            algorithm): repeatedly verify argmax-EVSI node while
            EVSI > 0
"""
from __future__ import annotations

import itertools as it
import json
import random
import statistics as st

import joint6_core as J
import joint6_verify as V
from joint6_verify import (VInst, plan, value, VERIFY_CNY, VERIFY_LAT,
                           SEV_LO, SEV_HI)

SIGMA_V = 0.05
GRID = [SEV_LO + (SEV_HI - SEV_LO) * k / 100.0 for k in range(101)]


def post_from_obs(obs, sigma):
    """posterior weights over GRID given observation(s) with noise sd."""
    import math
    w = []
    for g in GRID:
        p = 1.0
        for y, s in obs:
            p *= math.exp(-0.5 * ((g - y) / s) ** 2)
        w.append(p)
    tot = sum(w) or 1.0
    return [x / tot for x in w]


def wmean(w):
    return sum(g * wi for g, wi in zip(GRID, w))


def wq(w, q):
    cum = 0.0
    for g, wi in zip(GRID, w):
        cum += wi
        if cum >= q:
            return g
    return GRID[-1]


def belief_signals(signals):
    return {i: post_from_obs([(s, V.SIGMA_S)], V.SIGMA_S)
            for i, s in signals.items()}


def obs_predictive(w, sigma_v):
    """predictive over verification outcome y: mixture over GRID."""
    import math
    ys = [SEV_LO + (SEV_HI - SEV_LO) * k / 20.0 for k in range(21)]
    py = []
    for y in ys:
        p = sum(wi * math.exp(-0.5 * ((y - g) / sigma_v) ** 2)
                for g, wi in zip(GRID, w))
        py.append(p)
    tot = sum(py) or 1.0
    return [(y, p / tot) for y, p in zip(ys, py)]


def evsi_node(inst, i, beliefs, sev_means, lat_v, cash_v):
    """Honest myopic EVSI of verifying node i (cost inside via caps)."""
    w = beliefs[i]
    v0, R0, pi0 = plan(inst, sev_means, lat_v, cash_v)
    if pi0 is None:
        return None, None
    exp_after = 0.0
    for y, p in obs_predictive(w, SIGMA_V):
        w2 = post_from_obs(
            [(y, SIGMA_V)] + [(None, 0)] if False else [(y, SIGMA_V)],
            SIGMA_V)
        w2 = posterior_merge(w, y)
        m2 = dict(sev_means)
        m2[i] = wmean(w2)
        v1, R1, pi1 = plan(inst, m2, lat_v + VERIFY_LAT,
                           cash_v + VERIFY_CNY)
        exp_after += p * (v1 if v1 is not None else v0 - 0.5)
    return exp_after - v0, (R0, pi0)


def posterior_merge(prior_w, y):
    """posterior after prior (from signals) + verify obs y."""
    import math
    w = [pw * math.exp(-0.5 * ((y - g) / SIGMA_V) ** 2)
         for g, pw in zip(GRID, prior_w)]
    tot = sum(w) or 1.0
    return [x / tot for x in w]


def run_la1(inst, signals, rng):
    beliefs = belief_signals(signals)
    sev_means = {i: wmean(w) for i, w in beliefs.items()}
    lat_v = cash_v = 0.0
    verified = set()
    V.EVAL_COUNT[0] = 0
    plan0 = plan(inst, sev_means, 0.0, 0.0)
    while True:
        best_i, best_e, best_pair = None, 1e-9, None
        for i in sorted(inst.faults):
            if i in verified:
                continue
            e, p0 = evsi_node(inst, i, beliefs, sev_means, lat_v, cash_v)
            if e is not None and e > best_e:
                best_i, best_e, best_pair = i, e, p0
        if best_i is None:
            break
        y = inst.sev[best_i] + rng.gauss(0, SIGMA_V)
        beliefs[best_i] = posterior_merge(beliefs[best_i], y)
        sev_means[best_i] = wmean(beliefs[best_i])
        cash_v += VERIFY_CNY
        lat_v += VERIFY_LAT
        verified.add(best_i)
    v, R, pi = plan(inst, sev_means, lat_v, cash_v)
    true_v = value(inst, R, pi, sev_means, true=True, extra_lat=lat_v,
                   extra_cash=cash_v) if R is not None else None
    ev = V.EVAL_COUNT[0]
    plan_final = (R, pi)
    changed = (plan0[1] != R or plan0[2] != pi)
    return true_v, cash_v, len(verified), ev, changed


def run_method(inst, signals, method, rng):
    V.EVAL_COUNT[0] = 0
    if method == 'LA1':
        return run_la1(inst, signals, rng)
    beliefs = belief_signals(signals)
    sev_means = {i: wmean(w) for i, w in beliefs.items()}
    cash_v = lat_v = 0.0
    nv = 0
    if method == 'THRESH':
        sev_hard = {i: (0.0 if signals[i] <= 0.35 else SEV_HI)
                    for i in signals}
        v, R, pi = plan(inst, sev_hard, 0.0, 0.0)
        tv = value(inst, R, pi, sev_means, true=True) if R is not None \
            else None
        return tv, 0.0, 0, V.EVAL_COUNT[0], False
    if method == 'ALL':
        for i in inst.faults:
            y = inst.sev[i] + rng.gauss(0, SIGMA_V)
            beliefs[i] = posterior_merge(beliefs[i], y)
            cash_v += VERIFY_CNY
            lat_v += VERIFY_LAT
            nv += 1
    elif method == 'RANDV':
        ks = max(1, len(inst.faults) // 2)
        for i in rng.sample(sorted(inst.faults), ks):
            y = inst.sev[i] + rng.gauss(0, SIGMA_V)
            beliefs[i] = posterior_merge(beliefs[i], y)
            cash_v += VERIFY_CNY
            lat_v += VERIFY_LAT
            nv += 1
    elif method == 'COSTH':
        for i in sorted(inst.faults):
            spread = wq(beliefs[i], 0.85) - wq(beliefs[i], 0.15)
            if spread * inst.keys[i] > VERIFY_CNY * 10:
                y = inst.sev[i] + rng.gauss(0, SIGMA_V)
                beliefs[i] = posterior_merge(beliefs[i], y)
                cash_v += VERIFY_CNY
                lat_v += VERIFY_LAT
                nv += 1
    elif method == 'MEVPI':
        # the earlier falsified variant, kept for continuity: point
        # reveal at posterior quantiles, flat weights
        for i in sorted(inst.faults):
            q15, q85 = wq(beliefs[i], 0.15), wq(beliefs[i], 0.85)
            sh_lo, sh_hi = dict(sev_means), dict(sev_means)
            sh_lo[i], sh_hi[i] = q85, q15
            vp, _, _ = plan(inst, sh_lo, lat_v, cash_v + VERIFY_CNY)
            vo, _, _ = plan(inst, sh_hi, lat_v, cash_v + VERIFY_CNY)
            if vp is not None and vo is not None and \
                    0.3 * abs(vo - vp) > VERIFY_CNY:
                beliefs[i] = posterior_merge(beliefs[i], inst.sev[i])
                cash_v += VERIFY_CNY
                lat_v += VERIFY_LAT
                nv += 1
    sev_means = {i: wmean(w) for i, w in beliefs.items()}
    v, R, pi = plan(inst, sev_means, lat_v, cash_v)
    tv = value(inst, R, pi, sev_means, true=True, extra_lat=lat_v,
               extra_cash=cash_v) if R is not None else None
    return tv, cash_v, nv, V.EVAL_COUNT[0], False


def run_pj_ms(inst, signals, budget_evals, rng):
    """PJ + multi-start planning, budget-matched in planner evals."""
    V.EVAL_COUNT[0] = 0
    beliefs = belief_signals(signals)
    sev_means = {i: wmean(w) for i, w in beliefs.items()}
    best = None
    starts = [set()] + [set(rng.sample(sorted(inst.faults),
                                       rng.randint(0, len(inst.faults))))
                        for _ in range(6)]
    for R0 in starts:
        if V.EVAL_COUNT[0] >= budget_evals:
            break
        dirty = sorted(inst.faults)
        nodes = sorted(set(R0) | set(range(max(1, inst.n - 3),
                                           inst.n - 1)))
        pi = {i: 'keep' for i in range(inst.n)}
        for i in R0:
            pi[i] = 'Flash'
        cur = value(inst, set(R0), pi, sev_means)
        improved = True
        while improved and V.EVAL_COUNT[0] < budget_evals:
            improved = False
            for i in nodes:
                for m in J.MODEL_NAMES + ['keep']:
                    if m == pi[i] or (m == 'keep' and i in R0):
                        continue
                    pi2 = dict(pi)
                    pi2[i] = m
                    vv = value(inst, set(R0), pi2, sev_means)
                    if vv is not None and (cur is None or
                                           vv > cur + 1e-12):
                        pi[i], cur = m, vv
                        improved = True
        if cur is not None and (best is None or cur > best[0]):
            best = (cur, (set(R0), dict(pi)))
    if best is None:
        return None, 0.0, 0, V.EVAL_COUNT[0], False
    R, pi = best[1]
    tv = value(inst, R, pi, sev_means, true=True)
    return tv, 0.0, 0, V.EVAL_COUNT[0], False


def main():
    methods = ('PJ', 'PJ_MS', 'THRESH', 'ALL', 'RANDV', 'COSTH',
               'MEVPI', 'LA1')
    regimes = [('loose', 55.0, 0.02, 25.0), ('knife', 44.0, 0.012, 30.0),
               ('tight', 38.0, 0.010, 30.0), ('vtight', 36.0, 0.008, 30.0)]
    out = []
    for sig_s in (0.17, 0.35):
        V.SIGMA_S = sig_s
        for name, D, Ccap, pref in regimes:
            rows = {m: [] for m in methods}
            evs = {m: [] for m in methods}
            chg = []
            la_nverify = []
            for seed in range(30):
                rng = random.Random(seed)
                base = J.gen_inst(rng, 8, 3, D, Ccap)
                base.prefix_lat = pref
                inst = VInst(base, rng)
                signals = {i: inst.sev[i] + rng.gauss(0, sig_s)
                           for i in inst.faults}
                la = run_method(inst, signals, 'LA1',
                                random.Random(seed + 1))
                for m in methods:
                    if m == 'LA1':
                        tv, cv, nv, ev, changed = la
                    elif m == 'PJ_MS':
                        tv, cv, nv, ev, changed = run_pj_ms(
                            inst, signals, la[3], random.Random(seed + 2))
                    else:
                        tv, cv, nv, ev, changed = run_method(
                            inst, signals, m, random.Random(seed + 3))
                    rows[m].append(tv if tv is not None else -9.0)
                    evs[m].append(ev)
                    if m == 'LA1':
                        chg.append(changed)
                        la_nverify.append(nv)
            rec = dict(sig_s=sig_s, regime=name, D=D, Ccap=Ccap,
                       prefix=pref)
            for m in methods:
                rec[m] = round(st.mean(rows[m]), 4)
                rec[m + '_ev'] = round(st.mean(evs[m]), 0)
            rec['LA1_nverify'] = round(st.mean(la_nverify), 2)
            rec['LA1_plan_change'] = round(st.mean(chg), 2)
            for other in ('PJ', 'PJ_MS', 'THRESH', 'ALL', 'COSTH',
                          'MEVPI', 'RANDV'):
                w = sum(1 for s in range(30)
                        if rows['LA1'][s] > rows[other][s] + 1e-9)
                t = sum(1 for s in range(30)
                        if abs(rows['LA1'][s] - rows[other][s]) <= 1e-9)
                rec[f'LA1_vs_{other}'] = f'{w}/{t}/{30 - w - t}'
            # conditional deltas on plan change
            ch_idx = [s for s in range(30) if chg[s]]
            nc_idx = [s for s in range(30) if not chg[s]]
            if ch_idx and nc_idx:
                rec['LA1_gain|changed'] = round(
                    st.mean(rows['LA1'][s] - rows['PJ'][s]
                            for s in ch_idx), 4)
                rec['LA1_gain|same'] = round(
                    st.mean(rows['LA1'][s] - rows['PJ'][s]
                            for s in nc_idx), 4)
            out.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    json.dump(out, open('/root/r3_own_pool/deadline_reward_v1/'
                        'JOINT6_LAH_LOOKAHEAD.json', 'w'),
              ensure_ascii=False, indent=1)
    print('done')


if __name__ == '__main__':
    main()
