#!/usr/bin/env python3
"""P2-0.6: execution-mechanism & budget final feasibility audit (zero-call).

1) Detector audit: A_run (runtime-only: exec fail | fact missing | span/citation
   missing) vs A_full (adds semantic support check, NOT runtime-free).
2) Cost audit: speculative copies priced UNCONDITIONALLY (P2-0.5 frontier mixed
   pay-when-bad cost with speculative latency -- optimistic inconsistency);
   failed executions priced; shared-prep discount on groups only.
3) Quality audit: joint per-task recomputation with fresh draws for copies,
   topological early selection, downstream recompute on selected inputs.
   Selection rules: conservative / count (runtime-only), oracle (bound), sham.
4) Statistical audit: n required for 95% CI lower bound > 70%.
H0 variant included for attribution context. Zero real API; no new mechanism
probabilities; fresh draws are re-rolls of the frozen mechanism only.
"""
import os, json, math, numpy as np
from rq1_v1_8_2_r5_core import (FACT_PARENTS, DEC, RATES, PRICE, LAT, BASE_LAT,
    FP_RATE, prep_all, run_fast, mask_to_assign)
from rq1_v1_8_2_r5_main import SCENARIOS, task_pool

OUT = os.path.dirname(os.path.abspath(__file__))
N = 800
NODES = ['e0', 'e1', 't', 'm', 'r', 'v', 'p']
TOPO = [0, 1, 2, 3, 4, 5, 6]
DS = mask_to_assign(127)

def load(cfg, seed_tag):
    ts = task_pool(N, cfg['seed'] * 1000 + 501, cfg['sign_mode'])
    P = prep_all(ts, cfg['delta'], cfg['up'], cfg['extra_parse'], cfg['pure_null'])
    ids = [t['id'] for t in ts]
    return P, ids

ST = load(SCENARIOS[2], 'stable')          # stable .20
H0 = load(SCENARIOS[0], 'h0')              # H0 pure null

Rl = {0: RATES['loc'][0], 1: RATES['loc'][1]}
Rs = {0: RATES['sup'][0], 1: RATES['sup'][1]}
Rp = {0: RATES['parse'][0], 1: RATES['parse'][1]}
Rc = {0: RATES['contract'][0], 1: RATES['contract'][1]}
Runk = {0: RATES['unk'][0], 1: RATES['unk'][1]}

def copy_rng(tid, ni):
    return np.random.default_rng(abs(hash((tid, ni, 'copy', 20261103))) % (2**32))

def exec_node(P, i, ni, model, q, fresh=None):
    """Execute node ni with model and parent-quality q. fresh=None -> original U."""
    if fresh is None:
        up = P[i]['parse'][ni] <= P[i]['Rparse'][model] - P[i]['extra']
        uc = P[i]['contract'][ni] <= P[i]['Rcontract'][model]
        uf = P[i]['fact'][ni]
    else:
        up = fresh.random() <= Rp[model]
        uc = fresh.random() <= Rc[model]
        uf = fresh.random((2, 5))
    if not (up and uc):
        return [2, 2], [False, False], [False, False], False
    b = P[i]['base'][model][ni]
    out = [2, 2]; loc = [False, False]; sup = [False, False]
    for fi in (0, 1):
        if ni == 6 and fi == 1:
            out[1] = 3 if uf[1][2] <= Runk[model] else 1
            continue
        qq = max(0.0, min(1.0, q))
        pp = b * (0.35 + 0.65 * qq)
        if ni == 5:
            pp = pp + 0.30 * (1 - qq) * (1 - b)
        pp = max(0.02, min(0.98, pp))
        u0, u1, _, u3, u4 = uf[fi]
        out[fi] = 0 if u0 <= pp else (1 if u1 < FP_RATE else 2)
        if out[fi] in (0, 1):
            loc[fi] = u3 <= Rl[model]
            sup[fi] = u4 <= Rs[model]
    return out, loc, sup, True

