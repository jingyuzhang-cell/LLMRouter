# Feedback Schema V1 — 字段定义词典（2026-10-31，零调用）

---

## 设计原则

1. **质量/可靠性/成本/时延四维彻底分离**，不允许混为一个"成功奖励"
2. **INCOMPLETE ≠ Q=0**：无报告时不评分（NOT_SCORABLE），不自动赋零
3. **故障双维度**：fault_layer（位置）× persistence（持续特征），正交非互斥
4. **归因不可只存数字**：必须附 comparison_id、method、evidence_status、uncertainty
5. **决策必须保存完整状态快照**，否则事后无法判断决策是否合理
6. **预测误差是学习信号**，expected vs actual 的差异必须记录
7. **485 次调用 ≠ 485 个独立样本**：归因以任务×条件×配对执行为单位

---

## 一、run_context

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| task_id | string | ✓ | 任务唯一标识 |
| experiment_id | string | — | 实验批次标识（如 H1_V2_FINAL） |
| rep_id | string | — | 重复编号（r1/r2/…） |
| group_id | string | — | 配对组标识（如 G5_Z_R_pilock） |
| dag_snapshot | object | ✓ | 完整 DAG 状态 |
| dag_snapshot.dag_version | integer | — | DAG 版本号（结构变更后递增） |
| dag_snapshot.nodes | array | ✓ | 节点列表（含 id/kind/subtask/model/status） |
| dag_snapshot.edges | array | ✓ | 依赖边列表 |
| initial_pi | object | ✓ | 初始模型分配 |
| initial_pi.allocation_rule | string | — | 分配规则名（如 Q_min=0.70 cheapest） |
| initial_pi.per_node | object | — | {node_id → model_id} 映射 |
| anomaly | object | ✓ | 注入或发生的异常 |
| anomaly.node_id | string | ✓ | 异常发生的节点 |
| anomaly.fault_layer | enum | ✓ | merge_interface / node_logic / runtime / transport / none / unknown |
| anomaly.persistence | enum | ✓ | transient / persistent / unknown / none |
| anomaly.injected | boolean | — | 是否为实验注入 |
| anomaly.inherited_by_splits | boolean | — | 拆分后子节点是否继承故障 |
| budget | object | — | 预算状态 |
| budget.total_tokens | number | — | 总 token 上限 |
| budget.remaining_at_start | number | — | Run 开始时剩余 token |
| budget.deadline_s | number | — | 截止时间（秒） |
| model_pool | array | — | 可用模型列表 |
| reference_set | object | — | 评分参考信息 |

## 二、scheduling_actions（数组）

每个 Z/R/π 决策一条记录。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| action_id | string | — | 决策唯一标识 |
| timestamp_s | number | — | 决策时间 |
| dimension | enum | ✓ | Z / R / pi / none |
| action | string | ✓ | 动作名（SPLIT_VERIFY / retry / switch_model / keep / …） |
| action_detail | string | — | 动作详情 |
| state_snapshot | object | ✓ | **决策时完整状态快照** |
| state_snapshot.dag_version | integer | — | 当前 DAG 版本 |
| state_snapshot.completed_nodes | array | — | 已完成节点列表 |
| state_snapshot.pending_nodes | array | — | 待执行节点列表 |
| state_snapshot.failed_nodes | array | — | 失败节点列表 |
| state_snapshot.faulted_nodes | array | — | 异常节点列表 |
| state_snapshot.current_pi | object | — | 当前模型分配 |
| state_snapshot.capability_gaps | object | — | {node_type → Q_gap} |
| state_snapshot.budget_remaining | number | — | 剩余预算 |
| state_snapshot.deadline_remaining_s | number | — | 剩余截止时间 |
| state_snapshot.feasible_z_candidates | array | — | 当前可用的 Z 候选 |
| state_snapshot.feasible_r_candidates | array | — | 当前可用的 R 候选 |
| state_snapshot.feasible_pi_candidates | array | — | 当前可用的 π 候选 |
| decision_rationale | string | — | 决策依据文本 |
| expected_outcome | object | — | 预期结果 |
| expected_outcome.expected_quality_change | number/null | — | 预期质量变化 |
| expected_outcome.expected_cost_change | number/null | — | 预期成本变化 |

## 三、execution_results

