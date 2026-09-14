"""E7 pooled diagnostics, EQ of the two-stage route, and the frozen verdict."""
import json
from pathlib import Path
import numpy as np
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score

from .data import sha
from .run_e7_stable_preference_probe import OUT, REPS, SLOTS, BOOT_N, BOOT_SEED, write, status


def summarize():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    frozen = json.loads((OUT / 'PREDICTIONS_FROZEN.json').read_text())
    if sha(OUT / 'PREDICTIONS.npz') != frozen['predictions_sha256'] or sha(OUT / 'PROTOCOL.json') != frozen['protocol_sha256']:
        raise ValueError('Predictions/protocol changed')
    if sha(OUT / 'FIT_AUDIT.json') != frozen['fit_audit_sha256']:
        raise ValueError('Fit audit changed')
    z = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    p = np.load(OUT / 'PREDICTIONS.npz', allow_pickle=False)
    e6 = np.load(Path(str(OUT).replace('e7_stable_preference_probe', 'e6_representation_objective_2x2')) / 'PREDICTIONS.npz',
                 allow_pickle=False)
    if e6['ids'].tolist() != z['ids'].tolist():
        raise ValueError('E6/E7 id mismatch')
    rows = np.arange(len(z['ids']))
    y = z['quality']
    switch = z['switch'].astype(bool)
    which = z['which']
    a_choice = e6['A_QueryOnly_choice']
    base = y[rows, e6['bestsingle_choice']]
    oracle = protocol['labels']['decomposed_oracle_eq']
    boot = np.random.default_rng(BOOT_SEED).integers(0, len(z['ids']), (BOOT_N, len(z['ids'])))
    gap = oracle - base.mean()

    def interval(v, coverage=.95):
        return np.quantile(v[boot].mean(1), [(1 - coverage) / 2, 1 - (1 - coverage) / 2]).tolist()

    methods = {}
    for rep in REPS:
        prob = p[f'{rep}__p1']
        pred_switch = prob >= .5
        routed = p[f'{rep}__routed']
        sens = p[f'{rep}__sensitivity_routed']
        mask = switch & (which >= 0)
        alt_u = p[f'{rep}__alt_unconditional']
        q = y[rows, routed]
        diff = q - y[rows, a_choice]
        ci = interval(diff)
        methods[rep] = dict(
            stage1=dict(roc_auc=float(roc_auc_score(switch, prob)),
                        pr_auc=float(average_precision_score(switch, prob)),
                        recall_at_05=float(recall_score(switch, pred_switch)),
                        precision_at_05=float(precision_score(switch, pred_switch, zero_division=0)),
                        predicted_switch=int(pred_switch.sum()), true_switch=int(switch.sum())),
            stage2_on_true_switch=dict(n=int(mask.sum()),
                                       accuracy=float(accuracy_score(which[mask], routed[mask])) if mask.any() else None,
                                       macro_f1=float(f1_score(which[mask], routed[mask], average='macro')) if mask.any() else None),
            stage2_unconditional_on_true_switch=dict(
                n=int(mask.sum()),
                accuracy=float(accuracy_score(which[mask], alt_u[mask])) if mask.any() else None,
                macro_f1=float(f1_score(which[mask], alt_u[mask], average='macro')) if mask.any() else None,
                note='stage-2 classifier on all true switch queries, ungated by the stage-1 threshold'),
            expected_quality=float(q.mean()),
            sensitivity_expected_quality=float(y[rows, sens].mean()),
            vs_queryonly=dict(mean=float(diff.mean()), ci95=ci, ci9875_bonferroni=interval(diff, 1 - .05 / 4)),
            vs_bestsingle=float((q - base).mean()),
            gap_recovery=float((q.mean() - base.mean()) / gap),
            success_vs_queryonly=bool(diff.mean() > 0 and ci[0] > 0),
            selection_counts=dict(zip(SLOTS, np.bincount(routed, minlength=4).tolist())),
            switch_decisions=dict(route_away_from_r1=int((routed != 3).sum()), helped=int((diff > 0).sum()),
                                  harmed=int((diff < 0).sum())))
    passed = [r for r in REPS if methods[r]['success_vs_queryonly']]
    verdict = ('representation_supported_integrate_into_MA_router' if passed
               else 'no_representation_recovers_switch_signal_move_to_model_probe_routing')
    best_auc = max(methods, key=lambda r: methods[r]['stage1']['roc_auc'])
    result = dict(experiment='E7 Stable Preference Representation Probe', n=int(len(z['ids'])),
                  reference=dict(bestsingle_eq=float(base.mean()), queryonly_eq=float(y[rows, a_choice].mean()),
                                 decomposed_oracle_eq=oracle),
                  methods=methods, passed=passed, verdict=verdict,
                  best_stage1_auc=best_auc,
                  decision=dict(criterion='EQ>73.50% AND paired CI95 lower>0 vs E6 A_QueryOnly; AUC/F1 are diagnostics only',
                                auc_not_eq_warning='A higher switch AUC without EQ>QueryOnly is NOT router improvement',
                                expansion_executed=False, next_experiment_started=False),
                  protocol_sha256=sha(OUT / 'PROTOCOL.json'), predictions_sha256=sha(OUT / 'PREDICTIONS.npz'))
    write(OUT / 'RESULTS.json', result)
    report(result)
    status('COMPLETE', passed=passed, verdict=verdict)


