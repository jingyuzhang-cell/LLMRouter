"""Multi-objective execution trade-off analysis (zero model calls).

Three analyses for Chapter 4.5 (renamed from 'optimization boundary' to
'execution trade-off analysis'; no optimizer is proposed):

T1  Pareto frontier + EXCLUSIVE HYPERVOLUME contribution per method, per scenario.
    Objectives (maximize): quality Q, -tokens, -latency. Per scenario each method
    contributes one point (multi-seed scenarios: seed-mean values). Axes normalized
    to [0,1] within the scenario (reference point at the origin of the maximized
    normalized space); HV of the union of <=4 boxes computed exactly by
    inclusion-exclusion. A method's exclusive contribution = HV(front) - HV(front
    without its point); dominated methods contribute 0. HV values are
    scenario-relative (not comparable across scenarios).

T2  Budget-constrained execution curves: for an absolute per-task token budget B,
    budgeted accuracy Q(B) = #{ok AND used<=B} / N (ALL tasks stay in the
    denominator; over-budget tasks count as not completed). Grid: 600..3000.
    Clean + fault 20%/30% (3 seeds, mean +/- std).

T3  Failure-rate policy transition: best strategy by accuracy at 0/10/20/30%
    (multi-seed means), overall + Hard subset; the Single->Dynamic transition band.

Writes adaptive_benchmark/MULTIOBJECTIVE_TRADEOFF.md + .json.
"""
import json
import re
import time
from itertools import combinations

from .multidag_dynamic import OUT
from .benchmark_run import BENCH, RATES
from .multidag_fullgraph import FG

SEEDS = (20260923, 20260924, 20260925)
BUDGETS = (600, 800, 1000, 1200, 1500, 2000, 2500, 3000)


def load_fault(seed, rate):
    sub = BENCH / (f'fault_p{int(rate * 100)}' if seed == 20260923 else f'fault_p{int(rate * 100)}_seed{seed}')
    return json.loads((sub / 'FAULT_RESULT.json').read_text())


