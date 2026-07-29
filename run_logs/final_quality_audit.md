# 最终质量审计

- 总体门禁：通过
- 实验签名：`13ba763720ca0c4211d1e278bfc0f84e9c171d44d19217f221b490d0c4e2d6a5`
- 最终成功结果：1200/1200
- 历史失败尝试：1745；涉及 1131 个调用；最终恢复率 100.00%
- 模型分布：{'deepseek-chat': 300, 'qwen-plus': 300, 'qwen-turbo': 300, 'glm-5.2': 300}

## API 审计

- 错误类型：{'All connection attempts failed': 1740, 'Server disconnected without sending a response.': 3, 'unknown': 1, 'peer closed connection without sending complete message body (incomplete chunked read)': 1}
- 失败模型分布：{'glm-5.2': 439, 'deepseek-chat': 434, 'qwen-plus': 437, 'qwen-turbo': 435}
- 单调用尝试次数分布：{1: 69, 2: 517, 3: 614}；最大 3 次
- 最终未恢复调用：0

## Judge 审计

- GLM Judge 解析：3/601 (0.50%)
- 触发 fallback：602/1200 (50.17%)
- 最终双有效 Judge 覆盖：1198/1200 (99.83%)
- 结论：GLM 不得表述为有效评分贡献者；最终覆盖由 fallback Judge 保持。

## 异常分数

- 零质量分：136
- 满质量分：300
- Judge 分歧 ≥ 0.20：425
- 标记人工复核：402
- 具体任务 ID 和统计值见 JSON；未复制原始回答。

## 调用均衡与异常值

- 四模型各 300 条：True
- 全局延迟 P50/P95/P99/最大值：3360.3/11922.5/16798.0/38660.6 ms
- 全局成本 P50/P95/P99/最大值：0.000196/0.003526/0.004114/0.004418 USD

## 三重复方差

- 任务-模型组：400；全部含 3 次重复：True
- 质量标准差 ≥ 0.20：41 组
- 延迟 CV ≥ 0.50：10 组
- 成本 CV ≥ 0.50：0 组
- 各类最高波动 20 组见 JSON。

## Objective 评分器漂移

- 后验评分器版本：dataset-aware-objective-v2.2
- 会改变的记录：32/1200（上调 23，下调 9）
- 已应用至独立重评分结果：True
- 需要离线重算策略指标与显著性：False

## 门禁与限制

- experiment_completed_1200_of_1200: True
- result_has_1200_unique_successes: True
- all_failed_calls_recovered: True
- balanced_model_calls: True
- complete_three_repeat_groups: True
- dual_judge_coverage_at_least_99_percent: True
- glm_judge_limitation_disclosed: True
- objective_scorer_drift_resolved: True

### 必须披露

- GLM judge parsing succeeded for only 3/601 attempts; fallback judges, not GLM, supplied valid replacement scores.
- Equivalent routing baselines identified in final_paper_analysis must not be interpreted as independent evidence.
- Zero/full scores and high-variance groups listed here require paper caveats or targeted manual review; raw response text remains excluded.
- Objective scorer dataset-aware-objective-v2.2 changes 32/1200 records; strategy metrics and significance must be recomputed before paper claims are final.
