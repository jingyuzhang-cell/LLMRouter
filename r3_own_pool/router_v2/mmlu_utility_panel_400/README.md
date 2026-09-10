# Expected Utility Difference：400题MMLU-Pro实验

采用连续质量差监督，停止hard stable winner筛选。当前是准备与采集阶段，尚无新训练结果。

## 已执行

- 从原train的MMLU-Pro中固定400题，外层训练折分别可用168/168/167题；选题只使用对应训练折标签及内层OOF预测，保留随机覆盖。
- 每模型每题5次，temperature=.7。复用27题、每模型135条有效回答，逐条绑定原始来源并重评分。
- 本地large新增1865条采集中；reasoning新增1865条请求被自动审批拒绝，尚未执行。此前授权范围为113题，本次需要确认扩大的400题外发范围，见EXTERNAL_SCOPE.json。
- 新统计和模型代码6项测试通过；真实不完整数据门禁也已验证。

## 标签与模型

每模型保存成功次数/n、经验均值、单次质量样本方差、样本均值方差、Beta(1,1)后验均值与其方差。5次全对不等于确定的100%正确率；tie照常保留。

目标方向固定为reasoning−large：delta_quality_posterior、delta_total_ktokens、delta_latency_seconds。模型以共享model embedding生成每模型均值，再作差，天然满足Δ(i,j)=−Δ(j,i)。新增方差头拟合均值估计的不确定性；该头不自动等同于已校准的神经网络认知不确定性。

ΔU=ΔQ−λ·Δtoken用量−μ·Δ延迟。token按千token、延迟按秒；token用量不等于经核验的实际金额。资源回归器仅用训练折重复记录拟合，推理不读当前题目的真实资源消耗。

均值模型保留AnchoredMA/SVD64/cap=.1；15epochs、3seed、固定门槛.05。对照为：raw期望差回归、repeat期望差回归、repeat不确定性加权回归、相同预测加不确定性回退。资源权重分别固定(0,0)、(.01,0)、(0,.001)，全部报告，不从外层挑最佳点。

主指标用λ=μ=0的净Gap Recovery，分母仍为原2975题objective范围的DatasetBest→Oracle gap；本轮仅更改MMLU路由决策，不能把分母换成被采样的400题。temperature=.7监督对temperature=0历史结果属于迁移实验。

## 当前执行顺序：P0 → P1 → 有信号再做P2

P0：完成400题 × large/reasoning × 5次；每侧必须同时具有评分、token用量和延迟。失败记录不按质量零分处理，不完整pair不参与拟合。

P1：数据齐全后先运行分布统计和可学习性分析，不直接训练MA：

```bash
python -m router_v2.utility_distributions --panel-dir router_v2/mmlu_utility_panel_400 --data-dir data/mmlu_utility_repeats_400
python -m router_v2.mmlu_learnability --panel-dir router_v2/mmlu_utility_panel_400 --data-dir data/mmlu_utility_repeats_400 --output router_v2/mmlu_learnability_400
```

分析包含经验ΔQ分布、后验区间、前2次/后3次重复一致性、随机基线、任务常数、学科均值及GTE Ridge。当前400题均为knowledge任务，任务常数与学科基线分别报告。5次二元评分使经验ΔQ以0.2递增；观测tie不代表真实期望相等。学科内打乱标签作为额外对照。

P1入口检查400个完整pair及文件来源。主要开发筛选条件为GTE Ridge1相对学科基线的MSE改善区间下界大于零，且真实MSE优于20组学科内置换对照的第5百分位。这不是独立确认性检验，也不从结果选择新的最优门槛。

P2：仅当P1显示信号，再评估MA。expected_utility_ma入口现在必须提供通过筛选且数据哈希匹配的 --learnability-report；本轮没有启动MA训练。未来模型统计特征仅从训练折估计，不能读取当前题目生成后的质量/资源消耗。large与reasoning均约14B，单独model_size不能区分它们；历史统计与模型身份需单独消融。

当前原test已全部开封；本实验仍是train-only开发验证，不能据此承诺20%–30%或独立论文确认。全任务clean matrix还剩1个历史开放题生成缺失，与当前MMLU采样分开记录。

用户已明确授权新增1865次reasoning生成及费用，采集已启动。run_p1_when_ready.py只监控现有采集任务，完成后自动生成分布并执行P1；不发送API请求、不启动MA。进度见P1_PIPELINE_STATUS.json，日志见P1_PIPELINE.log。

### 三项P1实验补充
ΔQ回归保留全部tie，以MSE/MAE/R²/Spearman为主；辅助AUC仅在观测ΔQ非零的样本上计算，用连续预测差作为score，单一方向时返回null。AUC=0.65/0.75不作为证明或调参门槛。Shuffle含20组全局、20组学科内训练标签置换，评估折标签不变，同时报告MSE/Spearman/AUC。学科内置换保留学科信号，其相关性不要求为零。新增指标边界测试后共6项通过。采集结束后后台流程将使用此版本运行。
