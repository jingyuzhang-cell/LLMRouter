# C7.1 Signal Sufficiency Audit：专家结论

## 核心结论

当前 419 题上的通用 task-only Router 信号总体不足，但跨重复稳定 headroom 明确存在。合理动作不是继续调当前 Router，也不是先改善重复次数，而是按输入能力结构采集新的开发数据，并在新的 support-matched validation 上预注册 capability-aware predictor。

## 数量级判断

- 全局 OOF Quality MAE：0.24199。
- top1–top2 真实平均质量 margin：中位数 0，均值 0.07576。
- 只有 9.07% 的任务 margin 大于预测 MAE。
- 77.33% 的任务 margin-to-repeat-noise SNR 小于 1。
- 三次重复 winner 完全一致率：69.21%。
- 跨重复可复现 Oracle gap：0.05454，95% CI 为 [0.03430, 0.07557]。
- 噪声诱导的额外 Oracle gap：0.03244。

这说明预测误差确实淹没了绝大多数任务的模型差距；但稳定 gap 显著大于预设的 0.02 门槛，不能据此宣布 task routing 没有价值。

## 模型层诊断

Gemini 的绝对质量最难预测（MAE 0.32212，Spearman 0.24219），Qwen-plus 的绝对 MAE 最低（0.20648），但其预测分布标准差只有 0.04090，明显低于真实标准差 0.27828，存在强烈的回归到均值。

相对 Qwen-plus 的优势预测中，只有 Gemini 同时达到预注册标准（AUC 0.68966、Spearman 0.29096）。但 Gemini 真正胜过 Qwen-plus 的任务仅占 4.30%，这是一个稀有能力边界，不能在当前数据上继续调分类阈值。

DeepSeek、GLM 和 Qwen-turbo 的 sign accuracy 看似达到 73%–79%，主要受“通常不胜过 Qwen-plus”的类别不平衡影响；其 AUC 均低于 0.5，不能视为具备可用的切换识别能力。

## 下一步约束

1. 采用输入结构预先分层采样，覆盖 numerical、table、long-context、evidence synthesis、compliance、multi-hop、extraction 和 ambiguity handling。
2. 不得根据已有模型 winner 挑题；能力层在调用候选模型前确定。
3. 增加少数但关键的能力边界覆盖，尤其是可能产生 Gemini/Qwen-plus 稳定反转的长上下文与证据综合任务。
4. 新数据必须划分 development train、support-matched validation 和未触碰的 v4 confirmatory；当前 419 题只用于设计与诊断。
5. 在新 validation 上固定比较 absolute performance predictor 与 capability-aware predictor。只有后者产生可靠的 Utility 增益且不增加失败率，才进入多目标 Selector 和 DAG fallback。
