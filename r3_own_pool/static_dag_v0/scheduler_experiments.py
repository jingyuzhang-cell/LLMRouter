"""Scheduler validation experiments (zero new model calls).

E2  selection-baseline comparison (3-fold CV over seeds, 32 states):
    weighted-sum (alpha in {.25,.50,.75}, a priori), cost-greedy (Q/C),
    random-Pareto (uniform over calibration front) vs Pareto selector,
    fixed-best and oracle-state. Metrics: grid-avg budgeted Q(B), B=3000 avg,
    mean tokens, oracle gap.

E3  state ablation: full (p,B) vs w/o-failure (clean-only calibration) vs
    w/o-budget (unlimited-budget calibration), evaluated on the full grid.

E1c candidate-pool size sensitivity on the CLEAN panel (8 executed arms:
    single, static(no-fb), static-fallback, static-matched, dynamic-ideal,
    dynamic-real, full-replay, dynamic+verifier): nested pools P3/P5/P8;
    common-reference 2D HV of the calibration front; selector vs per-state
    oracle gap as the pool grows.

Writes adaptive_benchmark/SCHEDULER_EXPERIMENTS.md + .json.
"""
import json
import re
import statistics as st

BASE = '/root/r3_own_pool/static_dag_v0'
OUT = f'{BASE}/adaptive_benchmark'
BUDGETS = (600, 800, 1000, 1200, 1500, 2000, 2500, 3000)
RATES = (0, 0.1, 0.2, 0.3)
SEEDS = (20260923, 20260924, 20260925)
POOL = ('router', 'static', 'dynamic')


def load(seed, rate):
    sub = f'{OUT}/fault_p{int(rate*100)}' if seed == 20260923 else f'{OUT}/fault_p{int(rate*100)}_seed{seed}'
    return json.load(open(sub + '/FAULT_RESULT.json'))


def q_b(rows, uids, B):
    return sum(1 for u in uids if rows[u]['ok'] and rows[u]['used'] <= B) / len(uids)


