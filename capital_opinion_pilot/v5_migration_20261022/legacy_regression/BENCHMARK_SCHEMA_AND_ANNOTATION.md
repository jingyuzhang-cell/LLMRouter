# BENCHMARK_SCHEMA_AND_ANNOTATION — 事件/证据/Gold 模式与标注规范（v1.0）

## 1. manifest.json（每事件）
event_id, company, ticker, event_type(T1-T5), event_onset_date, evidence_cutoff,
regulators[], docs[]{doc_id,title,url,source_type(company_announcement|csrc_penalty|
exchange_letter|regulator_notice),publish_date,sha256,bytes,text_chars}, frozen_at, pool_sha256.

## 2. 原子事实 Gold（atomic_facts.json）
每条：`fact_id, question, answer, answer_type(date|amount|entity|text),
evidence_doc, quote(逐字≤50字), char_start/char_end(原文定位), publish_date,
support_status(supported|contradicted|unverified), annotator(deterministic|ai_cross|human)`
- 双层标注：候选=确定性接地（quote 命中+日期/截止校验）；正式 Gold=再加跨模型 AI 核验
  （授权后）+人工抽检 10%；任一层失败→support_status=unverified，不入主评分分母。
- 每事件 6–12 条，覆盖：时间节点、监管行为、处罚金额/禁入、风险警示安排、主体身份、金额口径。

## 3. 主体关系（entity_relations.json）
三元组 `subject, relation, object, evidence_doc, quote`（如 公司—实控人—张三；
公司—收到—处罚决定书）。供 entity 节点三元组 F1 评分。

## 4. 时间线（timeline.json）
`date(ISO), event_description, evidence_doc`，按日期升序；供 timeline 节点顺序+命中评分。

## 5. 评分规则（冻结，TEST 期禁改）
- 报告/核查输出：事实覆盖（full/partial 两级，Q=(full+0.5·partial)/N）+引用正确率
  （按事实上下文 doc 引用 vs Gold evidence_doc）+未验证日期幻觉标志；
- 提取节点：原子事实 F1（答案匹配+出处正确）；
- 主体节点：三元组精确匹配 F1；
- 时间线节点：事件命中率+顺序违反数；
- 核查节点：支持/反驳/证据不足判断与 Gold support_status 的混淆矩阵。

## 6. 隔离强制
`gold/` 目录仅评分器（离线）可读；运行时组件（planner/retriever/scheduler/executor）
加载器白名单只放行 task.md 与 evidence_index.json；测试用例断言运行时无法打开 gold 路径。
