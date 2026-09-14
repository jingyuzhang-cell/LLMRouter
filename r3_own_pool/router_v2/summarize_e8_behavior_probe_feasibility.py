"""E8 rotation-averaged EQ, paired contrasts, switch diagnostics, and the verdict."""
import json
from pathlib import Path
import numpy as np

from .data import sha
from .run_e8_behavior_probe_feasibility import OUT, ARMS, SLOTS, write, status

BOOT_N = 10000
BOOT_SEED = 20260914


def summarize():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    frozen = json.loads((OUT / 'PREDICTIONS_FROZEN.json').read_text())
    if sha(OUT / 'PREDICTIONS.npz') != frozen['predictions_sha256'] or sha(OUT / 'PROTOCOL.json') != frozen['protocol_sha256']:
        raise ValueError('Predictions/protocol changed')
    z = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    p = np.load(OUT / 'PREDICTIONS.npz', allow_pickle=False)
    ids = p['ids'].tolist()
    n = len(ids)
    v = z['repeats']
    rotations = p['rotations']
    anchor_eq = p['anchor_eq']
    anchor_choice = p['anchor_choice']
    eq = {a: p[f'{a}__eq'] for a in ARMS}
    matrices = {a: p[f'{a}__eq_matrix'] for a in ARMS}
    choices = {a: p[f'{a}__choice'] for a in ARMS}
    rows = np.arange(n)
    boot = np.random.default_rng(BOOT_SEED).integers(0, n, (BOOT_N, n))

    def interval(diff, coverage=.95):
        return (np.quantile(diff[boot].mean(1), [(1 - coverage) / 2, 1 - (1 - coverage) / 2]).tolist())

    # Rotation-level switch diagnostics (frozen definitions).
    eval_v = {a: np.stack([v[rows, choices[a][:, k], rotations[k, 1]] for k in range(len(rotations))], 1)
              for a in ARMS}
    reasoning_v = np.stack([v[:, 3, rotations[k, 1]] for k in range(len(rotations))], 1)
    diagnostics = {}
    for a in ARMS:
        away = choices[a] != 3
        helped_rot = (matrices[a] > reasoning_v) & away
        precision = helped_rot.sum() / away.sum() if away.sum() else None
        opportunity = (v[:, :3, :].max(1)[:, rotations[:, 1].tolist()] > reasoning_v)
        recall = helped_rot.sum() / opportunity.sum() if opportunity.sum() else None
        diff_a = eq[a] - eq[ARMS[0]]
        diff_anchor = eq[a] - anchor_eq
        ci_a = interval(diff_a)
        diagnostics[a] = dict(
            expected_quality=float(eq[a].mean()),
            switch=dict(away_rotations=int(away.sum()), total_rotations=int(away.size),
                        precision=float(precision) if precision is not None else None,
                        recall=float(recall) if recall is not None else None),
            helped_vs_a=dict(helped=int((diff_a > 0).sum()), harmed=int((diff_a < 0).sum()),
                             per_rotation_helped=int((matrices[a] > matrices[ARMS[0]]).sum()),
                             per_rotation_harmed=int((matrices[a] < matrices[ARMS[0]]).sum())),
            selection_counts=dict(zip(SLOTS, np.bincount(choices[a].ravel(), minlength=4).tolist())),
            vs_queryonly=dict(mean=float(diff_a.mean()), ci95=ci_a,
                              ci98333_bonferroni=interval(diff_a, 1 - .05 / 3)),
            vs_frozen_anchor=dict(mean=float(diff_anchor.mean()), ci95=interval(diff_anchor)),
            success=bool(a != ARMS[0] and eq[a].mean() > anchor_eq.mean() and ci_a[0] > 0))
    contrasts = {f'D_minus_{x[0].upper()}': dict(mean=float((eq[ARMS[3]] - eq[x]).mean()),
                                                 ci95=interval(eq[ARMS[3]] - eq[x]))
                 for x in [ARMS[1], ARMS[2]]}
    passed = [a for a in ARMS[1:] if diagnostics[a]['success']]
    verdict = ('behavior_signal_supported_design_v2' if passed
               else 'no_behavior_gain_consider_stronger_probes_or_stop')
    result = dict(experiment='E8 Behavior-Probe Feasibility', n=n, rotations=int(len(rotations)),
                  reference=dict(anchor_queryonly_eq=float(anchor_eq.mean()),
                                 in_protocol_a_eq=float(eq[ARMS[0]].mean()),
                                 bestsingle_eq=float(z['quality'][rows, np.load(
                                     Path(str(OUT).replace('e8_behavior_probe_feasibility',
                                                           'e6_representation_objective_2x2')) / 'PREDICTIONS.npz',
                                     allow_pickle=False)['bestsingle_choice']].mean())),
                  methods=diagnostics, contrasts=contrasts, passed=passed, verdict=verdict,
                  probe_cost=protocol['slot_cost'],
                  decision=dict(criterion='EQ>73.50% anchor AND paired CI95 lower>0 vs in-protocol A; precision/recall/helped-harmed are diagnostics only',
                                expansion_executed=False, next_experiment_started=False),
                  protocol_sha256=sha(OUT / 'PROTOCOL.json'), predictions_sha256=sha(OUT / 'PREDICTIONS.npz'))
    write(OUT / 'RESULTS.json', result)
    report(result)
    status('COMPLETE', passed=passed, verdict=verdict)