def flag_run(ni, out, loc, eok):
    """Runtime-only observable badness: exec fail | fact missing | span missing."""
    if not eok:
        return True
    for fi in (0, 1):
        if (ni, fi) not in DEC:
            continue
        if out[fi] == 2:
            return True
        if out[fi] in (0, 1) and not loc[fi]:
            return True
    return False

def flag_full(ni, out, loc, sup, eok):
    if flag_run(ni, out, loc, eok):
        return True
    return any(out[fi] in (0, 1) and not sup[fi] for fi in (0, 1) if (ni, fi) in DEC)

def clean_count(ni, out, loc, eok):
    c = 0
    for fi in (0, 1):
        if (ni, fi) not in DEC:
            continue
        if out[fi] != 2 and (loc[fi] or out[fi] not in (0, 1)):
            c += 1
    return c

def node_bad_actual(ni, out, loc, sup):
    return any(not (out[fi] == 0 and loc[fi] and sup[fi]) for fi in (0, 1) if (ni, fi) in DEC)

def q_of(state, ni):
    vals = [state['out'][pn][pf] == 0 for fi in (0, 1) for (pn, pf) in FACT_PARENTS[ni][fi]]
    return 1.0 if not vals else float(np.mean(vals))

COPY_MODEL = {0: 1, 1: 1, 2: 1, 3: 0, 4: 1, 5: 0, 6: 0}   # default: r DS re-roll (operator ruling)
COPY_VDS = dict(COPY_MODEL); COPY_VDS[5] = 1              # v downgraded to DS re-roll (matched-20)
COPY_STRICT = dict(COPY_MODEL); COPY_STRICT[5] = 1; COPY_STRICT[6] = 1  # only m GLM-spec (strict-10)
GROUPS = [(0, 1, 2), (3, 5, 6), (4,)]
COST = {0: PRICE[0] / 7.0, 1: PRICE[1] / 7.0}

def joint_run(P, ids, rebuild_set, rule, d=0.0, copy_model=None):
    cm = copy_model or COPY_MODEL
    """Speculative pipeline with topological early selection. Exact per-task states."""
    Qs = []; cost_adds = []; mks = []
    for i in range(len(P)):
        state = {'out': [[2, 2] for _ in range(7)], 'loc': [[False, False] for _ in range(7)],
                 'sup': [[False, False] for _ in range(7)], 'eok': [False] * 7}
        lat = {}
        cost = 0.6
        for g in GROUPS:
            members = [ni for ni in g if ni in rebuild_set]
            if len(members) > 1:
                cost += sum(COST[cm[ni]] for ni in members) * (1 - d)
            else:
                cost += sum(COST[cm[ni]] for ni in members)
        for ni in TOPO:
            q = q_of(state, ni)
            out, loc, sup, eok = exec_node(P, i, ni, 1, q)
            l_node = BASE_LAT[ni] * LAT[1]
            if ni in rebuild_set:
                rng = copy_rng(ids[i], ni)
                out2, loc2, sup2, eok2 = exec_node(P, i, ni, cm[ni], q, fresh=rng)
                l_copy = BASE_LAT[ni] * LAT[cm[ni]]
                l_node = max(l_node, l_copy)
                f1 = flag_run(ni, out, loc, eok)
                f2 = flag_run(ni, out2, loc2, eok2)
                if rule == 'conservative':
                    take2 = f1 and not f2
                elif rule == 'count':
                    take2 = clean_count(ni, out2, loc2, eok2) > clean_count(ni, out, loc, eok)
                elif rule == 'oracle':
                    take2 = (node_bad_actual(ni, out, loc, sup) and
                             not node_bad_actual(ni, out2, loc2, sup2))
                elif rule == 'sham':
                    take2 = f1 and (rng.random() < 0.5)
                if take2:
                    out, loc, sup, eok = out2, loc2, sup2, eok2
            state['out'][ni] = out; state['loc'][ni] = loc
            state['sup'][ni] = sup; state['eok'][ni] = eok
            lat[ni] = l_node
        F = {0: lat[0], 1: lat[1], 2: lat[0] + lat[2]}
        F[3] = max(lat[0], lat[1]) + lat[3]
        F[4] = F[3] + lat[4]
        F[5] = max(F[3], F[2]) + lat[5]
        mk = max(F[4], F[5]) + lat[6]
        gate = state['eok'][6]
        q_t = np.mean([state['out'][n][f] == 0 and state['loc'][n][f] and state['sup'][n][f] and gate
                       for (n, f) in DEC])
        Qs.append(q_t); cost_adds.append(cost - 0.6); mks.append(mk / 2.85)
    return np.array(Qs), np.array(cost_adds), np.array(mks)

