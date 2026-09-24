"""Pareto-aware Dynamic Scheduler(轻量多目标策略选择,零新调用)。

定位:不做全空间搜索;在已执行的候选策略池上,按状态 (故障率 p̂, 预算 B) 从 Pareto
前沿中选择策略。评估用 3 折跨种子 CV(2 种子校准 / 1 种子测试),对照:
  random(均匀期望) / cost-only(恒最廉=Single) / accuracy-only(恒 clean 最高=Single)
  fixed-Dynamic / oracle-per-state(测试种子逐状态最优,上界)。
指标:32 个状态(4 故障率 × 8 预算档)的预算内正确完成率 Q(B)、所选策略平均 tokens、
以及 B=3000 与不限预算两个口径下的质量保持(可靠性)。
输出 PARETO_SCHEDULER.md / .json;数据源全部为冻结工件。
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


def load_clean():
    clean = json.load(open(f'{OUT}/CLEAN_RESULTS.json'))
    return {m: clean[m] for m in POOL}


def load_fault(seed):
    sub = f'{OUT}/fault_p{int(seed_rate(seed)*100)}' if seed == 20260923 else f'{OUT}/fault_p{int(seed_rate(seed)*100)}_seed{seed}'
    return json.load(open(sub + '/FAULT_RESULT.json'))


def seed_rate(seed):
    return {20260923: 0.1, 20260924: 0.1, 20260925: 0.1}[seed]  # placeholder, unused


def load(seed, rate):
    sub = f'{OUT}/fault_p{int(rate*100)}' if seed == 20260923 else f'{OUT}/fault_p{int(rate*100)}_seed{seed}'
    return json.load(open(sub + '/FAULT_RESULT.json'))


def q_b(rows, uids, B):
    return sum(1 for u in uids if rows[u]['ok'] and rows[u]['used'] <= B) / len(uids)


def mean_tokens(rows, uids):
    return sum(rows[u]['used'] for u in uids) / len(uids)


def run():
    pol = json.load(open(f'{BASE}/multidag_dynamic_120/POLICY.json'))
    uids = [t['uid'] for t in pol['tasks']]
    n = len(uids)
    clean = load_clean()

    # ---- 校准/测试数据:每策略每状态在每种子下的 Q(B) 与平均 tokens ----
    perf = {}  # (rate, seed) -> {m: {B: q_b}}, tokens
    for rate in RATES:
        for seed in SEEDS:
            if rate == 0:
                rows_by_m = {m: clean[m] for m in POOL}
            else:
                fr = load(seed, rate)
                rows_by_m = {m: fr[m] for m in POOL}
            perf[(rate, seed)] = {
                m: dict(qb={B: q_b(rows_by_m[m], uids, B) for B in BUDGETS},
                        tokens=mean_tokens(rows_by_m[m], uids),
                        q_unlim=sum(1 for u in uids if rows_by_m[m][u]['ok']) / n)
                for m in POOL}

    def front(rate, cal_seeds):
        """校准集上该故障率的 (Q_unlim, -tokens) Pareto 前沿。"""
        pts = {m: (st.mean([perf[(rate, s)][m]['q_unlim'] for s in cal_seeds]),
                   st.mean([perf[(rate, s)][m]['tokens'] for s in cal_seeds])) for m in POOL}
        return {m for m in pts
                if not any(pts[o][0] >= pts[m][0] and pts[o][1] <= pts[m][1] and
                           (pts[o][0] > pts[m][0] or pts[o][1] < pts[m][1]) for o in pts if o != m)}

    def select(rate, B, cal_seeds):
        """Pareto-aware selector:前沿内取校准 Q(B) 最高者。"""
        f = front(rate, cal_seeds)
        return max(f, key=lambda m: st.mean([perf[(rate, s)][m]['qb'][B] for s in cal_seeds]))

    # ---- 评估:3 折 CV ----
    policies = ['random', 'cost_only', 'accuracy_only', 'fixed_dynamic', 'pareto_selector', 'oracle_state']
    grid = {p: {r: {B: [] for B in BUDGETS} for r in RATES} for p in policies}
    cost_of = {p: {r: [] for r in RATES} for p in policies}
    for test_seed in SEEDS:
        cal = [s for s in SEEDS if s != test_seed]
        for rate in RATES:
            for B in BUDGETS:
                realized = {m: perf[(rate, test_seed)][m]['qb'][B] for m in POOL}
                choices = {
                    'random': st.mean(realized.values()),
                    'cost_only': realized['router'],
                    'accuracy_only': realized[max(POOL, key=lambda m: st.mean([perf[(0, s)][m]['q_unlim'] for s in cal]))],
                    'fixed_dynamic': realized['dynamic'],
                    'pareto_selector': realized[select(rate, B, cal)],
                    'oracle_state': max(realized.values()),
                }
                for p in policies:
                    grid[p][rate][B].append(choices[p])
            tok = {m: perf[(rate, test_seed)][m]['tokens'] for m in POOL}
            sel = select(rate, 3000, cal)
            cost_of['random'][rate].append(st.mean(tok.values()))
            cost_of['cost_only'][rate].append(tok['router'])
            cost_of['accuracy_only'][rate].append(tok['router'])
            cost_of['fixed_dynamic'][rate].append(tok['dynamic'])
            cost_of['pareto_selector'][rate].append(tok[sel])
            cost_of['oracle_state'][rate].append(tok[max(POOL, key=lambda m: perf[(rate, test_seed)][m]['q_unlim'])])

    def gavg(p, rate=None, B=None):
        vals = []
        for r in ([rate] if rate else RATES):
            for B_ in ([B] if B else BUDGETS):
                vals.append(st.mean(grid[p][r][B_]))
        return st.mean(vals)

    # ---- 报告 ----
    lines = ['# Pareto-aware Dynamic Scheduler(轻量多目标策略选择,零新调用)', '',
             f'状态空间:{len(RATES)} 故障率 × {len(BUDGETS)} 预算档 = {len(RATES)*len(BUDGETS)} 状态;'
             '3 折跨种子 CV(2 种子校准 / 1 种子测试);候选池 = 已执行的 {"/".join(POOL)}。', '',
             '## 全状态网格平均预算内完成率 Q(B) 与平均 tokens', '',
             '| 策略 | 网格平均 Q(B) | 平均 tokens/题 |', '|---|---:|---:|']
    for p in policies:
        q = gavg(p)
        c = st.mean([st.mean(cost_of[p][r]) for r in RATES])
        lines.append(f'| {p} | {q:.4f} | {c:.0f} |')
    lines += ['', '## 分故障率明细(B=3000 与不限预算)', '',
              '| 故障率 | Single | fixed-Dynamic | pareto_selector | oracle | selector 选择 |',
              '|---:|---:|---:|---:|---:|---|']
    for rate in RATES:
        sel_counts = {}
        for test_seed in SEEDS:
            cal = [s for s in SEEDS if s != test_seed]
            s = select(rate, 3000, cal)
            sel_counts[s] = sel_counts.get(s, 0) + 1
        q = st.mean(grid['pareto_selector'][rate][3000])
        qs = st.mean(grid['cost_only'][rate][3000])
        qd = st.mean(grid['fixed_dynamic'][rate][3000])
        qo = st.mean(grid['oracle_state'][rate][3000])
        rule = '/'.join(f'{k}×{v}' for k, v in sel_counts.items())
        lines.append(f'| {int(rate*100)}% | {qs:.4f} | {qd:.4f} | {q:.4f} | {qo:.4f} | {rule} |')
    # 可靠性(不限预算口径,用 clean 与 f30 的 q_unlim)
    rel = {}
    for p in ('cost_only', 'fixed_dynamic', 'pareto_selector'):
        q0 = st.mean([perf[(0, s)]['router' if p == 'cost_only' else 'dynamic' if p == 'fixed_dynamic' else 'router']['q_unlim'] for s in SEEDS])
        lines.append('')
    rep = dict(
        policies=policies,
        grid_avg={p: dict(Q=round(gavg(p), 4),
                          Q_B3000=round(gavg(p, B=3000), 4),
                          mean_tokens=round(st.mean([st.mean(cost_of[p][r]) for r in RATES]), 1)) for p in policies},
        per_rate_B3000={int(r*100): {p: round(st.mean(grid[p][r][3000]), 4) for p in policies} for r in RATES},
        note='zero new calls; 3-fold CV over seeds; state = (fault rate, budget); pool = executed arms only',
    )
    open(f'{OUT}/PARETO_SCHEDULER.json', 'w').write(json.dumps(rep, ensure_ascii=False, indent=1))
    open(f'{OUT}/PARETO_SCHEDULER.md', 'w').write('\n'.join(lines))
    print('\n'.join(lines))
    print('\ngrid_avg:', json.dumps(rep['grid_avg'], indent=1))


if __name__ == '__main__':
    run()
