# V5 VS RL 逐决策审计

日期：2026-10-22。**这是合成零API验收，不是确认性模型收益实验。** 两臂获得同一状态、检测反馈、模型候选、能力单元、预算、截止期和计量回调；没有任何真实模型响应或反事实Q被补造。唯一含终端质量数值的第10项使用明确标为SYNTHETIC_TEST_REFERENCE的夹具，其余质量不可识别。

V5按联合候选Pareto及冻结加权规则选择；RL先按规则选择恢复范围、再逐节点选低Token模型，若不满足约束则尝试低时延模型。RL不读取V5最终选择，同样应用完整硬约束，允许缓存复用与合法闭包。两臂均需支付实际测得的本地决策耗时；不能把零付费测试中的虚拟时延当真实网络时延。

| 状态 | V5 Z / R / π | RL Z / R / π | V5执行 / RL执行 | 动作相同 |
| --- | --- | --- | --- | --- |
| healthy_independent_cache | LOCAL / a,out / a→fast,out→fast | LOCAL / a,out / a→cheap,out→cheap | COMPLETE / COMPLETE | 否 |
| evidenced_cache_suspicion_quality_unknown | LOCAL / a,out / a→fast,out→fast | EXPAND / a,b,out / a→cheap,b→cheap,out→cheap | COMPLETE / COMPLETE | 否 |
| independent_cache_fingerprint_invalid | LOCAL / a,b,out / a→fast,b→fast,out→fast | LOCAL / a,b,out / a→cheap,b→cheap,out→cheap | COMPLETE / COMPLETE | 否 |
| fast_model_unavailable | LOCAL / a,out / a→cheap,out→cheap | LOCAL / a,out / a→cheap,out→cheap | COMPLETE / COMPLETE | 是 |
| token_budget20 | LOCAL / a,out / a→cheap,out→cheap | LOCAL / a,out / a→cheap,out→cheap | COMPLETE / COMPLETE | 是 |
| deadline2 | LOCAL / a,out / a→fast,out→fast | LOCAL / a,out / a→fast,out→fast | REFUSED_AFTER_PLANNING / REFUSED_AFTER_PLANNING | 是 |
| insufficient_budget_refuse | REFUSE | REFUSE | REFUSED / REFUSED | 是 |
| unknown_terminal_quality_refuse | REFUSE | REFUSE | REFUSED / REFUSED | 是 |
| supported_annotation_only | VERIFY /  / verify_b→fast | VERIFY /  / verify_b→cheap | VERIFIED_ANNOTATION / VERIFIED_ANNOTATION | 否 |
| synthetic_terminal_calibration_only | EXPAND / a,b,out / a→fast,b→fast,out→fast | EXPAND / a,b,out / a→cheap,b→cheap,out→cheap | COMPLETE / COMPLETE | 否 |

## 逐状态解释与复现范围

- 缓存健康时两者都选择最小合法闭包；不同π来自冻结目标差异，不能据此称为新恢复范围能力。
- 有独立分支接地异常但终端质量未知时，V5没有凭空给扩大集合质量奖励；RL的严重异常规则可选择EXPAND。这是规则差异，不能据此判断哪一个真实终端质量更高。
- 输入指纹失效时两者均必须恢复相应分支；这不是V5独有能力。模型不可用、预算紧张时两者会收敛到同一可行π，预算/终端质量下限不可满足时均拒绝。
- `deadline2`的名义模型时延恰好用满2秒。注入式执行器扣除实测规划开销后再次检查，因此可能在发送前`REFUSED_AFTER_PLANNING`。不隐去该拒绝，不将“预测候选可行”当作“实际按时完成”。
- VERIFY只产出注解，健康缓存保留；核验输出不是自动确认性Gold，不据此加质量分。
- 最后一项是明确声明的合成任务质量映射，检验联合排序可以选择不同范围，不是独立校准数据，不可用来报告V5真实ΔQ。

[完整JSON](v5_migration_20261022/V5_VS_RL_DECISIONS.json)记录全部候选预测、拒绝原因和每臂实际注入式轨迹，包括选定动作的实际结果、输入指纹、虚拟Token/时延及本地规划耗时。未执行候选实际结果保持null。夹具终端算术检查只核验该合成执行流程；不外推真实舆情质量。

## 确定性与公平性

每个冻结状态重复调用两次选择器，V5与RL共20个逐策略检查均选择一致。运行耗时会随机器负载变化，不承诺墙钟字节级一致。选择器输入不含实测后的终端答案；夹具参考只在执行后评价。

可复现入口：`python /root/capital_opinion_pilot/v5_migration_20261022/build_decision_audit.py`。该入口仅调用注入式算术回调，不创建模型客户端；输出位于本轮开发目录，不覆盖历史实验。

**当前只能确认决策机制存在差异且受共同约束，不能确认V5优于强规则RL。** 独立真实增量仍要求同状态配对、可信终端参考、真实完整成本和截止期记录及专项授权。本轮到此停止。
