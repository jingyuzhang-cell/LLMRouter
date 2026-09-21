# 三条件控制性机制分析（零调用重放，2026-09-21）

状态：全部由冻结日志重放 + 本地沙箱/评分器复算得出；**零模型调用、零 GPU**。目的：把中心命题的三个条件从"跨域观察总结"提升为"受控机制证据"。

## 条件 1：能力匹配（Capability Match）

- Math500 正式面板：冻结自财务域的阶段分配先验整体失配——Node/Type Router 13.0% vs Query Router 50.0%（−37.0pp，CI [−48,−26]，McNemar p<1e-10）；medium 求解节点 33/100 正确 vs mono-large 54/100。
- MBPP：Node/Type Router 73.0% 未超过 Always-Large 76.0%（阶段互补仅有限证据）。
- Finance：类型先验与冻结节点路由持平（6.9pp 增益来自阶段粒度）——同一套先验在一个域成立、在另一个域失配，即"能力匹配"是条件而非默认成立。

## 条件 2：接口表达能力（Interface Adequacy）

- Math 两类分解接口族（数值事实+算术表达式；JSON 计划+自由求解）均塌缩（DAG 13–16% vs mono 54%）→ 接口表达力不足时分解/异构/动态同时失效。
- TAT-QA 200 配对题失败分类（`decomposition_benchmark/TAT_QA_FAILURE_CLASSIFICATION.json`）：Harm 56 = 真分解失败 31（推理在 gold facts 下仍错 30 + 抽取值错 1）+ 接口损失 25（执行/解析 12、抽取不可解析 7、**事实顺序/符号错位 6**、百分比/千位缩放 0）。B 类全修的反事实配对差仍 −8.5pp CI 不含零 → TAT-QA 的分解损失以真推理退化为主，接口损失次之；6 例符号/顺序错位是"节点接口丢失语义"的具体机制。

## 条件 3：反馈可诊断性（Feedback Diagnosability）

- **MBPP 信号降级重放**（`p3_xdomain/MBPP_SIGNAL_DEGRADATION.json`）：26/26 个 static 失败任务的代码都能编译并运行，失败全部来自单元测试断言（assertion-only）；7/7 个被 Dynamic 修复的 Help 同样全是 assertion-only。把反馈降级为"仅 syntax/runtime（隐藏断言）"后：**Dynamic 80.0% → 73.0%，低于 Static 74.0%**——+6.0pp 增益几乎 100% 由断言信号承载。同一适应机制、仅换信号内容，增益即反转：这是对"反馈可诊断性"的直接受控证据。
- **Math 信号盲区**（`p3_xdomain/MATH_SIGNAL_BLINDSPOT.json`）：solve 错误 67 题中 62 题"形式合法但数值错误"对部署信号完全隐形；动态实际仅触发 6 次升级（4 solve + 2 verify），而 62 题盲区全部无感；verify 层净效应 −18（修正 3 题、改错 21 题）。
- Finance 既有审计引用：P2 离线检测器 precision 1.0 / recall 33–39%（commit 567b768）；verifier 一致性信号退化为常发（commit 4bcd418）——三个域的信号质量梯度与动态收益梯度同向。

## 结论

三个条件各自拥有"机制级"证据：能力匹配（同一先验跨域反转）、接口表达（两类接口族塌缩 + TAT-QA 逐题分类 + 顺序/符号错位机制）、反馈可诊断性（MBPP 信号降级反事实 + Math 盲区计数）。中心命题的写法由"正负对照归纳"升级为"三个条件的受控机制分离"。
