# 多目标 Router 主线审查与已执行修复

主线保持：学习 query–model 匹配，预测质量并结合请求时可用资源信息作多目标路由。多目标没有脱离偏好/约束的唯一最优解；有限权重网格仅覆盖候选策略，不能称已求得完整 Pareto 前沿或全局最优。

## 首要问题

训练、部署决策与验证协议没有闭环。419-query 开发诊断显示质量 Oracle 0.880707、Best Single 0.802866；Ridge 相对 Zero 的 AIQ 增益区间跨零（来源 ../router_decision_diagnostics/REPORT.md）。这是旧五模型开发证据，不能外推为当前四模型效果。当前 R3 设计、旧训练器与 FULL_V2_EXECUTION_PROTOCOL.md 的 split/资源预测定义冲突，先解决有效性才有可解释的 gap recovery。

## 本次实际执行

- 修复预测未 eval 导致 Dropout 随机路由；恢复原训练状态，质量输出裁剪至合法范围。
- 修复 Hybrid 结果 pop 键名错误（此前会 KeyError）；资源尺度允许零成本。
- GRR 使用未舍入质量，分母非正返回 null；每组权重另报 profile-utility 的 train-selected Best Single、Oracle gap、GRR、配对 bootstrap 区间与路由分布。
- 同一 Pareto 图固定模型成本改为测试实际均值，与 Router 实际成本口径一致；静态训练 profile 仍只用于决策。
- 保存逐 query 的预测与结果，便于审计。测试筛选的同质量点明确降级为描述性结果，不能作已验证省钱结论。
- 旧 train_router.py 限于 pilot：禁止它按旧 split 自动打开 full 测试集。未修改/终止当前采集进程，未消费真实 holdout。
- CPU 合成端到端测试覆盖24个权重、输出落盘、零成本、稳定推理和旧全量入口拒绝；未训练真实数据，不构成效果提升证明。

## 如何学习 gap：下一阶段执行规格

1. 按新版 3500/750/750 query 分组及哈希冻结，训练内生成监督；20000条模型响应不是20000个独立样本。完成评分、失败记录与成本口径门禁后才训练。
2. 保留 Qhat(q,m) 的校准回归，学习同题模型间质量差；rank 应按每题有效 pair 数归一化，tie 不强造 winner。质量 tie 的节省由请求时预测资源/冻结profile决定。加入 rank 不等于已证明更好。
3. 共用特征与 split 比较回归、回归+ranking、去掉model embedding。alpha 只在 validation 选；报告质量优先和预先固定多目标偏好，避免仅按质量挑参数却声称三目标训练。
4. 新版要求资源预测，与旧静态profile方案分开报告；纯 ranking score 不直接减美元/毫秒。部署选择不得读测试真实 Q/C/L。
5. 固定偏好 w 下，比较 Urouter、训练选出的最佳固定模型/验证选出的固定混合策略及同定义 Oracle。GRR=(Urouter−Ubaseline)/(Uoracle−Ubaseline)，同时报告绝对差及区间；小/非正分母不夸大比率。静态profile Oracle与真实逐请求资源Oracle必须区别。
6. 对质量约束 Q>=Qbaseline−δ，在 validation 选择成本/延迟折中点，δ先定；test一次评估质量非劣与资源节省。不能用test找省钱点再报成功。λ/μ sweep不能替代约束保证。
7. 重复采样检验胜负稳定性，学习曲线检验增加训练数据是否恢复更多 gap；新增表达能力前先排查监督噪声和条件预测信号。所有新方法仍服务于 Router，不转向非路由论文。

## 尚未完成的工作

新版正式训练入口、资源预测、公平基线补齐、validation操作点选择及独立测试尚未执行；当前采集/评分与成本门禁未在本次审查中认证完成。旧流水线无失败即停止，且其full_v1路径与v2冲突，应迁移后再启动正式训练；本次限制旧训练入口是防止误评估，不代表全量流水线已经就绪。bootstrap仅条件于当前模型、不包含重训波动；现有代码的task-holdout超参来自含knowledge的验证集，因此不能声称严格未见域选择。未来正式入口须独立处理。

## 继续执行更新：v2离线实验入口已实现

上文“新版入口尚未实现”的状态由此更新取代。新增 `router_v2/`，包含原split冻结、训练内资源预测、Hybrid/去model表示/回归/排序等对照、逐偏好validation选alpha、严格质量和延迟约束下选成本操作点、独立test评估及hash封存。参见 `router_v2/README.md`。20项回归测试通过（`router_v2/VALIDATION.md`），并以扰动合成test标签和资源的方式验证训练/选择不依赖test结果。

旧全量freeze现会拒绝重建80/20划分，旧机会分析仅开发分区、可靠性审计仅train；未停止采集。正式全量训练和性能结论仍未执行：完整响应、评分/计费/隔离与holdout历史门禁未通过；GTE全量嵌入、Transformer基线、跨seed汇总和部署服务仍未完成。现有新入口是可测试的离线实验实现，不代表全量正式流水线或论文结果已经完成。
