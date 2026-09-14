"""Paired query-level inference for the fixed E5 learning curves."""
import json
from pathlib import Path
import numpy as np

from .data import sha
from .run_e5_independent_query_learning_curve import (
    OUT, SLOTS, METHODS, REPRESENTATIONS, NS, SUBSEEDS, MASEEDS,
    job_name, verify, write_json, status,
)


def seed_summary(values):
    a = np.asarray(values, dtype=float)
    return dict(mean=float(a.mean()), std=float(a.std(ddof=1)), by_subsampling_seed=a.tolist())


def percentile(values):
    return np.percentile(values, [2.5, 97.5]).tolist()


def summarize():
    verify()
    if (OUT / 'RESULTS.json').exists():
        raise FileExistsError('E5 results already exist')
    samples = [json.loads(r) for r in (OUT / 'SAMPLES.jsonl').open()]
    data = np.load(OUT / 'INPUTS.npz', allow_pickle=False)
    ids = data['ids'].tolist(); y = data['quality'].astype('float64')
    # Axes: representation,N,subsampling seed,method,query.
    test = np.zeros((2, 4, 10, 3, 400), dtype=float)
    train_sum = np.zeros_like(test)
    train_counts = np.zeros((2, 4, 10, 400), dtype=float)
    coverage = np.zeros_like(train_counts)
    selections = np.zeros((2, 4, 10, 3, 4), dtype=float)
    optimizer_test = np.zeros((2, 4, 10, 3, 400), dtype=float)
    records = []; job_hashes = {}
    for ri, representation in enumerate(REPRESENTATIONS):
        for sample in samples:
            ni = NS.index(sample['n']); si = SUBSEEDS.index(sample['subsampling_seed'])
            name = job_name(representation, sample)
            meta_path, pred_path = OUT / 'jobs' / f'{name}.json', OUT / 'jobs' / f'{name}.npz'
            meta = json.loads(meta_path.read_text())
            if sha(pred_path) != meta['npz_sha256'] or meta['protocol_sha256'] != sha(OUT / 'PROTOCOL.json'):
                raise ValueError('Job integrity mismatch: ' + name)
            job_hashes[name] = dict(metadata=sha(meta_path), predictions=sha(pred_path))
            z = np.load(pred_path, allow_pickle=False)
            d, t = z['development_indices'], z['test_indices']
            if [ids[i] for i in d] != sample['development_ids'] or [ids[i] for i in t] != sample['test_ids']:
                raise ValueError('Saved prediction indices disagree with frozen sample')
            best = int(z['bestsingle'])
            if best != y[d].astype('float32').mean(0).argmax():
                raise ValueError('BestSingle not train-selected')
            ridge_t, ridge_d = z['ridge_test'].argmax(1), z['ridge_train'].argmax(1)
            ma_t, ma_d = z['ma_test'].argmax(2), z['ma_train'].argmax(2)
            mt = y[t[None, :], ma_t]; md = y[d[None, :], ma_d]
            tq = [y[t, best], y[t, ridge_t], mt.mean(0)]
            dq = [y[d, best], y[d, ridge_d], md.mean(0)]
            counts = [np.bincount(np.full(len(t), best), minlength=4),
                      np.bincount(ridge_t, minlength=4),
                      np.bincount(ma_t.ravel(), minlength=4) / len(MASEEDS)]
            coverage[ri, ni, si, t] += 1
            train_counts[ri, ni, si, d] += 1
            optimizer_test[ri, ni, si][:, t] = mt
            methods = {}
            oracle = y[t].max(1)
            for mi, method in enumerate(METHODS):
                test[ri, ni, si, mi, t] = tq[mi]
                train_sum[ri, ni, si, mi, d] += dq[mi]
                selections[ri, ni, si, mi] += counts[mi]
                gain = float((tq[mi] - tq[0]).mean())
                gap = float((oracle - tq[0]).mean())
                methods[method] = dict(train_expected_quality=float(dq[mi].mean()),
                    outer_test_expected_quality=float(tq[mi].mean()),
                    train_test_gap=float(dq[mi].mean() - tq[mi].mean()),
                    gain_vs_bestsingle=gain, gap_recovery=(gain / gap if gap > 0 else None),
                    selection_counts=dict(zip(SLOTS, counts[mi].tolist())))
            records.append(dict(representation=representation, n=sample['n'], actual_n=len(d),
                fold=sample['fold'], subsampling_seed=sample['subsampling_seed'], test_n=len(t),
                job=name, sample_key=sample['sample_key'], subject_counts=sample['subject_counts'],
                inner_train_n=len(sample['inner_train_ids']), inner_validation_n=len(sample['inner_validation_ids']),
                methods=methods, delta_ma_minus_queryonly=float((tq[2] - tq[1]).mean()),
                ma_optimization_seeds=[dict(seed=s, train_eq=float(md[j].mean()), test_eq=float(mt[j].mean()),
                                              **meta['ma_fit'][j]) for j, s in enumerate(MASEEDS)],
                source_prediction_sha256=meta['npz_sha256']))
    if not np.all(coverage == 1):
        raise ValueError('Every query must have one outer prediction per configuration')
    if not np.array_equal(train_counts[0], train_counts[1]):
        raise ValueError('Primary and secondary samples differ')
    if not np.array_equal(test[0, :, :, 0], test[1, :, :, 0]):
        raise ValueError('Representation changed BestSingle')
    # Full has identical training sets, fixed optimization seeds, and thus no subsampling variance.
    if not np.all(test[:, 3] == test[:, 3, :1]) or not np.all(train_sum[:, 3] == train_sum[:, 3, :1]):
        raise ValueError('Full changed across subsampling seeds')
    (OUT / 'PER_FOLD.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in records))
    np.savez_compressed(OUT / 'POOLED_PREDICTIONS.npz', ids=np.array(ids), test=test, train_sum=train_sum,
                        train_counts=train_counts, selections=selections, optimizer_test=optimizer_test)
    boot = np.random.default_rng(20260914).integers(0, 400, (10000, 400))
    oracle = y.max(1)

    def query_boot(q):
        return q[boot].mean(1)

    def comparison(seed_query_diff):
        q = seed_query_diff.mean(0)
        return dict(**seed_summary(seed_query_diff.mean(1)), ci95=percentile(query_boot(q)))

    output = {}; eq_dist = {}; train_dist = {}
    for ri, representation in enumerate(REPRESENTATIONS):
        levels = {}
        for ni, n in enumerate(NS):
            bm = test[ri, ni, :, 0]
            baseline_q = bm.mean(0)
            gap_boot = query_boot(oracle - baseline_q)
            if np.any(gap_boot <= 0):
                raise ValueError('Nonpositive empirical oracle gap in bootstrap; ratio needs separate handling')
            methods = {}
            for mi, method in enumerate(METHODS):
                tq = test[ri, ni, :, mi]
                seed_test = tq.mean(1)
                seed_train = train_sum[ri, ni, :, mi].sum(1) / train_counts[ri, ni].sum(1)
                numerator = train_sum[ri, ni, :, mi].sum(0)
                denominator = train_counts[ri, ni].sum(0)
                train_boot = numerator[boot].sum(1) / denominator[boot].sum(1)
                test_boot = query_boot(tq.mean(0))
                train_dist[(ri, ni, mi)] = train_boot
                eq_dist[(ri, ni, mi)] = test_boot
                gain = tq - bm
                gain_boot = query_boot(gain.mean(0))
                seed_recovery = gain.mean(1) / (oracle.mean() - bm.mean(1))
                count = selections[ri, ni, :, mi]
                opt = None
                if method == 'RepeatPairwiseMA':
                    op = optimizer_test[ri, ni].mean(0).mean(1)
                    opt = dict(seeds=MASEEDS, mean_test_eq_by_optimizer=op.tolist(),
                               std_over_optimizers_after_subsampling_mean=float(op.std(ddof=1)))
                methods[method] = dict(
                    train_expected_quality={**seed_summary(seed_train), 'ci95': percentile(train_boot)},
                    outer_test_expected_quality={**seed_summary(seed_test), 'ci95': percentile(test_boot)},
                    train_test_gap={**seed_summary(seed_train - seed_test), 'ci95': percentile(train_boot - test_boot)},
                    comparison_vs_bestsingle=comparison(gain),
                    gap_recovery={**seed_summary(seed_recovery), 'ci95': percentile(gain_boot / gap_boot),
                                  'pooled_ratio': float(gain.mean() / (oracle.mean() - bm.mean()))},
                    selection_distribution={s: dict(mean_count=float(count[:, j].mean()), std_count=float(count[:, j].std(ddof=1)),
                                                    mean_fraction=float(count[:, j].mean() / 400)) for j, s in enumerate(SLOTS)},
                    optimization_seed_sensitivity=opt)
            levels[n] = dict(actual_n_by_fold={str(f): next(r['actual_n'] for r in records if r['n'] == n and r['fold'] == f) for f in range(3)},
                methods=methods, delta_ma_minus_queryonly=comparison(test[ri, ni, :, 2] - test[ri, ni, :, 1]),
                empirical_oracle_eq=float(oracle.mean()), matched_bestsingle_eq=float(bm.mean()))
        transitions = {}
        for a, b in [(0, 1), (1, 2), (2, 3), (0, 3)]:
            row = {}
            for mi, method in enumerate(METHODS):
                test_change = comparison(test[ri, b, :, mi] - test[ri, a, :, mi])
                train_a = train_sum[ri, a, :, mi].sum(1) / train_counts[ri, a].sum(1)
                train_b = train_sum[ri, b, :, mi].sum(1) / train_counts[ri, b].sum(1)
                tr_diff = train_dist[(ri, b, mi)] - train_dist[(ri, a, mi)]
                te_diff = eq_dist[(ri, b, mi)] - eq_dist[(ri, a, mi)]
                row[method] = dict(outer_test_change=test_change,
                    train_change={**seed_summary(train_b - train_a), 'ci95': percentile(tr_diff)},
                    train_test_gap_change={**seed_summary((train_b - train_a) - (test[ri, b, :, mi] - test[ri, a, :, mi]).mean(1)),
                                           'ci95': percentile(tr_diff - te_diff)})
            row['delta_ma_minus_queryonly_change'] = comparison(
                (test[ri, b, :, 2] - test[ri, b, :, 1]) - (test[ri, a, :, 2] - test[ri, a, :, 1]))
            transitions[f'{NS[a]}_to_{NS[b]}'] = row
        output[representation] = dict(levels=levels, marginal_gains=transitions)
    primary = output['Original']; endpoint = primary['marginal_gains']['40_to_Full']
    last = primary['marginal_gains']['120_to_Full']
    ridge = endpoint['QueryOnlyRidge']['outer_test_change']; ma = endpoint['RepeatPairwiseMA']['outer_test_change']
    delta = endpoint['delta_ma_minus_queryonly_change']; train = endpoint['RepeatPairwiseMA']['train_change']
    data_limited = delta['ci95'][0] > 0 and last['RepeatPairwiseMA']['outer_test_change']['ci95'][0] > 0
    representation_limited = ridge['ci95'][0] > 0 and delta['ci95'][1] < 0 and ma['ci95'][0] <= 0
    overfitting = train['ci95'][0] > 0 and ma['ci95'][1] <= 0
    patterns = [name for name, yes in [('data-limited', data_limited), ('representation-limited', representation_limited), ('overfitting', overfitting)] if yes]
    verdict = patterns[0] if len(patterns) == 1 else 'inconclusive'
    deltas = [primary['levels'][n]['delta_ma_minus_queryonly']['mean'] for n in NS]
    assessment = dict(
        A=dict(improved_40_to_full=ridge['ci95'][0] > 0, latest_step_positive=last['QueryOnlyRidge']['outer_test_change']['ci95'][0] > 0,
               evidence=ridge, latest_step=last['QueryOnlyRidge']['outer_test_change']),
        B=dict(improved_40_to_full=ma['ci95'][0] > 0, latest_step_positive=last['RepeatPairwiseMA']['outer_test_change']['ci95'][0] > 0,
               evidence=ma, latest_step=last['RepeatPairwiseMA']['outer_test_change']),
        C=dict(relative_improvement_40_to_full=delta['ci95'][0] > 0, monotone_point_estimates=bool(np.all(np.diff(deltas) >= -1e-12)), evidence=delta),
        D=dict(direction='Change as N increases from40 toFull', gap_shrinks=endpoint['RepeatPairwiseMA']['train_test_gap_change']['ci95'][1] < 0,
               evidence=endpoint['RepeatPairwiseMA']['train_test_gap_change']),
        E=dict(verdict=verdict, sufficient_patterns=patterns, criteria_source='PROTOCOL.json classification',
               no_expansion_trigger=(verdict != 'data-limited'), secondary_used=False))
    result = dict(experiment='E5 Independent-Query Learning Curve', n_queries=400, repeats=5,
                  subsampling_seeds=SUBSEEDS, optimization_seeds=MASEEDS, methods=METHODS,
                  representations=output, assessment=assessment,
                  protocol_sha256=sha(OUT / 'PROTOCOL.json'), per_fold_sha256=sha(OUT / 'PER_FOLD.jsonl'),
                  pooled_predictions_sha256=sha(OUT / 'POOLED_PREDICTIONS.npz'))
    write_json(OUT / 'RESULTS.json', result)
    write_json(OUT / 'JOB_MANIFEST.json', job_hashes)
    make_report(result)
    status('COMPLETE', verdict=verdict, jobs=len(job_hashes), per_fold_records=len(records), next_experiment_started=False)


def pct(mean_std):
    return f'{100 * mean_std["mean"]:.2f} ± {100 * mean_std["std"]:.2f}'


def effect(row):
    return f'{100 * row["mean"]:+.2f} [{100 * row["ci95"][0]:.2f}, {100 * row["ci95"][1]:.2f}]'


def make_report(result):
    main = result['representations']['Original']; assessment = result['assessment']
    lines = ['# E5：Independent-Query Learning Curve', '',
        f'主判定：**{assessment["E"]["verdict"]}**。以下判断只使用原始提示 GTE；去模板表示仅作 secondary sensitivity。', '',
        '固定400-query ×4-model ×5-repeat corrected labels，保留每题完整五次均值。三折 development 为168/168/167题，outer test 为132/133/135题且始终不变。所有方法共享10个固定分层、嵌套抽样；MA复用未改动的冻结训练函数及42/43/44三个初始化种子。没有新回答、架构/loss/hidden/rank/threshold调整、outer-test选参或GitHub推送。', '',
        'MA先在每个抽样子集内部按原规则选epoch，再在全部N题上重训。表中train EQ为重训后的回代质量。MA指标先平均三个初始化的实际选择质量，再计算10个抽样种子的均值与样本标准差；不是投票集成。Full对10个抽样种子完全相同，只计算一次，抽样标准差为0不代表优化器或总体没有不确定性。', '',
        '## 原始表示主实验', '',
        '| N | 方法 | Train EQ %（均值±std） | Outer EQ %（均值±std） | 对BestSingle增益 pp [95%CI] | Gap Recovery %（均值±std） |',
        '|---|---|---:|---:|---|---:|']
    for n in NS:
        for name in METHODS:
            m = main['levels'][n]['methods'][name]
            lines.append(f'| {n} | {name} | {pct(m["train_expected_quality"])} | {pct(m["outer_test_expected_quality"])} | {effect(m["comparison_vs_bestsingle"])} | {pct(m["gap_recovery"])} |')
    lines += ['', 'Gap Recovery相对同一N/seed选出的BestSingle，分母为经验五重复均值Oracle减该基线；不是理论可达到上界。每次bootstrap共同重算分子与分母。完整train/test/gap/Recovery区间及逐seed数值在RESULTS.json。', '',
        '| N | MA−QueryOnly pp（均值±std） | MA−QueryOnly 95%CI pp | MA train−test gap pp（均值±std） |',
        '|---|---:|---|---:|']
    for n in NS:
        level = main['levels'][n]; d = level['delta_ma_minus_queryonly']
        gap = level['methods']['RepeatPairwiseMA']['train_test_gap']
        lines.append(f'| {n} | {pct(d)} | [{100*d["ci95"][0]:.2f}, {100*d["ci95"][1]:.2f}] | {pct(gap)} |')
    lines += ['', '## 相邻N的边际收益（不外推）', '',
        '| N变化 | QueryOnly outer变化 pp [95%CI] | MA outer变化 pp [95%CI] | Δ(MA−QueryOnly) pp [95%CI] | MA train−test gap变化 pp [95%CI] |',
        '|---|---|---|---|---|']
    for transition, r in main['marginal_gains'].items():
        lines.append(f'| {transition} | {effect(r["QueryOnlyRidge"]["outer_test_change"])} | {effect(r["RepeatPairwiseMA"]["outer_test_change"])} | {effect(r["delta_ma_minus_queryonly_change"])} | {effect(r["RepeatPairwiseMA"]["train_test_gap_change"])} |')
    lines += ['', '## A–E回答', '',
        f'A. QueryOnly：40→Full变化 {effect(assessment["A"]["evidence"])} pp；120→Full变化 {effect(assessment["A"]["latest_step"])} pp。'
        + ('有继续改善证据。' if assessment['A']['latest_step_positive'] else '尚无最后一档仍显著改善的证据，不能据此断言饱和。'),
        '', f'B. MA：40→Full变化 {effect(assessment["B"]["evidence"])} pp；120→Full变化 {effect(assessment["B"]["latest_step"])} pp。'
        + ('有继续改善证据。' if assessment['B']['latest_step_positive'] else '尚无最后一档仍显著改善的证据。'),
        '', f'C. MA相对QueryOnly的差距变化：{effect(assessment["C"]["evidence"])} pp；四档点估计单调上升={assessment["C"]["monotone_point_estimates"]}。'
        + ('相对差距改善区间高于0。' if assessment['C']['relative_improvement_40_to_full'] else '未观察到显著的相对差距缩小。'),
        '', f'D. 当N从40增加到Full时，MA train−test gap变化 {effect(assessment["D"]["evidence"])} pp。'
        + ('区间支持gap随N增加而减小（反向看，小N gap更大）。' if assessment['D']['gap_shrinks'] else '未确认gap随N增加而减小；表中列出所有相邻变化。'),
        '', f'E. 按预先记录的充分判据，分类为 **{assessment["E"]["verdict"]}**。'
        + ('未触发增加独立queries的data-limited条件。' if assessment['E']['no_expansion_trigger'] else '触发data-limited诊断条件，但本轮仍停止，不启动采集。'),
        '', '判据采用充分而非强制归类规则：MA−Ridge全程改善及MA最后一档改善的区间均高于0才判data-limited；Ridge上升且MA相对差距恶化才支持representation-limited；MA训练上升而测试明确不升才支持overfitting。其他情况或冲突归为inconclusive。区间跨0不等于平坦，单凭低样本统计不确定性也不能归为data-limited。', '',
        '## 主实验选择分布', '', '| N | 方法 | medium | large | coder | reasoning |', '|---|---|---:|---:|---:|---:|']
    for n in NS:
        for method in METHODS:
            dist = main['levels'][n]['methods'][method]['selection_distribution']
            lines.append(f'| {n} | {method} | ' + ' | '.join(f'{100*dist[s]["mean_fraction"]:.2f}%' for s in SLOTS) + ' |')
    lines += ['', '## Secondary：去掉答题模板的表示', '',
              '| N | QueryOnly outer EQ % | MA outer EQ % | MA−QueryOnly pp [95%CI] |', '|---|---:|---:|---|']
    secondary = result['representations']['Content_secondary']
    for n in NS:
        level = secondary['levels'][n]
        lines.append(f'| {n} | {pct(level["methods"]["QueryOnlyRidge"]["outer_test_expected_quality"])} | {pct(level["methods"]["RepeatPairwiseMA"]["outer_test_expected_quality"])} | {effect(level["delta_ma_minus_queryonly"])} |')
    lines += ['', '## 解释边界与验证', '',
        '- Full每折仅167–168题。训练曲线变化混合了训练集组成、样本量与原有内层epoch选择的影响；N=40时每学科至少1题验证使验证比例高于20%，规则未调整。',
        '- 面板此前按机会富集且已用于多次开发，本实验不是新确认集。不得将结果推广为全MMLU-Pro或总体泛化结论。',
        '- 10000次query-level配对bootstrap使用相同400个query索引，先在query内平均抽样及初始化种子；不把重复、seed或重叠训练折当独立题目。训练gap区间为按训练出现次数加权的条件描述。',
        '- 所有区间为pointwise95%，未做多重比较校正，也不包含完整重训总体不确定性。representation-limited仅指当前冻结MA表示/目标配方，无法单独因果归因于共享GTE编码器。',
        '- 每折每seed原始结果在PER_FOLD.jsonl，完整抽样名单在SAMPLES.jsonl，逐模型逐query预测在jobs/与POOLED_PREDICTIONS.npz。原始Full基线须复现旧Ridge及全部3个MA初始化决策，否则执行器报错。',
        '', '本轮结束后停止，不自动启动新实验。']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
        xx = [40, 80, 120, (168 + 168 + 167) / 3]
        for mi, method in enumerate(METHODS):
            mean = [100 * main['levels'][n]['methods'][method]['outer_test_expected_quality']['mean'] for n in NS]
            sd = [100 * main['levels'][n]['methods'][method]['outer_test_expected_quality']['std'] for n in NS]
            axes[0].errorbar(xx, mean, yerr=sd, marker='o', capsize=3, label=method)
        axes[0].set(xlabel='Development queries per fold', ylabel='Outer expected quality (%)', title='Original GTE: mean ± subsampling SD')
        axes[0].legend(fontsize=8); axes[0].grid(alpha=.25)
        d = [100 * main['levels'][n]['delta_ma_minus_queryonly']['mean'] for n in NS]
        cis = np.array([main['levels'][n]['delta_ma_minus_queryonly']['ci95'] for n in NS]) * 100
        axes[1].errorbar(xx, d, yerr=np.maximum(0, np.stack([np.array(d)-cis[:, 0], cis[:, 1]-np.array(d)])), marker='o', capsize=3)
        axes[1].axhline(0, color='gray', linestyle='--')
        axes[1].set(xlabel='Development queries per fold', ylabel='MA − QueryOnly (pp)', title='Paired query bootstrap 95% CI')
        axes[1].grid(alpha=.25)
        for ax in axes:
            ax.set_xticks(xx, ['40', '80', '120', 'Full'])
        fig.savefig(OUT / 'LEARNING_CURVE.png', dpi=180)
        fig.savefig(OUT / 'LEARNING_CURVE.svg')
        plt.close(fig)
    except ImportError:
        # Numeric reports are complete without optional plotting dependencies.
        pass


if __name__ == '__main__':
    summarize()