### 3a. per_node（数组）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| node_id | string | ✓ | 节点标识 |
| model | string | ✓ | 执行模型 |
| execution_status | enum | ✓ | success / failed / blocked / replaced / not_executed |
| failure_type | enum/null | — | contract / parse / transport / timeout / cascade / injected / null |
| attempt_number | integer | — | 第几次尝试 |
| tokens_in | number | — | 输入 token |
| tokens_out | number | — | 输出 token |
| latency_s | number | — | 执行耗时 |
| quality_signal | number/string/null | — | 节点级质量信号（如事实覆盖率） |
| quality_signal_type | enum/null | — | fact_coverage / parse_success / null |

### 3b. terminal

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| execution_status | enum | ✓ | COMPLETE / INCOMPLETE_NO_RECOVERY / INCOMPLETE_RECOVERY_EXHAUSTED / INCOMPLETE_BUDGET / INCOMPLETE_DEADLINE / INCOMPLETE_OTHER |
| quality_status | enum | ✓ | SCORED / NOT_SCORABLE / PENDING |
| Q_terminal | number/null | ✓ | 终端质量得分（NOT_SCORABLE 时为 null） |
| Q_reference_type | enum | — | GOLD_CONFIRMED / SILVER / AI_ADJUDICATED / UNKNOWN |
| Q_scoring_formula | string | — | 评分公式标识 |
| Q_sample_n | integer | — | 评分事实数 |
| key_fact_results | array | — | 关键事实结果列表 |
| report_generated | boolean | — | 是否生成了报告 |
| reliability_status | enum | — | RELIABLE / FAILED / DEGRADED |

**关键设计**：
- `execution_status = INCOMPLETE` 时 `Q_terminal = null`，`quality_status = NOT_SCORABLE`
- `reliability_status` 独立于 `execution_status`（COMPLETE 也可能 DEGRADED）
- `report_generated = true` 不等于 `quality_status = SCORED`

## 四、cost_latency

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| total_tokens | number | ✓ | 总 token 消耗 |
| per_model_tokens | object | — | {model_id → tokens} |
| total_calls | integer | — | 总调用次数 |
| per_model_calls | object | — | {model_id → calls} |
| cash_cost_cny | number | — | 现金成本（¥） |
| makespan_s | number | ✓ | 端到端时延 |
| within_budget | boolean | — | 是否在预算内 |
| within_deadline | boolean | — | 是否在截止期内 |
| wasted_tokens | number | — | 浪费 token（失败/替换节点的消耗） |

## 五、attribution（数组）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| action_dimension | enum | ✓ | Z / R / pi / Z_R_interaction / Z_pi_interaction / R_pi_interaction / joint |
| effect_estimate | number/null | — | 效应估计值（可为 null） |
| effect_unit | enum | — | delta_Q / delta_tokens / delta_makespan_s / completion_rate_delta / null |
| comparison_id | string | ✓ | 配对比较标识（如 H1_SC_E1_G5_vs_G2） |
| attribution_method | enum | ✓ | paired_comparison / ablation / observational / none |
| evidence_status | enum | ✓ | PRELIMINARY / REPLICATED / CONTRADICTED / INSUFFICIENT_DATA |
| uncertainty | enum | — | LOW_N / SINGLE_CELL / CROSS_SCORING / NONE |
| notes | string | — | 备注 |

**关键设计**：
- `effect_estimate` 可为 null（数据不足时不猜测）
- `evidence_status = PRELIMINARY` 表示单 cell 或未重复
- `uncertainty = CROSS_SCORING` 表示两组使用了不同评分口径
- 交互效应有独立的 dimension 值（Z_R_interaction 等）

## 六、prediction_errors（数组）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| what_was_predicted | string | — | 预测内容描述 |
| expected_value | number/string/null | — | 预期值 |
| actual_value | number/string/null | — | 实际值 |
| error_magnitude | number/null | — | 误差大小 |
| lesson | string | — | 教训/学习信号 |

**用途**：记录调度器的预测与实际结果的差异，作为策略更新的输入。

---

## 缺失值规则

| 场景 | 正确值 | 错误值 |
|---|---|---|
| 未执行节点 | execution_status = "not_executed" | 不要写 "failed" |
| 未评分终端 | Q_terminal = null, quality_status = "NOT_SCORABLE" | 不要写 0 |
| 无法归因 | effect_estimate = null | 不要写 0 或猜测值 |
| 无异常 | anomaly.fault_layer = "none" | 不要省略 anomaly 字段 |
| 历史数据缺失 | 保留缺失 + notes 记录原因 | 不要事后补充推测值 |