def run():
    pol = json.load(open(f'{BASE}/multidag_dynamic_120/POLICY.json'))
    uids = [t['uid'] for t in pol['tasks']]
    n = len(uids)
    clean = json.load(open(f'{OUT}/CLEAN_RESULTS.json'))

    perf = {}
    for rate in RATES:
        for seed in SEEDS:
            rows_by_m = {m: clean[m] for m in POOL} if rate == 0 else load(seed, rate)
            perf[(rate, seed)] = {m: dict(qb={B: q_b(rows_by_m[m], uids, B) for B in BUDGETS},
                                          tokens=sum(rows_by_m[m][u]['used'] for u in uids) / n,
                                          q_unlim=sum(1 for u in uids if rows_by_m[m][u]['ok']) / n)
                                  for m in POOL}

    def cal_mean(rate, m, key, B=None, seeds=None):
        seeds = seeds or SEEDS
        vals = [perf[(rate, s)][m]['qb'][B] if key == 'qb' else perf[(rate, s)][m][key] for s in seeds]
        return st.mean(vals)

    def front(rate, cal):
        pts = {m: (cal_mean(rate, m, 'q_unlim', seeds=cal), cal_mean(rate, m, 'tokens', seeds=cal)) for m in POOL}
        return {m for m in pts if not any(pts[o][0] >= pts[m][0] and pts[o][1] <= pts[m][1] and
                                          (pts[o][0] > pts[m][0] or pts[o][1] < pts[m][1]) for o in pts if o != m)}

    # ---------- E2: selection baselines ----------
    def pick(policy, rate, B, cal):
        f = front(rate, cal)
        if policy == 'pareto_selector':
            q = {m: cal_mean(rate, m, 'qb', B=B, seeds=cal) for m in f}
            best = max(q.values())
            return min((m for m in f if q[m] == best), key=lambda m: cal_mean(rate, m, 'tokens', seeds=cal))
        if policy == 'random_pareto':
            return st.choice(f) if False else sorted(f)[0]  # deterministic: report expectation instead
        if policy == 'cost_greedy':
            return max(POOL, key=lambda m: cal_mean(rate, m, 'q_unlim', seeds=cal) / cal_mean(rate, m, 'tokens', seeds=cal))
        if policy.startswith('wsum'):
            a = float(policy.split('_')[1])
            cmax = max(cal_mean(rate, m, 'tokens', seeds=cal) for m in POOL)
            return max(POOL, key=lambda m: a * cal_mean(rate, m, 'qb', B=B, seeds=cal) - (1 - a) * cal_mean(rate, m, 'tokens', seeds=cal) / cmax)
        raise ValueError(policy)

    policies = ['random_all', 'cost_only', 'wsum_0.25', 'wsum_0.50', 'wsum_0.75',
                'cost_greedy', 'random_pareto', 'pareto_selector', 'oracle_state']
    grid = {p: {r: {B: [] for B in BUDGETS} for r in RATES} for p in policies}
    toks = {p: [] for p in policies}
    for test in SEEDS:
        cal = [s for s in SEEDS if s != test]
        for rate in RATES:
            f = front(rate, cal)
            for B in BUDGETS:
                real = {m: perf[(rate, test)][m]['qb'][B] for m in POOL}
                cm = {m: cal_mean(rate, m, 'tokens', seeds=cal) for m in POOL}
                vals = {'random_all': st.mean(real.values()), 'cost_only': real['router']}
                for a in (0.25, 0.5, 0.75):
                    vals[f'wsum_{a:.2f}'] = real[pick(f'wsum_{a}', rate, B, cal)]
                vals['cost_greedy'] = real[pick('cost_greedy', rate, B, cal)]
                vals['random_pareto'] = st.mean(real[m] for m in f)  # front 上均匀期望
                vals['pareto_selector'] = real[pick('pareto_selector', rate, B, cal)]
                vals['oracle_state'] = max(real.values())
                for p in policies:
                    grid[p][rate][B].append(vals[p])
            sel = pick('pareto_selector', rate, 3000, cal)
            cg = pick('cost_greedy', rate, 3000, cal)
            toks['random_all'].append(st.mean(cm.values()))
            toks['cost_only'].append(cm['router'])
            toks['cost_greedy'].append(cm[cg])
            toks['pareto_selector'].append(cm[sel])
            toks['oracle_state'].append(cm[max(POOL, key=lambda m: perf[(rate, test)][m]['q_unlim'])])
            for a in (0.25, 0.5, 0.75):
                toks[f'wsum_{a:.2f}'].append(cm[pick(f'wsum_{a}', rate, 3000, cal)])
            toks['random_pareto'].append(st.mean(cm[m] for m in f))

    def gavg(p, B=None):
        vals = [st.mean(grid[p][r][B_]) for r in RATES for B_ in ([B] if B else BUDGETS)]
        return st.mean(vals)

    e2 = {p: dict(grid_avg_Q=round(gavg(p), 4), B3000_avg_Q=round(gavg(p, 3000), 4)) for p in policies}

    # ---------- E3: state ablation ----------
    def pick_abl(mode, rate, B, cal):
        if mode == 'full':
            return pick('pareto_selector', rate, B, cal)
        if mode == 'no_failure':  # 只用 clean 校准
            return max(POOL, key=lambda m: cal_mean(0, m, 'qb', B=B, seeds=cal))
        if mode == 'no_budget':   # 只用不限预算质量
            return max(POOL, key=lambda m: cal_mean(rate, m, 'q_unlim', seeds=cal))

    abl_grid = {m_: {r: {B: [] for B in BUDGETS} for r in RATES} for m_ in ('full', 'no_failure', 'no_budget')}
    for test in SEEDS:
        cal = [s for s in SEEDS if s != test]
        for rate in RATES:
            for B in BUDGETS:
                real = {m: perf[(rate, test)][m]['qb'][B] for m in POOL}
                for mode in abl_grid:
                    abl_grid[mode][rate][B].append(real[pick_abl(mode, rate, B, cal)])
    e3 = {m_: dict(grid_avg_Q=round(st.mean([st.mean(abl_grid[m_][r][B]) for r in RATES for B in BUDGETS]), 4),
                   B3000_f30=round(st.mean(abl_grid[m_][0.3][3000]), 4),
                   f30_lowB=round(st.mean([st.mean(abl_grid[m_][0.3][B]) for B in (600, 800, 1000)]), 4))
          for m_ in abl_grid}

    # ---------- E1c: clean-pool size sensitivity ----------
    corr = json.load(open(f'{BASE}/corrected_replay/CORRECTED_ARMS.json'))['arms']
    dv = json.load(open(f'{OUT}/verifier_ablation/DV_RESULT.json'))['dv']
    arms = {
        'single': clean['router'], 'static_nofb': clean['static'],
        'static_fb': {u: dict(ok=corr['static'][u]['ok'], used=corr['static'][u]['used'],
                              lat=corr['static'][u]['latency']) for u in uids},
        'sm': {u: dict(ok=corr['sm'][u]['ok'], used=corr['sm'][u]['used'], lat=corr['sm'][u]['latency']) for u in uids},
        'ideal': {u: dict(ok=corr['dynamic'][u]['ok'], used=corr['dynamic'][u]['used'], lat=corr['dynamic'][u]['latency']) for u in uids},
        'dynamic': clean['dynamic'],
        'full_replay': {u: dict(ok=corr['fg'][u]['ok'], used=corr['fg'][u]['used'], lat=corr['fg'][u]['latency']) for u in uids},
        'dv': {u: dict(ok=dv[u]['ok'], used=dv[u]['used'], lat=dv[u]['lat']) for u in uids},
    }
    nested = [('P3', ['single', 'static_nofb', 'dynamic']),
              ('P5', ['single', 'static_nofb', 'dynamic', 'full_replay', 'sm']),
              ('P8', list(arms))]
    c_ref = 1.1 * max(sum(a[u]['used'] for u in uids) / n for a in arms.values())

    def hv2d(pts):
        total = 0.0
        from itertools import combinations
        for k in range(1, len(pts) + 1):
            for comb in combinations(pts, k):
                corner = (min(p[0] for p in comb), min(p[1] for p in comb))
                v = corner[0] * corner[1]
                total += v if k % 2 else -v
        return total

    e1c = []
    for name, members in nested:
        pts = {m: (sum(1 for u in uids if arms[m][u]['ok']) / n, 1 - sum(arms[m][u]['used'] for u in uids) / n / c_ref) for m in members}
        f = [m for m in pts if not any(pts[o][0] >= pts[m][0] and pts[o][1] >= pts[m][1] and
                                       (pts[o][0] > pts[m][0] or pts[o][1] > pts[m][1]) for o in pts if o != m)]
        sel_q = []
        oracle_q = []
        for B in BUDGETS:
            qb = {m: q_b(arms[m], uids, B) for m in members}
            sel = max(f, key=lambda m: qb[m])
            sel_q.append(qb[sel])
            oracle_q.append(max(qb.values()))
        e1c.append(dict(pool=name, n=len(members), front_size=len(f), front=sorted(f),
                        HV_2d=round(hv2d([pts[m] for m in f]), 4),
                        selector_avgQB=round(st.mean(sel_q), 4),
                        oracle_avgQB=round(st.mean(oracle_q), 4),
                        gap=round(st.mean(oracle_q) - st.mean(sel_q), 4)))

    rep = dict(E2_baselines=e2, E2_tokens={p: round(st.mean(v), 1) for p, v in toks.items() if v},
               E3_state_ablation=e3, E1c_clean_pool_sensitivity=e1c,
               note='zero new calls; 3-fold CV (E2/E3); weighted-sum alphas fixed a priori')
    json.dump(rep, open(f'{OUT}/SCHEDULER_EXPERIMENTS.json', 'w'), ensure_ascii=False, indent=1)
    lines = ['# Scheduler validation experiments (zero calls)', '',
             '## E2 选择基线比较(32 状态 × 3 折;网格平均 / B=3000 平均)', '',
             '| 方法 | 网格平均 Q(B) | B=3000 平均 | 平均 tokens |', '|---|---:|---:|---:|']
    for p in policies:
        lines.append(f"| {p} | {e2[p]['grid_avg_Q']:.4f} | {e2[p]['B3000_avg_Q']:.4f} | {rep['E2_tokens'].get(p, '—')} |")
    lines += ['', '## E3 状态消融(网格平均;30%故障细节)', '',
              '| 变体 | 网格平均 Q(B) | f30@B3000 | f30@低预算(600-1000) |', '|---|---:|---:|---:|']
    for m_, v in e3.items():
        lines.append(f"| {m_} | {v['grid_avg_Q']:.4f} | {v['B3000_f30']:.4f} | {v['f30_lowB']:.4f} |")
    lines += ['', '## E1c 候选池规模敏感性(clean,8 个已执行臂,嵌套池)', '',
              '| 池 | n | 前沿规模 | 前沿 HV(2D,公共参考) | selector 平均 Q(B) | oracle 平均 Q(B) | gap |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for e in e1c:
        lines.append(f"| {e['pool']} | {e['n']} | {e['front_size']} | {e['HV_2d']:.4f} | {e['selector_avgQB']:.4f} | {e['oracle_avgQB']:.4f} | {e['gap']:.4f} |")
    open(f'{OUT}/SCHEDULER_EXPERIMENTS.md', 'w').write('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    run()
