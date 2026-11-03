# 质量计算与下游用途审计

结果：**乘法和加总正确；14.472是历史代理下的期望事实数，不是节点准确率或终端任务质量。来源追溯完整性仍为PARTIAL，不升级为独立质量校准。**

| 项 | 源码输入与声明来源 | 单位 | 核验值 |
| --- | --- | --- | --- |
| t2重执行 | grounding=0.964，n=28，`f7v2 saved`；facts_per_call=15为计划显式输入；survival=0.70，n=10，`RF2-signal trace` | 无量纲接地率×事实数×无量纲存活率 | 10.122 |
| t1保留 | 已接地15/22个缓存事实，模型glm53；survival=0.29，n=7，`RF2-signal trace` | 已接地事实数×无量纲存活率 | 4.350 |
| 合计 | t1项+t2项 | 期望链式事实数 | 14.472 |

`0.964×15×0.70=14.47`单独作为等式不成立。现有代码实际计算`4.35+10.122`；旧解释漏写缓存项，已有历史[S6更正报告](../S6_V5_DECISION_GATE.md)说明。本轮使用Decimal独立核对算术，再核对TaskQuality实际返回值与下游候选字段，保留浮点返回值的表示误差。

t1的15已经是接地事实数，不能再无依据乘一次接地率。t2的15是调用者传入的事实数假设，不是本轮新观测的真实输出数量。0.964等常数经过舍入，样本数和来源字符串已记录；本轮没有重新判读历史响应、签署Gold或验证可迁移的预测概率。

代码数据出处是[task_quality.py](../task_quality.py)中的`measured_cells`及计划输入，逐观察的原始响应/证据位置没有在Cell中完全标出，因此来源可追溯性为PARTIAL。不能把这些字符串引用当作独立终端参考，也不能把总数除以任意15、22或37当准确率；跨节点重复事实与终端必要项集合未经确认。

下游核验：TaskQuality返回14.472及`historical_chained_fact_proxy`；正式V5候选的`diagnostic_q_proxy`保留该值，`q_task=null`、`terminal_q=null`、`terminal_q_identified=false`、`quality_term_used=false`。终端质量约束存在而缺独立校准时拒绝。未校准事件、遗漏必要质量单元和缺参数传播为未知，不补零或扩大范围奖励。

原V5研究兼容测试中的`allow_proxy_objective=True`只用于原逻辑回归；正式执行器强制关闭，不能将测试日志里的“Q̂”写成研究收益。完整分项和下游输出见[JSON审计](QUALITY_CALCULATION_AUDIT.json)。
