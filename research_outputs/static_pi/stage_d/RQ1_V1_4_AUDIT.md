# RQ1 V1.4 科学有效性审计（零调用）

**结论**：V1.4 的材料与框架可复核，但存在 **1 项 FAIL（上游泄漏）**、3 项 BLOCKED/PARTIAL；不满足 RQ1 GO 条件。以下逐项给证据。

## 1. node_type 定义一致性 — FAIL

- 材料中 E05/E06/E08 的 `merge` 节点被标为 `kind:"reason"`，与 E04 的 `anomaly_calc`（真推理）混为一类；E04 的 `reg_timeline` 是 timeline，E05 的风险时间线却在 extract 节点里。
- 证据：`rq1_tasks/rq1_tasks_materials.json` 节点 kind 字段。
- 后果：跨任务的"reason"能力不可比；timeline/verification 覆盖偏差。
- 修复：拆分为 extract / timeline / merge / reason / verification / report；E05 风险提示节点改为 timeline；E05/E06/E08 的 merge 独立成类。

## 2. 跨任务定义偏差 — BLOCKED

- 同为 extract：E04 财务金额抽取、E05/E07 监管事实抽取、E06 业绩表抽取，难度与证据结构不同；V1.4 未给节点特征值，无法校正。
- 需要：每节点 information_complexity / evidence_dispersion / output_complexity / dependency_depth 的实际取值。

## 3. 四个特征是否可复核 — FAIL

- V1.4 只有文字定义，材料 JSON 没有逐节点特征字段；无法复核或用于条件化分析。
- 修复：在材料中增加 `features` 字典并冻结定义。

## 4. Gold 是否覆盖必要事实 — PARTIAL

- E04 29 条（M8-P2）；E05 11、E06 12、E07 11、E08 10；事实数 73。
- 事实覆盖了日期/金额/对象/原因，但**关系型事实**（立案与风险警示的先后/因果）不足；下游节点 Gold 主要复制上游事实。
- 需要：为 merge/verification/report 增加**派生关系 Gold**（见第 6 项）。

## 5. UNKNOWN 是否保留 — PASS（有限）

- 4 条 UNKNOWN：F-E05-11（风险警示未消除）、F-E06-12（投资者沟通风险因素）、F-E07-11（审计最终意见）、F-E08-10（投资者沟通内容）；E07 立案精确日亦不可判定。
- 材料显式标注 expected_status=UNKNOWN；报告若断言具体值应判 unknown_asserted。
- 限制：UNKNOWN 的评分规则尚未写入评分器；需在 V1.5 冻结。

## 6. 节点输入是否存在上游泄漏 — **FAIL（阻断）**

- E05 `merge` 的参考上游 fact_ids = F-E05-2/3/4/9；其 **Gold fact_ids = F-E05-2/3/9** —— Gold 全在输入里，模型可直接抄。
- E06 `merge`（输入 1/5/11，Gold 1/5/11）、E07 `verify`（输入 1/3/7/9，Gold 3/7/9）、E08 `merge`（输入 1/5/7/9，Gold 1/7/9）同样重叠。
- E04 `final_report` 输入含 C1/C2/F1/F2/F3，Gold 含 C1/C2/F3 → 重叠。
- 后果：第一层对 merge/verify/report 的"能力"测量变为复制能力；第二层也可能高估。
- 修复：下游节点 Gold 改为**不在输入中出现的派生关系/综合结论**（如"立案晚于风险警示""立案原因与风险警示触发原因不同""两类退市路径先触及先适用"），并保留证据跨度。

## 7. 参考上游是否独立于被测模型 — PASS

- 参考上游来自原文提取的 Gold 事实，不由 GLM/DeepSeek 生成；但需与第 6 项一起修复（独立≠不泄漏）。

## 8. 统一 GLM/DS/LOTO 的任务/文档/评分一致性 — PASS（设计）

- 三条件使用同一任务、文档、评分器、参考上游；V1.5 需把"同文档/同评分"写入预注册。

## 9. Best Unified 是否只用训练任务 — PASS（设计）

- V1.4 明确按折在训练任务上选统一 GLM/DS；需在执行代码中强制，不得看留出任务。

## 10. 第二层是否评价完整 DAG 终端 — PARTIAL

- 设计是完整 DAG；但当前材料的下游 Gold 泄漏使终端结果可能被上游复制污染；修复第 6 项后才成立。

## 审计结论

- **FAIL 2 项**（node_type、上游泄漏）；**BLOCKED 1 项**（特征值）；**PARTIAL 3 项**（Gold 覆盖、UNKNOWN 评分、第二层）。
- **不足以 RQ1 GO。** 必须先完成 V1.5 修复：节点类型拆分、特征冻结、派生关系 Gold、UNKNOWN 评分、任务扩充/功效、预算与独立审查。
