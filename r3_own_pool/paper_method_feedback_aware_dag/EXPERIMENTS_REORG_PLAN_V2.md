# 实验章重组方案(V2,2026-09-23)

> 目标:第 4 章按"主评估—恢复效率评估—诊断分析"三层重组,四表一图落地;
> 全部数字取自 PAPER_EVIDENCE.md / MULTI_SEED_REPORT.md / STAT_CHECK.md,
> 不再出现受解析缺陷影响的旧值(+20.0pp、91.7%)。旧章中不受影响的材料
> (能力画像、严格配对分解基准、跨域边界)降级为问题 A 的支撑证据,前置到 4.1。

## 新第 4 章结构

**4.1 实验设置与问题 A 的回答(压缩旧 4.2–4.3)**
- 面板:四节点 DAG(e1 表格抽取 / e2 文本抽取 → r 推理 → v 验证),120 题 TAT-QA
  表格-文本混合算术,冻结协议;模型池(7B/14B-GPTQ/coder-7B,本地 vLLM)。
- 能力基线与工作流基线的两分类(Single LLM 属前者)。
- 问题 A 结论一段带过:分解基准(−21.0pp 同模型拆分、+5.0pp 异构分工)与
  clean 三策略比较(Single 0.550/603 全支配)→ 引出问题 B。
- 解析缺陷修正的出处与修正重放方法(附录详述,正文一句话 + 脚注)。

**4.2 主评估:不同执行条件下的任务完成率(RQ1)**
- Table 1:Method × Clean/F10/F20/F30(mean±std,3 种子)+ tokens/latency 列。
- Figure 1:robustness_curve_2panel_multiseed.png(整体 + Hard 双面板,误差棒)。
- Table 1b(子集)与 1c(质量-成本权衡/帕累托):Single 全程支配 clean 成本-质量,
  Static 全工况被支配,Dynamic 自 20%(Hard)/30%(整体)进入非支配集。
- 统计:配对 dQ ± std、零伤害配对(11/0、14/0、17/0,p≤0.001)、30% 跨种子
  一致反超(+4.4±1.4);单种子配对 p 值如实标注"方向一致但未确证"。
- 退化率表(Router +36.4% vs Dynamic −2.1%,seed1 口径,注明)。

**4.3 恢复效率评估:局部恢复 vs 整图重执行(RQ2)**
- Table 2:RD vs FG(Q/tokens/calls/latency/预算违规;配对 dQ −2.5pp,p=0.25,
  CI [−5.8, 0])。同初始图、同检测、同恢复目标、同停止条件,仅重执行范围不同;
  FG 832 次真实调用;未受影响分支重复 217 次;确定性审计(14B 会话级非确定性
  38 次同提示分歧,作为质量差异的界)。
- 预算扫描:FG 违规 68/45/12/1.7/0% @1.0–2.5×,RD 5/0/0/0/0%——"效率而非能力"。

**4.5 多目标执行策略权衡分析(Multi-objective Execution Strategy Trade-off Analysis;不提出优化器)**
- 4.5.1 Pareto 边界与超体积分析(Single 各场景主导 HV;Static/FG 全程零贡献;Dynamic 于 30% 故障成为非支配执行策略——措辞用 becomes a non-dominated execution strategy,禁用 best hypervolume)
- 4.5.2 预算约束下的策略选择分析 Q(B)(clean/10/20% Single 全预算领先;30% 故障 B≥~2800 处 Dynamic 反超;关键句:The optimal execution policy changes with failure probability and resource constraints)
- 4.5.3 动态执行策略切换边界分析(整体切换带 (20%,30%];Hard 子集自 10–20% 起 Dynamic 最优;策略随任务状态变化 → 引出章末伏笔)
- 章末伏笔段:LLM workflow execution is inherently a combinatorial decision problem —— pi=(m_1..m_n, s, r) 在 max(Q,R)/min(C,L) 下的联合决策;本章实验证明最优 pi* 随故障率/难度/预算变化;自动求 Pareto 高效执行配置(演化/整数规划)为第 5 章展望,本文不提出求解器

**4.4 诊断分析(RQ3,明确标注为机制解释,小样本子集不作头条结论)**
- 4.4.1 失败检测评估(Table 4):Evidence F1 0.93 / Execution 1.0 /
  Verification 0.78 / Reasoning 召回 0;x0.8 证据扰动 32/36 在 r 层不可见。
- 4.4.2 验证器消融:跨模型分歧信号精确率 82%(28/34),修复率 21%(7/34),
  Q 不变(0.400,p=1.0),代价 +17% tokens——检测已解,可修复性是瓶颈。
- 4.4.3 恢复归因(Table 3):clean 78 个初始失败按类型(证据解析 44/恢复 16%、
  证据值错 8/12%、执行 4/0%、推理 20/0%、验证 2/0%);注入故障按节点类型
  恢复 29–100% vs 静态级联存活 0–50%——任务固有失败 vs 偶发故障的可修复性差异。
- 4.4.4 入口路由模拟(补充):oracle 上界 = Single-all(0.550),可部署规则
  0.41–0.49;故障场景 oracle 组合 20% 最优(0.4611±0.005)——入口决策的价值
  是成本塑形与中等故障组合,不是 clean 准确率(与 Selective-DAG 门控 AUC 0.734
  的既有发现互证)。

**4.5 附录移交**
- 故障模型定义(能力型;瞬态=成本口径;对抗型不覆盖)、注入输出取自真实失败、
  种子嵌套;局限七条;预算事后统计口径;补充实验身份声明。

## 旧章处置
- 旧 4.2(能力异质性)/4.3(分解基准)压缩进 4.1;跨域(4.5)保留一段引用;
  FLARE-DAG/恢复矩阵 v2 等与主线无关的材料移入附录或删除(待作者定夺);
  旧第 5 章讨论按新定位改写(单模型=能力基线、三条件=合取、恢复边界)。