def boot(q, ns=3000, nt=24, seed=7):
    rng = np.random.default_rng(seed)
    vals = np.array([rng.choice(q, nt, replace=False).mean() for _ in range(ns)])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))

def summarize_variant(P, ids, rebuild_set, rule, d, copy_model=None):
    q, c, m = joint_run(P, ids, rebuild_set, rule, d, copy_model)
    lo, hi = boot(q)
    return {'Q': float(q.mean()), 'ci24': [lo, hi], 'sd': float(q.std(ddof=1)),
            'cost_add': float(c.mean()), 'mult': 1 + float(c.mean()) / 0.6,
            'mk_ratio': float(m.mean()), 'mk_max': float(m.max()),
            'q_arr': q}

# ---------- 1) detector audit ----------
P, ids = ST
outB = []; locB = []; supB = []; eokB = []
for i in range(N):
    o, l, s, e = run_fast(P[i], DS)
    outB.append(o); locB.append(l); supB.append(s); eokB.append(e)
stats = {'A_run': {'tp': 0, 'fn': 0, 'fp': 0, 'tn': 0}, 'A_full': {'tp': 0, 'fn': 0, 'fp': 0, 'tn': 0}}
hidden = {'evidenced_FP_fact': 0, 'unsupported_TP_fact': 0}
for i in range(N):
    for ni in range(7):
        bad = node_bad_actual(ni, outB[i][ni], locB[i][ni], supB[i][ni])
        for nm, fl in (('A_run', flag_run(ni, outB[i][ni], locB[i][ni], eokB[i][ni])),
                       ('A_full', flag_full(ni, outB[i][ni], locB[i][ni], supB[i][ni], eokB[i][ni]))):
            s_ = stats[nm]
            if bad and fl: s_['tp'] += 1
            elif bad: s_['fn'] += 1
            elif fl: s_['fp'] += 1
            else: s_['tn'] += 1
        for fi in (0, 1):
            if (ni, fi) not in DEC:
                continue
            if outB[i][ni][fi] == 1 and locB[i][ni][fi] and supB[i][ni][fi]:
                hidden['evidenced_FP_fact'] += 1
            if outB[i][ni][fi] == 0 and locB[i][ni][fi] and not supB[i][ni][fi]:
                hidden['unsupported_TP_fact'] += 1
det = {nm: {'sens': v['tp'] / float(v['tp'] + v['fn']), 'spec': v['tn'] / float(v['tn'] + v['fp']),
            'fn': v['fn'], 'fp': v['fp']} for nm, v in stats.items()}

# ---------- 2)+3) joint recalculation ----------
FULL = (0, 1, 2, 3, 4, 5, 6)
NO_R = (0, 1, 2, 3, 5, 6)
CORE = (3, 5, 6)
variants = {}
for d in (0.0, 0.3, 0.5):
    for rule in ('conservative', 'count'):
        v = summarize_variant(P, ids, FULL, rule, d)
        variants[f'FULL|{rule}|d={d}'] = {k: v[k] for k in v if k != 'q_arr'}
        variants[f'FULL|{rule}|d={d}']['q_arr'] = None
