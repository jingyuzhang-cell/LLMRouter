# Schema Validation Report（2026-10-31，零调用）

## 验证结果：7/7 PASS

| # | 检查项 | 结果 | 详情 |
|---|---|---|---|
| 1 | JSON 语法有效性 | ✓ | 7 个顶层字段，标准 JSON Schema Draft-07 结构 |
| 2 | 必填字段完整性 | ✓ | run_context + execution_results + cost_latency + schema_version |
| 3 | 质量/可靠性分离 | ✓ | Q_terminal(nullable) + quality_status + reliability_status 三字段独立 |
| 4 | 故障双维度 | ✓ | fault_layer(6值枚举) × persistence(4值枚举)，正交设计 |
| 5 | 归因元数据 | ✓ | comparison_id + attribution_method + evidence_status + uncertainty 四字段必填 |
| 6 | 决策状态快照 | ✓ | 13 个字段涵盖 DAG/节点/模型/预算/截止期/候选动作 |
| 7 | 预测误差追踪 | ✓ | prediction_errors 数组含 expected/actual/error_magnitude/lesson |

## 模块兼容性

| 模块 | 支持字段 | 状态 |
|---|---|---|
| M1 模型画像 | per_node.quality_signal + per_node.model | ✓ |
| M2 DAG 生成 | dag_snapshot（含版本号追踪） | ✓ |
| M4 静态调度 | initial_pi + reference_set | ✓ |
| M5 动态调度 | scheduling_actions（Z/R/π 三维度 + 状态快照） | ✓ |
| M6 反馈学习 | attribution + prediction_errors | ✓ |
| M7 多目标优化 | Q/C/L 独立记录 + within_budget/deadline | ✓ |

## 边界案例处理

| 案例 | Schema 处理 | 是否正确 |
|---|---|---|
| INCOMPLETE run | Q_terminal=null, quality_status=NOT_SCORABLE | ✓ 不自动赋零 |
| 无异常 | fault_layer=none, persistence=none | ✓ 不省略字段 |
| 被替换节点 | execution_status=replaced | ✓ 区别于 failed |
| 模型切换未发生 | state_snapshot.capability_gaps 记录差距 | ✓ 可事后判断 |
| 跨口径比较 | uncertainty=CROSS_SCORING | ✓ 标记不隐藏 |
| 单 cell 归因 | evidence_status=PRELIMINARY | ✓ 标记可信度 |
| 交互效应 | action_dimension 含 *_interaction | ✓ 独立维度 |
