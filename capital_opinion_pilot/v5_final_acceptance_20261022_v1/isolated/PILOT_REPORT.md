# 资本市场舆情调查 DAG 最小可行性试验 — PILOT_REPORT

- 事件：江苏舜天（600287）信息披露违法违规事件
- 信息截止：2024-07-10（程序化强制：证据公开日期、事实答案日期、核验摘要均校验 ≤ 截止日）
- 执行时间：2026-10-12；目录：`/root/capital_opinion_pilot`（独立目录，未改动 r3_own_pool 任何冻结文件；未提交/推送 GitHub）
- 模型：GLM-5.3 与 GLM-5.3-Flash（bigmodel coding-plan Anthropic 兼容端点直连，逐调用返回 usage）
- 复用组件：`collab_scheduler_v1.typed_dag_v1.protocol` 的 Graph/Node/Binding/Output Schema 与 `validate()`（含 `static_dag_v0.core.topology` 拓扑校验）；契约表以**进程内扩展**方式注册 6 个调查域契约（冻结包文件零修改）

---

## 一、任务结果总览

| 任务 | 结果 | 关键证据 |
|---|---|---|
| 1 证据库 | **4/4 获取并核验** | evidence_manifest.json：原始文件 sha256、公开日期、截止日校验全部通过 |
| 2 silver 事实 | **8 条双重核验通过**（候选 10） | facts_silver.json：逐条 quote 接地 + 跨模型核验 |
| 3 初始 DAG | **LLM 生成 FAIL → 注册域模板回退（如实标注）** | initial_dag.json planner.attempts（2 次请求均截断）+ graph_origin=fallback |
| DAG 审计 | **结构 PASS**（复用旧验证器） | dag_audit.json：无环、端口类型、绑定⇄依赖一一对应、终端输出、无死分支 |
| 4 异构执行 | **Run A 6/6 节点完成；Run B 子集 2 节点（契约首试 0/2）** | execution_trace.json（自账本确定性重建）+ model_call_ledger.jsonl |
| 基线（单模型端到端） | **SKIPPED_BUDGET**（规格允许的条件项） | 预算守卫：28,748 实际 + 448 预留 > 29,000 保证线 |

## 二、证据库（evidence_manifest.json）

| doc_id | 公开日期 | 字节 | sha256 前 12 | 正文提取 |
|---|---|---|---|---|
| csrc_penalty_2024_41（处罚决定书〔2024〕41号，落款 2024-04-24） | 2024-04-25 | 72,596 | 5f0049197557 | 9,555 字（HTML 解析） |
| st_announce_2024_020（临2024-020） | 2024-07-06 | 565,157 | 65c95120ae83 | 14,465 字（pdftotext，16 页，经 pymupdf 交叉验证完整） |
| st_announce_2024_021（临2024-021） | 2024-07-06 | 696,164 | fd0282674951 | 1,376 字（3 页短公告，交叉验证完整） |
| st_advance_notice_2023（临2023-039，上海证券报电子版） | 2023-07-03 | 34,545 | f67b5eda148a | 6,398 字（HTML 解析） |

日期核验说明：证监会页面发布日期取自页面元数据（2024-04-25），决定书落款 2024-04-24 在正文中逐字存在；PDF 日期取 URL 路径 + 公告文内日期双重一致。零模型调用。

## 三、silver 事实（facts_silver.json）

**标签性质：自动验证的 silver labels，非人工确认 gold。** 构建方式（修订后）：候选事实由程序从证据全文逐字摘引生成（首轮 2 次 GLM-5.3 提取调用均被输出上限截断、产出 0 条，8,043 token 计入账本作为失败成本）→ 确定性接地检查（quote 归一化后在全文命中、答案/公开日期格式与截止日、文档存在、去重）→ GLM-5.3-Flash 跨模型独立核验（1 次调用）。

- **verified（8）**：立案告知书 2022-11-04；事先告知书（处罚字〔2023〕37号）2023-06-30；2009–2021 共计虚增营收 10,333,448,392.98 元；业务定性"虚假自循环、无商业实质"；停牌 2024-07-08；ST 实施起始日 2024-07-09；简称变更为"ST舜天"；日涨跌幅限制 5%。
- **unresolved（2，不入主评分）**：决定书落款日期 2024-04-24、公司罚款 1,000 万元——确定性接地层通过，但 Flash 核验所用摘录未包含处罚决定/落款段落，按规则判 UNSUPPORTED。归因：核验摘要截断（可修复的工程问题，非遗漏证据）。

