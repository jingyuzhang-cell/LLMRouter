"""E9a summary: EQ, paired contrasts vs A, stable-switch diagnostics, verdict."""
import json
from pathlib import Path
import numpy as np

from .data import sha
from .run_e9a_deterministic_logit_probe import OUT, ARMS, SLOTS, write, status
from .run_e7_stable_preference_probe import stable_switch_labels

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
    quality = z['quality']
    rows = np.arange(n)
    e6 = np.load(Path(str(OUT).replace('e9a_deterministic_logit_probe',
                                       'e6_representation_objective_2x2')) / 'PREDICTIONS.npz', allow_pickle=False)
    base = quality[rows, e6['bestsingle_choice']]
    oracle = quality.max(1)
    gap = float((oracle - base).mean())
    _, switch, _, _, _ = stable_switch_labels(z['repeats'])
    anchor_eq = quality[rows, p['anchor_choice']]
    eq = {a: p[f'{a}__eq'] for a in ARMS}
    choices = {a: p[f'{a}__choice'] for a in ARMS}
    boot = np.random.default_rng(BOOT_SEED).integers(0, n, (BOOT_N, n))

    def interval(diff, coverage=.95):
        return np.quantile(diff[boot].mean(1), [(1 - coverage) / 2, 1 - (1 - coverage) / 2]).tolist()

    gap_samples = (oracle - base)[boot].mean(1)
    methods = {}
    for a in ARMS:
        away = choices[a] != 3
        diff = eq[a] - anchor_eq
        ci = interval(diff)
        gain = eq[a] - base
        precision = float(switch[away].mean()) if away.any() else None
        recall = float(away[switch].mean())
        methods[a] = dict(
            expected_quality=float(eq[a].mean()),
            gap_recovery=float(gain.mean() / gap),
            away=dict(rate=float(away.mean()), count=int(away.sum()),
                      stable_switch_precision=precision, stable_switch_recall=recall),
            vs_queryonly=dict(mean=float(diff.mean()), ci95=ci, ci975_bonferroni=interval(diff, 1 - .05 / 2)),
            helped=int((diff > 0).sum()), harmed=int((diff < 0).sum()),
            selection_counts=dict(zip(SLOTS, np.bincount(choices[a], minlength=4).tolist())),
            success=bool(a != ARMS[0] and eq[a].mean() > anchor_eq.mean() and ci[0] > 0))
    probe_agreement = float((p['probe_top1'] == p['sampled_majority'])[p['majority_exists'] > .5].mean())
    passed = [a for a in ARMS[1:] if methods[a]['success']]
    verdict = ('confidence_profile_router_supported' if passed
               else 'logit_probe_fails_one_e9b_pilot_left_then_stop')
    result = dict(experiment='E9a Deterministic Logit Probe', n=n,
                  reference=dict(anchor_queryonly_eq=float(anchor_eq.mean()), bestsingle_eq=float(base.mean()),
                                 hindsight_oracle_eq=float(oracle.mean()), oracle_gap=gap),
                  probe_diagnostics=dict(top1_equals_sampled_majority_rate=probe_agreement,
                                         majority_exists=float((p['majority_exists'] > .5).mean())),
                  methods=methods, passed=passed, verdict=verdict,
                  decision=dict(criterion='EQ>73.50% AND paired CI95 lower>0 vs A; diagnostics never decide',
                                expansion_executed=False, next_experiment_started=False),
                  protocol_sha256=sha(OUT / 'PROTOCOL.json'), predictions_sha256=sha(OUT / 'PREDICTIONS.npz'))
    write(OUT / 'RESULTS.json', result)
    report(result)
    status('COMPLETE', passed=passed, verdict=verdict)


def report(r):
    m = r['methods']
    ref = r['reference']
    pd_ = r['probe_diagnostics']
    lines = ['# E9a：Deterministic Logit Probe（零生成）', '',
             '本地Qwen2.5-7B-Instruct单次确定性forward：原文+冻结后缀`Answer:`，取该位置10个选项字母token的next-token softmax。无采样、无CoT、无ground truth。三臂冻结，E6折，mean5目标与评估（与73.50% anchor同尺度）；A在代码内断言逐题复现E6 QueryOnly。', '',
             f'参照：anchor={ref["anchor_queryonly_eq"]:.2%}；BestSingle={ref["bestsingle_eq"]:.2%}；Oracle={ref["hindsight_oracle_eq"]:.2%}（GAP {100 * ref["oracle_gap"]:.2f}pp）。probe top-1与medium多数采样选项一致率={pd_["top1_equals_sampled_majority_rate"]:.3f}（多数存在比例={pd_["majority_exists"]:.3f}）。', '',
             '| 组 | EQ | Gap Recovery | vs anchor pp [95% CI] | 离开R1 | stable-switch P/R | helped/harmed | 通过 |', '|---|---:|---:|---|---|---|---|---|']
    for a in ARMS:
        v = m[a]
        d = v['vs_queryonly']
        aw = v['away']
        pr = f'{aw["stable_switch_precision"]:.3f}/{aw["stable_switch_recall"]:.3f}' if aw['stable_switch_precision'] is not None else f'n/a/{aw["stable_switch_recall"]:.3f}'
        lines.append(f'| {a} | {v["expected_quality"]:.2%} | {v["gap_recovery"]:.2%} | '
                     f'{100 * d["mean"]:+.2f} [{100 * d["ci95"][0]:.2f}, {100 * d["ci95"][1]:.2f}] | '
                     f'{aw["rate"]:.1%} | {pr} | {v["helped"]}/{v["harmed"]} | ' +
                     ('基线' if a == ARMS[0] else ('是' if v['success'] else '否')) + ' |')
    lines += ['', '## 判定', '',
              ('有组通过 → ' if r['passed'] else '没有组通过 → ') + (
                  'Query Representation + Model Confidence Profile 收敛为最终方法候选，进入方法整合。' if r['passed']
                  else 'deterministic logit信号无效。按预注册：只剩一次小规模E9b pilot（cheap partial response + verifier/confidence）；E9b再失败则停止信号搜索、重定论文定位。'),
              '', '## 选择分布', '', '| 组 | medium | large | coder | reasoning |', '|---|---:|---:|---:|---:|']
    for a in ARMS:
        c = m[a]['selection_counts']
        lines.append(f'| {a} | {c["medium"]} | {c["large"]} | {c["coder"]} | {c["reasoning"]} |')
    lines += ['', '## 冻结口径', '',
              '1. probe分布：softmax仅归一在10个字母token上（截断式读出），非全词表归一；这是设计选择并已冻结。',
              '2. B特征16维：top-1 one-hot(10)+top1概率+top2 margin+熵+方差+多数存在+与多数一致；C为完整10维概率向量。',
              '3. 主判据唯一：EQ>73.50%且配对bootstrap CI95下界>0；97.5% Bonferroni区间在RESULTS.json作背景。',
              '4. 一致性特征用medium历史5次采样的多数选项（无GT）；部署时对应一次新鲜采样。', '',
              '## 结论边界', '',
              '- 分布读自无CoT的原文prompt；CoT条件化的分布可能不同（E9b范畴）。',
              '- probe是medium槽位模型；未测large/coder的logit profile。',
              '- 400题面板已多次复用，非独立确认。', '',
              '文件：PROTOCOL.json / LOGIT_PROBES.npz / PREDICTIONS.npz / RESULTS.json。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    summarize()
