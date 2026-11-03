# PLANNER_V1_REPORT — 真实 LLM Planner 接入验证（2026-10-28，已完成）

> 授权执行：12 次真实请求（上限 18）/ 增量现金 **¥0.00**（GLM-Flash 订阅，
> 冻结费率经准入核验）/ 墙钟 141s / 零重试 / 未启动端到端执行。
> 全部 12 份原始响应已保存（含 1 份非法 DAG），无选择性保留。

## 1. 规划成功率

| 指标 | 结果 |
|---|---|
| 解析成功率 | **12/12**（全部输出可解析为 DAGSpec） |
| 合法性通过 | **11/12**（A_r2 被合同检查器捕获：n7 requires 'penalty_items' not produced upstream） |
| 孤立节点 | **0**（11 份合法图全部节点可达汇点） |
| 证据绑定 | 全部绑定索引内 doc_id，**零虚构来源**；A/C→jsst，B/D→两份泽达文书（与问题匹配） |

## 2. 任务驱动的结构分化（核心验证点）

四类问题 × 3 独立规划 = 12 份图。**跨类结构零重叠**（12 份 distinct，
无任何一份的角色多重集出现在另一类中）；类内 3 份也互不相同（规划多样性）：

| 类 | 典型结构（角色×数） | 节点数 | 业务差异体现 |
|---|---|---|---|
| A 信息披露变化 | extract + timeline + amounts×2 + penalties + amounts_check + merge/timeline_deep + synthesis | 6-8 | 双金额通道（事实+复核）做跨年对比 |
| B 调查至处罚 | extract×2 + timeline + entity + penalties + amounts + cross_check + synthesis | 8-9 | 双文档抽取+交叉核验 |
| C 并购关联交易 | extract + entity_graph×2 + amounts + cross_check + synthesis | 6-8 | 主体关系为主链 |
| D 重大事件全景 | extract×2 + merge + timeline_deep×2 + amounts×2 + entity + penalties + cross_check + synthesis | 8-10 | 最宽覆盖、双 merge/复核 |

Planner 未套模板：节点数随任务需求 6-10 变化；D 类未生成行情分支——
证据索引中无行情源，Planner **没有虚构**不存在的来源（绑定合法性成立，
同时确认"自主检索"能力尚未接入）。

## 3. 动态动作空间审计（回应 operator 三项重点）

| 项 | 结论 |
|---|---|
| **R 多候选** | ✓ 闭包=**可行性上界**而非唯一动作：r_scan 枚举闭包∩pending 的全部子集，实测各图 2-32 个合法 R 候选 |
| **Z 语义守卫** | ✓ 已加装（终节点 produces 集合不变 + 证据集不变 + 合同满足），实测各图 0-2 个非 IDENTITY 选项（REDUNDANT 过守卫；SPLIT 因合同单字段不适用——如实记录） |
| **π 全覆盖** | ✓ 未执行节点全部可重选模型，空间 3^pending = 729-59049 |
| 缓存/已完成保护 | ✓（Runtime V1 版本化缓存；上轮强制 Z 演示已证） |
| 基线公平 | ✓ 9 策略共享规划器/评估器/动作空间 |

## 4. Runtime V1 兼容性（零调用，适配器=PREDICTED 层，明确标注）

4 份 Planner 原图（每类 1 份）直接入运行时：静态分配生成→执行至中点→
注入故障→SIMPLE_DYNAMIC 与 JOINT_Z_R_PI 均产出合法 (Z,R,π) 动作并完成
恢复执行（R 均为闭包子集、π 覆盖全部未执行节点、Z 均 IDENTITY）。
**兼容性通过**；终端数值为预测层，不代表真实质量。

## 5. 尚缺什么（下一阶段门槛清单）

1. **自主检索**：Planner 只能绑定已有索引，无行情/公告检索节点执行器；
2. **真实节点执行**：适配器仍为回放/预测，需接 APIExecutor+预算准入；
3. **独立终端评分**：新任务的参考事实尚未程序锚定（沿用 T1 锚定流程即可）；
4. 规划失败修复环：1/12 合同违例目前人工丢弃，可加自动修复调用（未授权）。

## 结论

**用户问题→不同合法 DAG 的真实自动规划能力首次得到实测证据**（12 次
真实调用，零现金），四类任务结构分化且无跨类重叠、无虚构来源、无孤立
节点；Runtime V1 与真实 Planner 图即插即用。端到端动态调度收益仍未验证
（60-90 次对照继续 HOLD）。

**完成后 API HOLD 已恢复。** 数据：`fe_screening_runs/planner_v1_20261028/`
（12 原始响应 + 11 合法 spec + LEDGER + PLANNER_V1_RESULTS.json）。