v_or = summarize_variant(P, ids, FULL, 'oracle', 0.3)
variants['FULL|oracle|d=0.3'] = {k: v_or[k] for k in v_or if k != 'q_arr'}
v_sh = summarize_variant(P, ids, FULL, 'sham', 0.3)
variants['FULL|sham|d=0.3'] = {k: v_sh[k] for k in v_sh if k != 'q_arr'}
v_nr = summarize_variant(P, ids, NO_R, 'count', 0.3)
variants['NO_R|count|d=0.3'] = {k: v_nr[k] for k in v_nr if k != 'q_arr'}
v_core = summarize_variant(P, ids, CORE, 'count', 0.3)
variants['CORE_mvp|count|d=0.3'] = {k: v_core[k] for k in v_core if k != 'q_arr'}
v_vds = summarize_variant(P, ids, FULL, 'count', 0.3, COPY_VDS)
variants['FULL_vDS|count|d=0.3'] = {k: v_vds[k] for k in v_vds if k != 'q_arr'}
v_st = summarize_variant(P, ids, FULL, 'count', 0.3, COPY_STRICT)
variants['STRICT_mGLM|count|d=0.3'] = {k: v_st[k] for k in v_st if k != 'q_arr'}
v_sh_vds = summarize_variant(P, ids, FULL, 'sham', 0.3, COPY_VDS)
variants['FULL_vDS|sham|d=0.3'] = {k: v_sh_vds[k] for k in v_sh_vds if k != 'q_arr'}
# base and H0
base_q = float(np.mean([np.mean([outB[i][n][f] == 0 and locB[i][n][f] and supB[i][n][f] and eokB[i][6]
                                  for (n, f) in DEC]) for i in range(N)]))
P0, ids0 = H0
q0, c0, m0 = joint_run(P0, ids0, FULL, 'count', 0.3, COPY_VDS)
outH = []
qh_base = []
for i in range(N):
    o, l, s, e = run_fast(P0[i], DS)
    outH.append((o, l, s, e))
    qh_base.append(np.mean([o[n][f] == 0 and l[n][f] and s[n][f] and e[6] for (n, f) in DEC]))
h0 = {'base_Q': float(np.mean(qh_base)), 'joint_Q_count_d0.3': float(q0.mean()),
      'cost_add': float(c0.mean()), 'mk_ratio': float(m0.mean())}

# ---------- 4) sample size ----------
ss = {}
for name in ('FULL|count|d=0.3', 'FULL|oracle|d=0.3', 'FULL_vDS|count|d=0.3'):
    v = variants[name]
    gap = v['Q'] - 0.70
    if gap > 0:
        n_req = (1.96 * v['sd'] / gap) ** 2
        ss[name] = {'Q': v['Q'], 'sd': v['sd'], 'gap': gap, 'n_for_CI_lower_70': n_req}
    else:
        ss[name] = {'Q': v['Q'], 'sd': v['sd'], 'gap': gap,
                    'n_for_CI_lower_70': None, 'note': 'mean below 70; CI cannot exceed 70'}

res = {'detector_audit': det, 'hidden_classes': hidden,
       'variants': variants, 'base_Q': base_q, 'H0': h0, 'sample_size': ss,
       'notes': ['A_run = runtime-only (exec fail | fact missing | span missing); A_full adds semantic support check (not runtime-free)',
                 'speculative copies priced unconditionally; failed executions included; group discount on {e0,e1,t},{m,v,p}',
                 'joint recalc: fresh draws for copies, topo early selection, downstream recompute on selected inputs',
                 'r copy = DS re-roll per operator ruling']}
json.dump(res, open(os.path.join(OUT, 'P2_06_AUDIT_ANALYSIS.json'), 'w'), indent=1, default=float)

print('base Q =', round(base_q, 4))
print('detector audit:', json.dumps(det, indent=1))
print('hidden classes:', hidden)
print('\njoint variants:')
for k, v in variants.items():
    print(f"  {k:26s} Q={v['Q']*100:.2f}% CI24[{v['ci24'][0]*100:.1f},{v['ci24'][1]*100:.1f}] "
          f"sd={v['sd']:.3f} cost x{v['mult']:.2f} mk={v['mk_ratio']:.3f}(max {v['mk_max']:.3f})")
print('\nH0:', h0)
print('\nsample size:', json.dumps(ss, indent=1))