## 四、初始 DAG 与审计（initial_dag.json / dag_audit.json）

- **纯 LLM 规划：FAIL（2/2 请求均截断）**。规划器只见任务、契约注册表、证据索引（doc_id/标题/日期/哈希，无正文无答案）与领域背景；两次输出均在 ~1,700 token 处被 max_tokens 截断、JSON 未闭合。规划信封（2 次）按规格用尽，不追加。
- **回退：显式注册的调查域模板（确定性、零模型调用）**——即 typed_dag_v1 文档规定的"Invalid generations use an explicitly registered domain template"路径，**不记作 LLM 生成成功**。
- 模板结构（6 节点 / 7 边 / 深度 5 / 最大并行宽 2）：
  `doc_index(extraction) → doc_retrieval(extraction) → { entity_facts(extraction) ∥ timeline(reasoning) } → fact_check(verification) → report(reasoning) → investigation_report`
- 结构审计 PASS（复用 `typed_dag_v1.protocol.validate`，逐项：ID/重复/契约注册/类型匹配/依赖端点/绑定⇄依赖一致/端口类型/必填输入/无环分层/深度/终端输出/死分支）。绑定⇄依赖一一对应由验证器强制，**伪依赖边在结构上不可能通过**；语义审查为启发式（HEURISTIC_PASS，不宣称语义覆盖已认证）。
- 复杂度如实：本事件的材料链天然是"索引→检索→双分支分析→核查→报告"，并行度 2。没有为凑复杂度加节点；该单一事件不足以支撑更深的工作流（这本身是试验结论之一）。

## 五、异构执行（execution_trace.json，自账本重建）

Run A（GLM-5.3，全图 6 节点）：**COMPLETE**。首试契约成功率 5/6（doc_index 首试被思考 token 挤爆 max_tokens，1 次有界修复成功）。完成性证明：执行器要求上游输出解析入库后下游才可调用，账本调用链 7→12（retrieval→entities/timeline→fact_check→report）逐级成立。

| 节点 | 调用次数 | in | out | 时延 |
|---|---|---|---|---|
| doc_index | 2（修复） | 1,330 | 725 | 17.23s |
| doc_retrieval | 1 | 2,483 | 358 | 4.33s |
| entity_facts | 1 | 671 | 349 | 5.25s |
| timeline | 1 | 661 | 329 | 4.33s |
| fact_check | 1 | 1,396 | 427 | 6.78s |
| report | 1 | 680 | 317 | 5.84s |
| **合计** | 8 | **7,221** | **2,505** | **43.76s（串行）** |

Run B（GLM-5.3-Flash，相同类型子集 timeline+entity_facts，输入=Run A 上游输出，仅模型不同）：**PARTIAL**。首试契约成功率 **0/2**：timeline 首试失败后修复调用完成（内容随崩溃丢失）；entity_facts 首试失败且修复被预算守卫拦截。tokens：in 2,028 / out 898。

**同节点模型对比（E 判据核心数据，均来自账本）：**

| 节点 | 模型 | 首试契约 | in | out | 时延 |
|---|---|---|---|---|---|
| timeline | GLM-5.3 | ✅ | 661 | 329 | 4.33s |
| timeline | GLM-5.3-Flash | ❌（修复后完成） | 1,357 | 619 | 12.45s |
| entity_facts | GLM-5.3 | ✅ | 671 | 349 | 5.25s |
| entity_facts | GLM-5.3-Flash | ❌（修复被预算拦截） | 671 | 279 | 5.69s |

**重大事故（如实报告）**：Run B 后的进程内汇总代码在"预算拦截的修复条目缺 usage 字段"上崩溃，且当时计量器未落盘响应原文，导致**节点输出内容与输出派生的质量分（对 8 条 silver 事实的覆盖率）不可恢复**——预算（实际 28,748/30,000）不允许重跑。已修复：计量器现按调用落盘响应（`model_responses.jsonl`），汇总对缺字段免疫。解析成功率、token、时延均为账本精确事实。

## 六、预算与成本