def report(r):
    m = r['methods']
    ref = r['reference']
    lines = ['# E8：Behavior-Probe Feasibility（零新增生成）', '',
             '问题：Router 看到一个便宜模型的实际行为（probe），能否比只看 query 更准地路由。20个(p,r) rotation：probe特征只取第p次，目标用其余3次定义，只在第r次评估，p≠r。bootstrap单位= query。repeat身份=原始文件行序（已验证精确重现E6 repeat矩阵）。', '',
             f'参照：冻结QueryOnly anchor={ref["anchor_queryonly_eq"]:.2%}（rotation均值=mean5 EQ）；in-protocol A={ref["in_protocol_a_eq"]:.2%}（mean3目标重训）；BestSingle={ref["bestsingle_eq"]:.2%}。', '',
             '| 组 | EQ | vs A pp [95% CI] | vs anchor pp [95% CI] | switch精度/召回 | helped/harmed(vs A) | 通过 |', '|---|---:|---|---|---|---|---|']
    for a in ARMS:
        v = m[a]
        d, da = v['vs_queryonly'], v['vs_frozen_anchor']
        sw = v['switch']
        prec = f'{sw["precision"]:.3f}/{sw["recall"]:.3f}' if sw['precision'] is not None else 'n/a'
        lines.append(f'| {a} | {v["expected_quality"]:.2%} | {100 * d["mean"]:+.2f} [{100 * d["ci95"][0]:.2f}, {100 * d["ci95"][1]:.2f}] | '
                     f'{100 * da["mean"]:+.2f} [{100 * da["ci95"][0]:.2f}, {100 * da["ci95"][1]:.2f}] | {prec} | '
                     f'{v["helped_vs_a"]["helped"]}/{v["helped_vs_a"]["harmed"]} | ' +
                     ('基线' if a == ARMS[0] else ('是' if v['success'] else '否')) + ' |')
    lines += ['', '## 判定', '',
              ('有组通过 → ' if r['passed'] else '没有组通过 → ') + (
                  '行为信号成立，进入第二版方法设计（更强的probe设计/partial response是后续选项）。' if r['passed']
                  else '最简行为信号无效；按预注册，考虑更强 probe（partial response/self-confidence/verifier）或停线。'),
              '', '## 选择分布（20 rotation合并）', '', '| 组 | medium | large | coder | reasoning | 离开R1的rotation数 |', '|---|---:|---:|---:|---:|---:|']
    for a in ARMS:
        c = m[a]['selection_counts']
        lines.append(f'| {a} | {c["medium"]} | {c["large"]} | {c["coder"]} | {c["reasoning"]} | {m[a]["switch"]["away_rotations"]} |')
    lines += ['', '## Probe 成本（原始运行统计，中位数）', '', '| slot | 模型 | tokens_out | latency ms |', '|---|---|---:|---:|']
    for s, c in r['probe_cost'].items():
        lines.append(f'| {s} | {c["model"]} | {c["tokens_output_p50"]:.0f} | {c["latency_ms_p50"]:.0f} |')
    lines += ['', 'B/C/D 的 probe 成本 = 每题必付一次 medium（或 large，或两者）的推理；D 为两者之和。路由后的模型成本由选择分布给出。', '',
              '## 对比', '', '| 对比 | EQ变化 pp [95% CI] |', '|---|---|']
    for name, v in r['contrasts'].items():
        lines.append(f'| {name} | {100 * v["mean"]:+.2f} [{100 * v["ci95"][0]:.2f}, {100 * v["ci95"][1]:.2f}] |')
    lines += ['', '## 冻结口径', '',
              '1. 目标：3个target repeats的 V(q,m)−V(q,R1) 均值；Ridge alpha=1 三个delta头，R1分数恒0，first-max tie order。',
              '2. probe特征18维/模型：parse(2)+选项one-hot(10)+log长度/tokens/latency/tps+finish+status；joint 4维：一致/不一致/有未解析 + token差。全部只用第p次原始输出，无ground truth。',
              '3. anchor= E6 冻结 QueryOnly 选择，同 rotation 评估；其 rotation 均值按构造等于 mean5 EQ（代码内断言验证）。',
              '4. AUC 类指标不进入判据。98.33% Bonferroni 区间在 RESULTS.json 作背景。', '',
              '## 结论边界', '',
              '- latency/tokens 来自历史运行，是 probe 成本的代理，非重新测量；部署 probe 看到的是一次 temperature 0.7 的新采样。',
              '- bootstrap 条件于已拟合模型；不含重训不确定性。',
              '- 本版只有最简行为信号；无效不排除更强 probe 形式。', '',
              '文件：PROTOCOL.json / INPUTS.npz / PREDICTIONS.npz / RESULTS.json。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    summarize()
