# Pareto-aware Dynamic Scheduler(轻量多目标策略选择,零新调用)

状态空间:4 故障率 × 8 预算档 = 32 状态;3 折跨种子 CV(2 种子校准 / 1 种子测试);候选池 = 已执行的 {"/".join(POOL)}。

## 全状态网格平均预算内完成率 Q(B) 与平均 tokens

| 策略 | 网格平均 Q(B) | 平均 tokens/题 |
|---|---:|---:|
| random | 0.2385 | 1473 |
| cost_only | 0.4234 | 692 |
| accuracy_only | 0.4234 | 692 |
| fixed_dynamic | 0.1303 | 2234 |
| pareto_selector | 0.4234 | 939 |
| oracle_state | 0.4239 | 1059 |

## 分故障率明细(B=3000 与不限预算)

| 故障率 | Single | fixed-Dynamic | pareto_selector | oracle | selector 选择 |
|---:|---:|---:|---:|---:|---|
| 0% | 0.5500 | 0.3667 | 0.5500 | 0.5500 | router×3 |
| 10% | 0.4972 | 0.3722 | 0.4972 | 0.4972 | router×3 |
| 20% | 0.4389 | 0.3806 | 0.4389 | 0.4389 | router×3 |
| 30% | 0.3639 | 0.3750 | 0.3639 | 0.3806 | router×1/dynamic×2 |


