# 独立下游节点校准：真实批次结果

**CLOSED：8/8请求完成，无重试、补跑。校准完成；Static/Dynamic配对未启动，算法收益未评价。**

| 节点 | Qwen合同 | Qwen请求耗时(s) | DeepSeek合同 | DeepSeek请求耗时(s) |
|---|---|---:|---|---:|
| timeline_1 | MODEL_FAILURE | 5.469 | CONTRACT_COMMITTED | 2.696 |
| relations_1 | MODEL_FAILURE | 25.035 | CONTRACT_COMMITTED | 3.048 |
| verify_1 | MODEL_FAILURE | 44.555 | CONTRACT_COMMITTED | 3.650 |
| report_1 | CONTRACT_COMMITTED | 12.054 | CONTRACT_COMMITTED | 4.252 |

## 实际计量

- qwen-plus-2025-12-01：4请求，合同通过1/4；输入10119、输出3854 Token；请求耗时累计87.114秒；估费人民币0.015804、美元0.000000。
- deepseek-flash：4请求，合同通过4/4；输入9601、输出2776 Token；请求耗时累计13.646秒；估费人民币0.000000、美元0.006213。

总Token 26,350；公开牌价估费¥0.015804和$0.006213，分别低于¥0.20/$0.10程序停止阈值。实际账户结算UNKNOWN。耗时是各独立请求实测墙钟，累计值不是并行DAG Makespan或完整任务时延。

## 失败归因（原始成绩不改判）

- Qwen时间线：一个JSON对象后又附加代码块，严格单JSON解析失败。没有解包、删代码块或自动修补。
- Qwen关系：顶层除findings外还返回node_id，违反冻结合同。
- Qwen核验：顶层除findings外还返回status，违反冻结合同。
- Qwen报告及DeepSeek四节点通过既有结构与引用链检查；这不证明内容语义正确。三个失败也不等于事实内容错误。

## 已解决与未证明

- 已真实验证：普通模型合同失败后，其他固定输入单元仍继续执行。此前Qwen四类下游缺测现在都有实际请求耗时、usage与输出记录。
- Qwen报告节点与DeepSeek报告节点均有合法提交；其他三类Qwen只有失败观测，不能把失败耗时当作合法完成时间。
- 这一输入和提示下，DeepSeek四类请求都更快且合同通过；每格仅一个样本，不能估计0.95可靠性或外推总体优势。人民币与美元未换算，不直接断言现金谁更便宜。
- 使用历史DeepSeek生成的固定上游输入，存在生成模型风格偏差；不是独立任务，也不是完整上游鲁棒性检验。
- 语义Q全部UNKNOWN。不能声称完整终端质量提高、Pareto改善或Dynamic-π有净收益。
- 本次新提示不与旧提示混合当作同条件配对，不自动导入冻结调度器，不自动更换任务或追加调用。

原始请求/响应/计账在requests/，完整输出在CELL_*.json，机器汇总在ANALYSIS.json。冻结代码、配置、输入及历史来源哈希未变，RUN_ONCE.lock保留。所有8次额度已使用，授权结案。