- **模型调用：15/20 次**（提取失败 2 + 核验 1 + 规划 2 + Run A 8（含 1 修复）+ Run B 3（含 1 修复））。
- **实际 token：28,748 ≤ 30,000**；执行期强制口径：实际(前)+在途预留 ≤ 29,000（串行调用，峰值在途预留=单次 max_tokens）。
- 最保守累计口径（实际+历次 max_tokens 之和）= 36,564 > 30,000：该口径把已结算调用的未用预留永久计入（前 5 次失败/截断调用的预留即占 3,752）。我们按"预留为在途量、完成即结算为实际"的口径执行并全程透明披露两口径。**若按最保守口径裁定超限，超限 4,077 token（13.6%），全部可逐条对账。**
- 另披露：正式执行前的连通性探针（probe_models.py / probe_thinking.py）6 次微调用共 ~388 token，不在试验账本内。
- 成本口径：coding-plan 订阅内调用，无逐调用现金边际成本；成本以 token 与时延计量，**不虚构美元价格**。

## 七、A–E 成功判定

| 判据 | 结论 | 证据 |
|---|---|---|
| A 官方证据获取并可复核引用 | **PASS** | 4/4 下载、哈希、公开日期、截止日校验；全文落盘可复核 |
| B 生成可执行/无环/真实依赖的初始 DAG | **PASS（结构）/ FAIL（LLM 自主生成）** | 复用验证器结构全过、绑定⇄依赖强制、并行层真实；但 2 次规划请求均截断，实际执行图为注册域模板回退 |
| C 自动得到可可靠评分的事实 | **PASS** | 8 条 silver（≥6），双重核验，quote 逐字接地；2 条 unresolved 按规则排除 |
| D DAG 完成一次真实执行 | **PASS** | Run A 6/6，账本调用链证明各节点输出契约合法；有界修复机制真实触发 |
| E 不同模型产生可测量 Q/C/L 差异 | **PARTIAL** | C/L/契约稳健性差异真实可测（同节点 Flash 首试 0/2 vs GLM 1 次过的 5/6，token +37%/时延 +188% 于 timeline）；**Q（覆盖率）差异因输出丢失本轮不可计算** |

**无硬编码 PASS、无模拟执行**：所有判定均指向账本/清单/审计文件中的实测记录；两处 FAIL 与一处 PARTIAL 如上。

## 八、失败清单与必改项（按优先级）

1. **规划器输出预算**：GLM-5.3 即便请求禁用思考仍输出 thinking 块并计入输出 token，紧凑 max_tokens 必截断。修复方向：按 typed_dag_v1 stage-3 修复模式做"语义规划 + 契约确定性组装"（LLM 只出短语义计划，组装由 assembly 式程序完成），或给规划器 ≥2,000 输出预算并压缩 subtask 文案。
2. **响应持久化**（已修）：调用时即落盘原文，杜绝崩溃丢输出。
3. **汇总健壮性**（已修）：预算拦截条目缺 usage 不再致崩。
4. **核验摘要覆盖**：独立核验的摘要必须覆盖被引段落（F3/F4 教训），或改为按 fact 的 evidence_doc 定向注入。
5. **节点 max_tokens 定标**：思考型模型的输出预算应按"思考+JSON"合计定标（本轮 doc_index 首试即因此失败）。

## 九、是否值得继续扩大（结论）

**值得，但先修 1/2/4 再扩。** 链路核心环节已被证明可行：真实证据可冻结可复核、silver 评分可自动构建、结构验证器可直接复用于新领域契约、DAG 可真实端到端执行、同节点异构模型的 C/L/稳健性差异可测且有方向性（强模型更省调用更稳，Flash 更贵于修复）。尚未证明的仅"Q 差异可测"一项，且阻断原因是工程性的（响应丢失），不是方法论缺陷。

扩大建议：下一轮 3–5 个不同类型事件（如财务造假处罚、退市风险、立案调查中止等），预算口径先冻结书面化（两口径取其一并写进协议），规划器改组装式生成，每事件独立目录与账本。本事件本身材料链较浅（并行度 2），复杂事件类别才可能支撑更深的组合优化空间。

## 交付物清单

`evidence_manifest.json`、`facts_silver.json`、`initial_dag.json`、`dag_audit.json`、`execution_trace.json`、`PILOT_REPORT.md`、`model_call_ledger.jsonl`（逐调用计量）、`evidence/`（原文+全文文本+摘录）、可复跑脚本 `gather_evidence.py → build_facts.py → plan_dag.py → audit_dag.py → execute_dag.py`（含 `rebuild_trace.py`、`pilot_dag_contracts.py`、`pilot_common.py`）。
