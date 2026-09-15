# Fresh Static DAG Confirmation

用户已批准使用审计后未参与开发的MultiHiertt train独立holdout，100题。官方test仅有question、没有answer/program，因此未使用它。

已排除工作区记录中的UID和已用问题文本；原始审计覆盖r3_own_pool与phase_c9_0，不能证明预训练或未知工作区从未见过。前述边界不会通过更换split名称抹去。

## 冻结与执行

- DEV_MODELS.npz / DEV_FROZEN.json：仅dev重建最终Ridge；精确复现原3-fold CV质量、utility及选择计数。
- PROTOCOL.json / TASKS.json / NODES.json / CALLS.json：100题，497评分节点；每模型404次调用，三个模型共1212次，无重试。
- PREDICTIONS_FROZEN.json / PREDICTIONS.json：原GTE、原特征、原utility下，先封存所有Query/Node/Static选择，再生成回答。
- ANALYSIS_PLAN.json：F1–F3、task-cluster bootstrap、主类型及Transformation探索性口径。
- RESULTS.json / REPORT.md / VALIDATION.json：采集完毕后按冻结规则生成并独立审计。STATUS.json提供真实状态。

## 解释边界

这里确认的是conditional node-table routing。Reasoning沿用gold facts，Verification沿用gold/perturbed输入；它不是端到端DAG执行质量。Static Capability保持旧实现的全局均值；Node Router特征保持问题GTE、type one-hot和log1p问题字符长度。

主报quality recovery；旧46.2%为utility recovery，不直接比较数值。Extraction共享响应按方法去重计算tokens/调用成本；延迟报告实际请求服务时长，不能冒充真实端到端DAG latency。本地GPU货币账单未建立。

不按结果调参，不增加R1，不启动Feedback/Dynamic DAG/Graph Forest，不推GitHub。
