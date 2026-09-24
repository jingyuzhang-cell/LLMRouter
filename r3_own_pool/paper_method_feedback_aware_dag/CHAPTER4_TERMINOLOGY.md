# 第四章英文术语冻结表

适用范围：当前METHOD.md、EXPERIMENTS.md及CHAPTER4_SUPPLEMENTARY.md的后续英文翻译；历史归档不据此改写。

| 中文术语 | 唯一英文术语 | 符号／定义 |
| --- | --- | --- |
| 质量保持率 | quality-retention ratio | $\rho_{\mathrm{keep}}=1-\mathrm{Degradation}$；clean质量非零 |
| 恢复率 | recovery rate | $\rho_{\mathrm{rec}}$；按对应冻结失败集合定义分母 |
| 预算内正确完成率 | budgeted success rate | $Q(B)$；正确且预算内任务数／全部任务数 |
| 会话非确定性审计 | cross-session output-stability audit | S4.5；映射数、输出差异数、同提示分歧数分别报告 |
| 执行策略空间刻画 | execution-strategy space characterization | 4.2 |
| 策略切换边界 | policy transition boundary | 4.4.3 |
| 独占超体积贡献 | exclusive hypervolume contribution | 移除该策略前后的HV差 |

质量保持率不缩写为单独的retention ratio。英文首次定义后采用以下限定句：

> A quality-retention ratio above one indicates slightly higher average quality under the evaluated fault condition than under the clean reference. This may reflect variability in fault placement and changes in recovery paths; it does not establish an improvement in model capability.

固定任务面板不应被描述为故障场景使用了不同任务集。上述可能解释不作为已经隔离验证的因果结论。

## 标题冻结

- 4.3.2 恢复机制贡献与局部执行效率 / Recovery Mechanism Contributions and Local Execution Efficiency
- 4.4 多目标执行策略权衡 / Multi-objective Execution Strategy Trade-off Analysis
- 4.5 不同任务场景下的适用边界分析 / Applicability Boundaries across Task Settings

定位句：This work characterizes the combinatorial execution strategy space.

不将刻画策略空间表述为求解组合优化或获得全局最优调度器。