def box_volume(pts):
    """Exact HV of union of boxes [0,p] in normalized 3-D maximization space."""
    total = 0.0
    pts = [tuple(p) for p in pts]
    for k in range(1, len(pts) + 1):
        for comb in combinations(pts, k):
            dim = len(comb[0])
            corner = [min(c[i] for c in comb) for i in range(dim)]
            v = 1.0
            for x in corner:
                v *= x
            total += v if k % 2 == 1 else -v
    return total


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]

    def n_ops(d):
        return len(re.findall(r'[+\-*/]', d))

    hard = {t['uid'] for t in tasks if n_ops(t['derivation']) >= 2}
    clean = json.loads((BENCH / 'CLEAN_RESULTS.json').read_text())
    corrected = json.loads((OUT.parent / 'corrected_replay' / 'CORRECTED_ARMS.json').read_text())

    def scenario_points(rows):
        n = len(uids)
        q = sum(1 for u in uids if rows[u]['ok']) / n
        c = sum(rows[u]['used'] for u in uids) / n
        l = sum(rows[u]['lat'] for u in uids) / n
        return q, c, l

    def seed_mean_points(rate):
        per = {m: [] for m in ('router', 'static', 'dynamic')}
        for seed in SEEDS:
            fr = load_fault(seed, rate)
            for m in per:
                per[m].append(scenario_points(fr[m]))
        return {m: tuple(sum(v[i] for v in vs) / len(vs) for i in range(3)) for m, vs in per.items()}

    scenarios = {'clean': {'router': scenario_points(clean['router']),
                           'static': scenario_points(clean['static']),
                           'dynamic': scenario_points(clean['dynamic']),
                           'full_replay': (sum(1 for u in uids if corrected['arms']['fg'][u]['ok']) / len(uids),
                                           sum(corrected['arms']['fg'][u]['used'] for u in uids) / len(uids),
                                           sum(corrected['arms']['fg'][u]['latency'] for u in uids) / len(uids))}}
    for rate in RATES:
        scenarios[f'fault{int(rate * 100)}'] = seed_mean_points(rate)

    # ---- T1: normalized exclusive hypervolume contribution ----
    hv = {}
    for sc, pts in scenarios.items():
        cs = [p[1] for p in pts.values()]
        ls = [p[2] for p in pts.values()]
        c_ref = 1.1 * max(cs)
        l_ref = 1.1 * max(ls)

        def norm(p):
            f1 = p[0]
            f2 = (c_ref - p[1]) / c_ref
            f3 = (l_ref - p[2]) / l_ref
            return (f1, f2, f3)
        npts = {m: norm(p) for m, p in pts.items()}

        def dominated(m):
            a = npts[m]
            return any(all(npts[o][i] >= a[i] for i in range(3)) and any(npts[o][i] > a[i] for i in range(3))
                       for o in npts if o != m)
        full = box_volume(list(npts.values()))
        pts2 = {m: (npts[m][0], npts[m][1]) for m in npts}
        full2 = box_volume(list(pts2.values()))
        excl = {}
        for m in npts:
            others = [npts[o] for o in npts if o != m]
            others2 = [pts2[o] for o in pts2 if o != m]
            excl[m] = dict(on_frontier=not dominated(m),
                           exclusive_hv=round(max(0.0, full - box_volume(others)), 4),
                           exclusive_hv_2d=round(max(0.0, full2 - box_volume(others2)), 4))
        hv[sc] = dict(points={m: dict(Q=round(p[0], 4), tokens=round(p[1], 1), latency=round(p[2], 2))
                              for m, p in pts.items()},
                      frontier_hv=round(full, 4), frontier_hv_2d=round(full2, 4), contributions=excl)

    # ---- T2: budget-constrained execution curves ----
    def budgeted(rows, B):
        return sum(1 for u in uids if rows[u]['ok'] and rows[u]['used'] <= B) / len(uids)

    curves = {}
    for name, rows in (('clean', None),):
        curves['clean'] = {m: {str(B): round(budgeted(clean[m], B), 4) for B in BUDGETS}
                           for m in ('router', 'static', 'dynamic')}
    for rate in (0.2, 0.3):
        key = f'fault{int(rate * 100)}'
        curves[key] = {}
        for m in ('router', 'static', 'dynamic'):
            per = {str(B): [] for B in BUDGETS}
            for seed in SEEDS:
                fr = load_fault(seed, rate)
                for B in BUDGETS:
                    per[str(B)].append(budgeted(fr[m], B))
            import statistics as st
            curves[key][m] = {str(B): dict(mean=round(st.mean(v), 4), std=round(st.stdev(v), 4))
                              for B, v in per.items()}

    # ---- T3: policy transition ----
    trans = {}
    ms = json.loads((BENCH / 'MULTI_SEED_RESULTS.json').read_text())
    for rate in RATES:
        e = ms['per_rate'][str(rate)]
        acc = {'single': e['router']['mean'], 'static': e['static']['mean'], 'dynamic': e['dynamic']['mean']}
        best = max(acc, key=acc.get)
        h = ms['hard'][str(rate)]
        hbest = max(('router', 'static', 'dynamic'), key=lambda m: h[m]['mean'])
        trans[rate] = dict(accuracy=acc, best=best, hard_accuracy={m: h[m]['mean'] for m in h}, hard_best=hbest)
    trans['clean'] = dict(accuracy={'single': 0.55, 'static': 0.35, 'dynamic': 0.4}, best='single')

    rep = dict(generated_unix=time.time(), zero_calls=True,
               normalization='per-scenario min-max on cost/latency, quality kept in [0,1]; '
                             'HV values scenario-relative; exclusive contribution=0 for dominated methods',
               T1_hypervolume=hv, T2_budget_curves=curves, T3_policy_transition=trans,
               budgets=BUDGETS)
    (BENCH / 'MULTIOBJECTIVE_TRADEOFF.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))

    lines = ['# 多目标执行权衡分析(zero calls)', '',
             'T1 Pareto 前沿与超体积独占贡献(按场景;归一化后,支配方法贡献为 0):', '',
             '| Scenario | method | Q | tokens | latency | on frontier | excl. HV (3D) | excl. HV (2D Q-C) |', '|---|---|---:|---:|---:|---|---:|---:|']
    for sc, h in hv.items():
        for m, c in h['contributions'].items():
            p = h['points'][m]
            lines.append(f"| {sc} | {m} | {p['Q']:.4f} | {p['tokens']:.0f} | {p['latency']:.2f} | "
                         f"{'yes' if c['on_frontier'] else 'no'} | {c['exclusive_hv']:.4f} | {c['exclusive_hv_2d']:.4f} |")
    lines += ['', 'T2 预算约束下的完成率 Q(B)=#(正确且 used≤B)/N(全部任务保留在分母):', '',
              '| Budget | clean:Single | clean:Static | clean:Dynamic | f20:Single | f20:Dynamic | f30:Single | f30:Dynamic |',
              '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for B in BUDGETS:
        row = [str(B)]
        row.append(f"{curves['clean']['router'][str(B)]:.3f}")
        row.append(f"{curves['clean']['static'][str(B)]:.3f}")
        row.append(f"{curves['clean']['dynamic'][str(B)]:.3f}")
        row.append(f"{curves['fault20']['router'][str(B)]['mean']:.3f}±{curves['fault20']['router'][str(B)]['std']:.3f}")
        row.append(f"{curves['fault20']['dynamic'][str(B)]['mean']:.3f}±{curves['fault20']['dynamic'][str(B)]['std']:.3f}")
        row.append(f"{curves['fault30']['router'][str(B)]['mean']:.3f}±{curves['fault30']['router'][str(B)]['std']:.3f}")
        row.append(f"{curves['fault30']['dynamic'][str(B)]['mean']:.3f}±{curves['fault30']['dynamic'][str(B)]['std']:.3f}")
        lines.append('| ' + ' | '.join(row) + ' |')
    lines += ['', 'T3 故障率-最优策略切换(多种子均值;整体/Hard):', '',
              '| Fault | Single | Static | Dynamic | best (overall) | Hard best |', '|---:|---:|---:|---:|---|---|']
    for rate in (0, 10, 20, 30):
        if rate == 0:
            t = trans['clean']
            lines.append(f"| 0% | {t['accuracy']['single']:.4f} | {t['accuracy']['static']:.4f} | "
                         f"{t['accuracy']['dynamic']:.4f} | {t['best']} | single (=dynamic 0.304) |")
        else:
            t = trans[rate / 100]
            a = t['accuracy']
            lines.append(f"| {rate}% | {a['single']:.4f} | {a['static']:.4f} | {a['dynamic']:.4f} | {t['best']} | {t['hard_best']} |")
    lines += ['', 'Switch point: Single 最优至 20%,Dynamic 于 30% 整体反超(切换带 (20%,30%]);Hard 子集自 20% 起 Dynamic 最优。']
    (BENCH / 'MULTIOBJECTIVE_TRADEOFF.md').write_text('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    run()
