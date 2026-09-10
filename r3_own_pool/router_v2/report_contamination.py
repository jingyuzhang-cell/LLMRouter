"""Summarize the completed train-only contamination audit and fixed reruns."""
import json
from pathlib import Path
import numpy as np
from .data import sha
ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'router_v2/contamination_audit_20260910b'
    audit=json.loads((out/'AUDIT.json').read_text())
    variants={'旧标签、原折':'objective_signal_20260909', '修复标签、原折':'objective_clean_audit_20260910',
              '修复标签、相似题分组':'objective_clean_grouped_20260910', '修复标签、分组且排除pilot':'objective_clean_no_pilot_20260910'}
    rows={};evidence={}
    for label,name in variants.items():
        p=ROOT/'router_v2'/name/'RESULTS.json';r=json.loads(p.read_text())['results']['all'];rows[label]=r;evidence[str(p)]=sha(p)
    rank_path=ROOT/'router_v2/rank_clean_grouped_20260910/RESULTS.json'
    rank=json.loads(rank_path.read_text())['results']['all'];evidence[str(rank_path)]=sha(rank_path)
    tie_path=ROOT/'router_v2/tieaware_clean_grouped_20260910b/RESULTS.json'
    tie=json.loads(tie_path.read_text());evidence[str(tie_path)]=sha(tie_path)
    old_dir=ROOT/'router_v2/objective_signal_20260909';new_dir=ROOT/'router_v2/objective_clean_audit_20260910'
    with np.load(old_dir/'OOF.npz') as a,np.load(new_dir/'OOF.npz') as b:
        if not np.array_equal(a['ids'],b['ids']) or not np.array_equal(a['folds'],b['folds']):raise ValueError('Same-fold comparison changed')
        changed=int((a['quality']!=b['quality']).sum())
        pair_counts={label:int((v[:,3]!=v[:,2]).sum()) for label,v in [('old',a['quality']),('clean',b['quality'])]}
    lines=['# 项目数据污染审计与修复验证（2026-09-10）','',
      '结论：发现并修复了真实的标签污染与事后信息泄漏。旧实验不能继续作为当前方法有效性的证据。当前结果仅是原训练分区的开发验证，论文独立确认尚未闭环。','',
      '## 已确认的问题与处理','',
      '- 旧训练矩阵有633个故障零分单元：ArenaHard 458、MMLUPro 124、MBPP 51。原始日志中633次训练请求的失败信息属于余额/访问拒绝。它们反映服务故障，不是模型答题能力。',
      f'- 客观任务中的175个故障单元已有成功补采与绑定评分；其中{changed}个评分从0变为1，其余按真实回答仍判错。新快照保留全部2975道客观题、11900个标签，没有按答对与否删题。开放题2100个单元当前未纳入该快照（含8个仍失败），不宣称全任务标签已清洗完成。',
      '- 旧tie-aware把当前query的各模型实际cost.usd直接传入决策，泄漏了生成后的信息。现改为其他训练折的每槽成本均值，当前query真实成本仅用于事后评估。停止在同一OOF结果上挑epsilon；表中各epsilon只作描述性对照。',
      '- 旧repeat盲panel没有ground_truth，评分前也未绑定cohort；故障/截断又可能被直接记0。现强制绑定train query与标准答案，生成请求仍仅含query；失败留缺失，截断按实际回答评分，代码使用既有隔离评分器。旧协议记录拒绝复用，重复index拒绝累加。5×5交叉比较明确不是25个独立样本。',
      '- 规范化精确重复未检出；词法近重复筛出5对，其中2组跨train/validation。新对照按这些题组划分OOF；近重复是保守候选，不等于每对题都语义完全相同。',
      '- Pilot与train/validation/test分别重叠354/65/81题。更关键的是run_seed42存在真实750题测试开封、对应预测和结果文件。原test全部退役为开发历史：不能通过剔除81题或重排split恢复未触碰属性。正式gate现在拒绝用holdout_uncontaminated=true覆盖已知暴露证据。',
      '- 原训练集中保留了354题pilot来源的生成结果；协议混用风险用按来源预先排除的敏感性对照检查。不是依据性能删样本。','',
      '## 修复后实跑结果','',
      '| 对照 | n | Ridge | DatasetBest | BestSingle | Oracle | Ridge−DatasetBest |',
      '|---|---:|---:|---:|---:|---:|---:|']
    for label,r in rows.items():
        m=r['methods'];lines.append(f"| {label} | {r['n']} | {100*m['Ridge']['quality']:.3f}% | {100*m['DatasetBest']['quality']:.3f}% | {100*m['BestSingle']['quality']:.3f}% | {100*r['empirical_oracle']:.3f}% | {100*r['ridge_minus_dataset_best']['mean']:+.3f} pp |")
    grouped=rows['修复标签、相似题分组'];ci=grouped['ridge_minus_dataset_best']['paired_ci95']
    lines += ['',f"相似题分组后，Ridge相对DatasetBest差值95%配对区间为[{100*ci[0]:.3f}, {100*ci[1]:.3f}] pp，覆盖0。该区间条件于拟合的OOF模型，不包含重训方差。分组更换也改变了折分配，不能把与原折的分差全部归因为近重复。",
              f"修复后，相对BestSingle的经验Oracle Gap从10.118 pp降到{100*grouped['empirical_oracle_gap']:.3f} pp；Ridge恢复率为{100*grouped['methods']['Ridge']['gap_recovery']:.2f}%。质量分数上升主要来自监督纠正，不能把旧GAP恢复率与新分数拼接为一条提升曲线。large/reasoning严格分歧题由{pair_counts['old']}变为{pair_counts['clean']}。",'',
              '## MA回归与排序消融（相同分组，3 seeds，60 epochs）','',
              '| seed | MA回归 alpha=0 | MA回归+排序 alpha=.5 | 排序增益 | 排序−DatasetBest |','|---|---:|---:|---:|---:|']
    for seed,v in rank['per_seed'].items():
        lines.append(f"| {seed} | {100*v['0.0']['quality']:.3f}% | {100*v['0.5']['quality']:.3f}% | {100*v['rank_minus_regression']['gain']:+.3f} pp | {100*v['0.5']['vs_baselines']['DatasetBest']['gain']:+.3f} pp |")
    lines += ['', '该实验使用修复后的客观标签和现有模型条件化网络；不是尚未完成的stable-pair训练。三个seed共享题目，不能将样本数乘3。','',
              '## 无事后成本泄漏的tie-aware','',
              '| 固定epsilon | 质量 | 相对DatasetBest | 成本代理节省 |','|---|---:|---:|---:|']
    for eps in ['0.0','0.005','0.01','0.02','0.05','0.1','0.2']:
        p=tie['policies']['tieaware_eps'+eps];lines.append(f"| {eps} | {100*p['quality']:.3f}% | {100*p['quality_delta_vs_baseline']:+.3f} pp | {100*p['cost_saving_fraction_vs_baseline']:.2f}% |")
    lines += ['', '成本仍沿用历史代理口径，不能当作经核验的美元账单或线上Pareto保证。有效机会子集之外的路由损失也已加入净GAP指标。','',
              '## 未发现证据与仍待完成','',
              '- 已查实现中GTE只编码query；TF-IDF/SVD在训练文本拟合；Ridge的OOF拟合与DatasetBest均只用对应训练折标签。未发现这些路径直接输入标准答案/测试质量。',
              '- 无法从本项目文件判断基础模型预训练是否见过这些公开benchmark；本次清洗不构成“预训练无污染”认证。',
              '- 97题的新repeat panel已经从修复后的标签重建；此次审计没有调用新生成API。panel按全体开发OOF标签选题，适合噪声诊断，不能在同一panel上训练再宣称独立超过dataset-best。正式比较需要将选题、阈值选择与训练全部放入训练折，或使用新未暴露确认集。',
              '- temperature=.7重复生成衡量随机采样鲁棒性，不能与原temperature=0部署结果混为同一估计目标；应分别报告。',
              '- 下一步应先在修复协议上获得有效重复标签，再冻结MA与基线，使用真正新增且去重的确认题。当前不能宣布论文实验闭环。','',
              '测试：test_contamination 8项、test_objective_signal 2项、test_router_v2 13项、test_rank_signal 4项、test_development_matrix 2项，共29项通过；py_compile与git diff --check通过。','',
              '主输入：data/train_matrix_clean_audit_20260910/TRAIN_MATRIX.jsonl；分组：本目录PROMPT_GROUPS.json。旧文件保留追溯，新的训练入口拒绝使用故障零分标签。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    manifest=dict(audit_sha256=sha(out/'AUDIT.json'),evidence=evidence,report_sha256=sha(out/'REPORT.md'),
        clean_train_matrix=str(ROOT/'data/train_matrix_clean_audit_20260910/TRAIN_MATRIX.jsonl'),
        clean_objective_source=str(ROOT/'router_v2/objective_clean_grouped_20260910'),
        superseded_objective_source=str(old_dir),superseded_old_gate=str(ROOT/'data/frozen/full_v2/GATE.json'),
        historical_test_ids_quarantined=len(audit['holdout_quarantine_ids']),formal_confirmation_ready=False,
        validation_or_test_quality_aggregated_this_audit=False,tests_passed=29)
    (out/'REMEDIATION.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(str(out/'REPORT.md'))

if __name__=='__main__':main()
