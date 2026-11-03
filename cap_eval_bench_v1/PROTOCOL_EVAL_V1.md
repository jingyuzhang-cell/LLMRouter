# PROTOCOL_EVAL_V1 — 独立终端评测协议（冻结版 v1）

适用对象：静态异构分配（Codex 线）、结构优化线、动态联合调度（ZCodex 线）、单模型/同构基线。
本协议由评测模块独立维护；被评系统不得读取 tasks_private*、scoring/silver*、本文件中的任何
评分参考内容（隔离检查见 isolation/gate.py）。

## 1. 任务与证据（已冻结）
- 8 个任务 / 4 类：监管处罚 T-P1..P3、信息披露变化 T-D1..D2、并购重组 T-M1、事件市场反应 T-R1..R2。
- 23 份官方证据文档（17 份复用既有冻结库原文 + 6 份新采集，全部带 URL/日期/SHA256，见
  evidence/index.json）；每个任务冻结证据 doc 集、信息截止日、交付 schema、UNKNOWN 边界、
  墙钟 deadline（1800s/任务，可全系统一致调整但须赛前统一）。
- silver 参考：52 条机器构建原子事实（逐字引文+程序接地，100% 接地通过），仅存在于私有面。
  **Silver ≠ Gold**：Gold 须按 gold/GOLD_RULES.md 完成独立人工裁决后才可宣称。

## 2. 证据访问（唯一合法通道）
所有系统只能通过 evidence/retrieval_api.py 访问证据：确定性、按任务作用域、按预算（chars）、
逐次调用写审计日志（计入该 run 的 E 成本）。查询词由被评系统自选——检索策略是被评能力的一部分；
默认词下限基线见 evidence/retrieval_coverage.json（仅为评测侧审计，不作任何系统输入）。
禁止直接读取 evidence/texts 原文（评测侧与集成契约强制）。

## 3. Q/E/K 定义（冻结；与 scoring/qe_k_scorer.py 一致）
**Q ∈ [0,1]** = 0.55×coverage + 0.25×citation_accuracy + 0.20×unknown_compliance − hallucination_penalty
- coverage=(full+0.5×partial)/N_silver；date=ISO 精确；amount=归一化子串；text=逐字/≥5字分段两级；
- citation_accuracy=被引已覆盖事实中引用正确文档比例（按事实上下文窗口归因，全文档兜底）；
- unknown_compliance=任务 UNKNOWN 边界逐项显式标注率（探测词匹配，确定性）；
- hallucination_penalty=证据∪silver 之外的断言日期每条 −0.05，封顶 −0.15。

**E（向量，禁止坍缩为标量）**：C_model_first / C_model_repair / C_planning / C_retrieval_chars /
C_retrieval_calls / C_program_ms /（合计 C_total_tokens）；L_service_s / L_wall_s；reuse_events
（跨请求复用记 0 新增成本但必须显式标记；完整成本口径另按历史真实支出计）。价格口径：订阅制无
逐调用计费时标记 UNKNOWN，token 为成本基数，禁止虚构货币数。

**K**：schema_conformance（必填交付字段齐备率）、first_attempt_contract_rate、repair_count、
deadline_compliance（wall_s ≤ task.deadline_s）、verdict ∈ {COMPLETE, INCOMPLETE, ABORTED}。

## 4. 统计口径（成本/墙钟/可靠性/按期完成率）
- 成本：全成本记账（规划+检索注入+模型首试+修复+程序毫秒）；同一 run 内不得遗漏失败调用；
- 真实墙钟：trace.wall_s 由被评系统以单调钟实测（规划前→交付落盘后），跨会话墙钟不可作配对比较
  （只作描述性）；同批对照须同会话或同负载条件并声明；
- 可靠性：以 run 为单位（verdict、first-attempt rate、repair 计数）；异常/恢复事件须在 trace
  nodes[].repair_of 与 notes 中如实记录；
- 按期完成率：P(wall_s ≤ deadline) 与 P(verdict=COMPLETE ∧ deadline_compliance)，每系统每任务
  k 次重复（k≥3 时报均值±std，k<3 只报中位数并标注探索性）。

## 5. 公平比较规则（三条系统线同一裁判）
1. 同任务、同证据 API 与预算上限、同模型集合与解码约定、同交付 schema、同 deadline；
2. 输出预算配平：各系统各节点 max_tokens 同额（防截断混杂——V2.1 教训已固化）；
3. 重复与随机性：k 次独立 run（不同 run_id）；报告 Q 中位、E 各维中位、K 比率；配对比较仅限
   同任务同重复序号（paired-by-index）；
4. 判定门槛（事前冻结）：系统 A 优于 B 需在 ≥6/8 任务上 Q 中位不降且（C_total_tokens 或
   L_service_s）中位改善 ≥20%，或 K 的 deadline_compliance/COMPLETE 率严格更高且 Q 不降；
   结构/调度收益必须给出场均差与逐任务方向（不允许只报总量）；
5. Pareto 陈述：以 (Q, C_total_tokens, L_service_s) 三维非支配关系报告；hypervolume 留待正式
   阶段以本协议 v1.1 冻结参考点后启用。

## 6. 防泄漏与防伪
- 隔离门：任何面向系统的输入（prompts/configs/控制器状态）可被 gate.py 扫描；评测侧定期对
  planner_static/structure_opt/dynamic_joint 的输入目录执行 check；
- silver/branch/私有任务内容出现在被评系统输入即判该系统全部结果无效；
- 严禁模拟输出/补写执行记录；trace 与 retrieval_log 交叉核验（chars_injected、调用次数）；
- 修改本协议或评分器必须产生新版本号并重新冻结哈希（BENCH_FREEZE_MANIFEST.json）。

## 7. 评测产出（由本模块出具）
per-system per-task：Q/E/K 全分解 + verdict；跨系统：配对表、Pareto 关系、逐任务方向图、
按期完成率与可靠性汇总；全部离线可复算（scoring/qe_k_scorer.py + trace + deliverable）。