def report(r):
    m = r['methods']
    ref = r['reference']
    lines = ['# E7：稳定偏好表示探针（Representation Probe）', '',
             '问题：题目表示里是否有足够信息判断“何时应离开 R1、切给谁”。两段式分解 ShouldSwitch→WhichAlternative，分解oracle=81.00%，与hindsight oracle相等，分解本身不损失上限。四种表示、dev-fold标准化+L2 logistic(C=1.0)、阈值0.5冻结、E6 frozen folds、零生成（仅本地Qwen2.5-7B forward）。', '',
             f'参照：BestSingle={ref["bestsingle_eq"]:.2%}；QueryOnly(A)={ref["queryonly_eq"]:.2%}；分解oracle={ref["decomposed_oracle_eq"]:.2%}。', '',
             '| 表示 | Switch ROC-AUC | PR-AUC | Recall@0.5 | Stage2 Acc(未闸门) | Macro-F1 | EQ | vs A pp [95% CI] | 通过 |', '|---|---:|---:|---:|---:|---:|---:|---|---|']
    for rep, v in m.items():
        s1 = v['stage1']
        s2 = v['stage2_unconditional_on_true_switch']
        d = v['vs_queryonly']
        lines.append(f'| {rep} | {s1["roc_auc"]:.3f} | {s1["pr_auc"]:.3f} | {s1["recall_at_05"]:.3f} | '
                     f'{s2["accuracy"]:.3f} | {s2["macro_f1"]:.3f} | {v["expected_quality"]:.2%} | '
                     f'{100 * d["mean"]:+.2f} [{100 * d["ci95"][0]:.2f}, {100 * d["ci95"][1]:.2f}] | '
                     f'{"是" if v["success_vs_queryonly"] else "否"} |')
    lines += ['', f'真实switch query：{m[REPS[0]]["stage1"]["true_switch"]}/400；各表示预测switch数：'
              + '，'.join(f'{r}={m[r]["stage1"]["predicted_switch"]}' for r in REPS) + '。',
              '成功判据唯一：EQ>73.50% 且相对A的配对bootstrap CI95下界>0。AUC/PR-AUC/F1只是诊断——switch AUC更高但EQ未超过QueryOnly不算Router改善。98.75% Bonferroni区间在RESULTS.json中作背景。', '',
              '## 判定', '',
              ('至少一种表示通过 → ' if r['passed'] else '没有任何表示通过 → ') + (
                  '把该表示整合回MA-Router（分支一）。' if r['passed']
                  else '停止纯query-only静态Router；下一步转向 query→cheap model probe/partial response→routing（分支二，未启动）。'), '',
              '## 选择分布与switch行为', '', '| 表示 | medium | large | coder | reasoning | 离开R1题数 | helped/harmed vs A |', '|---|---:|---:|---:|---:|---:|---|']
    for rep, v in m.items():
        c = v['selection_counts']
        sw = v['switch_decisions']
        lines.append(f'| {rep} | {c["medium"]} | {c["large"]} | {c["coder"]} | {c["reasoning"]} | {sw["route_away_from_r1"]} | {sw["helped"]}/{sw["harmed"]} |')
    lines += ['', '## 敏感性（非判据）', '',
              '阈值=dev内switch基础率的路由EQ（仅报告，不参与判定）：'
              + '，'.join(f'{r}={m[r]["sensitivity_expected_quality"]:.2%}' for r in REPS) + '。', '',
              '## 冻结口径', '',
              '1. 标签：mean5(m)−mean5(R1)>0 且 ≥4/5 repeats ≥ R1 → stable advantage；WhichAlt取稳定者中mean5差最大。77/400 switch，medium 27/large 36/coder 14。',
              '2. 表示：R0=E6冻结GTE；R1=R0+15个确定性结构特征+14 subject one-hot（control）；R2=Qwen2.5-7B-Instruct末层masked-mean hidden state（原文、无chat template、无生成）；R3=全拼接。',
              '3. 分类器：StandardScaler(仅dev)+L2 logistic C=1.0，阈值0.5；无PCA/无MLP/无阈值搜索/无类权重。所有表示同一管线。',
              '4. 折：E6三个frozen outer folds原样复用；A的选择取自E6 PREDICTIONS.npz。', '',
              '## 结论边界', '',
              '- 阈值0.5与19%正类率：stage1可能极端保守（几乎不switch），此时EQ≈BestSingle本身就是“可预测性不足”的诊断。',
              '- 77个switch query的stage2只有约50个dev样本，macro-F1的CI很宽；F1不进入成功判据。',
              '- 本实验不训练Router、不调权重、不扩K；R2只做forward提取，与API/生成无关。',
              '- 未通过≠证明query-only永远不可行；按预注册分支转向行为信号路由。', '',
              '文件：PROTOCOL.json / EMBEDDINGS_QWEN.npz / INPUTS.npz / PREDICTIONS.npz / FIT_AUDIT.json / RESULTS.json。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    summarize()
