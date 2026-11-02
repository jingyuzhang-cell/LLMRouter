# P1-1 Static-π 实验设计（零调用）

> 科研线第二项。基于 P1-1 合同 v1_1（sha256 `a1c5d3a9…`，17 状态事实 / 5 关键 / 3 UNKNOWN）与已审计的 DAG 拓扑（dag_propagation_audit.py，5/5 PASS）。

## 一、节点输入规格

### DAG 结构（6 节点，与传播审计一致）

```
E1(D_S1=公告080, 9/10) ──┐
E2(D_S2=公告097, 10/9) ──┼──→ J1(逐阶段三维状态判定) ──→ J2(现时汇总+跨阶段一致性) ──→ SINK(17槽+3拒判)
E3(D_S3=公告098, 10/13) ─┘
```

| 节点 | 输入 | 消费上游 | 输出 |
|---|---|---|---|
| E1 | D_S1 全文 + 六信息项清单 | 无 | JSON: {doc, items: {item: {mentioned: bool, quote, page, summary}}} |
| E2 | D_S2 全文 + 六信息项清单 | 无 | 同上 |
| E3 | D_S3 全文 + 六信息项清单 | 无 | 同上 |
| J1 | E1+E2+E3 输出 + 三维枚举定义 | E1, E2, E3 | JSON: {state_judgments: [{item, stage, dim1_factual, dim2_procedural, dim3_evidentiary, evidence: [{doc, page, quote}]}]} |
| J2 | J1 输出 | J1 | JSON: {current_state(S3 摘要), cross_stage_conflicts: [...], derived: {is_final_finding, prior_notice_cited}} |
| SINK | J1 + J2 输出 + 17 槽位 ID + 3 拒判项 ID | J1, J2 | JSON: 评分器输入格式（见四） |

**六信息项**：虚增利润/营收事实、证监会调查状态、重大违法强制退市风险、交易类退市风险(价格/市值)、行政处罚事先告知书(含文号)、正式处罚决定状态。

**拓扑忠实性**：J1→J2→SINK 单链与传播审计版本图完全一致（J2 消费 J1、SINK 消费 J2，不允许旁路 E 层——SINK 拿到的原文引用只能经 J1/J2 携带）。

### 输入版本与哈希

| 输入 | 来源 | sha256 |
|---|---|---|
| D_S1 (公告2026-080) | 合同 source_pages.S1 | `bba3b15c…`（raw_sha256 冻结） |
| D_S2 (公告2026-097) | 合同 source_pages.S2 | `22f7703f…` |
| D_S3 (公告2026-098) | 合同 source_pages.S3 | `90928fc0…` |
| 合同 | TASK_CONTRACT_P1_1_v1_1.json | `a1c5d3a9…`（评分器内断言校验） |
| 评分器 | state_scorer.py | `3c6030d0…`（冻结，10 篡改测试全过） |

## 二、静态模型分配 π

| 节点 | 类型 | 分配模型 | 依据 |
|---|---|---|---|
| E1-E3 | 文档抽取 | GLM-5.3-Flash | 与 P0-1/P0-2 E 层同构，Batch-1 抽取两模型零差异，取廉价者 |
| J1 | 跨文档状态演化判定 | GLM-5.3-Flash | Static-π 基线先建立单模型参照；能力配对对照留待授权 |
| J2 | 一致性汇总 | GLM-5.3-Flash | 同上 |
| SINK | 终端汇总 | GLM-5.3-Flash | 同上 |

**备选分配**（授权后按需）：全 DS 臂（J1/J2/SINK 换 DeepSeek-flash）、J1=DS 臂（状态判定能力配对）。**本设计只执行全 GLM 一臂**。

## 三、提示词构造

### E 层（3 节点，同构）

```python
system = "你是精确的公告信息抽取器。只输出一个 JSON 对象：{\"doc\": ..., \"items\": {信息项名: {\"mentioned\": true/false, \"quote\": 完整原句逐字引用或null, \"page\": 页码, \"summary\": ≤30字}}}。六个信息项逐项填写，未提及则 mentioned=false。不得编造。"

user = f"时间节点：{stage_date}\n六个信息项：{six_items}\n\n公告{doc_no}全文：\n{doc_text}\n\n逐项抽取：该公告对此信息项是否有披露？披露了什么？携带完整原句引用与页码。"
```

### J1 层（三维状态判定，消费 E1+E2+E3）

```python
system = "你是跨文档监管状态演化判定器。只输出 JSON：{\"state_judgments\": [{\"item\": ..., \"stage\": ..., \"dim1_factual\": ..., \"dim2_procedural\": ..., \"dim3_evidentiary\": ..., \"evidence\": [{\"doc\", \"page\", \"quote\"}]}]}。\ndim1_factual ∈ {CONTINUING, DETAIL_EXPANDED, NEWLY_DISCLOSED, NOT_DISCLOSED, NOT_YET_RECEIVED}\ndim2_procedural ∈ {INVESTIGATION, PRIOR_NOTICE, FINAL_DECISION, NOT_APPLICABLE}\ndim3_evidentiary ∈ {ALLEGATION, NOTICE_CONTENT, DISCLOSED_MARKET_DATA, FINAL_FINDING, UNKNOWN}\n语义规则：NEWLY_DISCLOSED 指\"首次披露\"而非\"首次发生\"；NOT_DISCLOSED 指\"未披露\"而非\"不存在\"；NOT_YET_RECEIVED 需原文明确表述尚未收到；证据性质以所引原文的表述性质为准（涉嫌=ALLEGATION，告知书载明=NOTICE_CONTENT，市场数据=DISCLOSED_MARKET_DATA，处罚认定=FINAL_FINDING，无证据=UNKNOWN）。\n每个判断必须携带证据锚点三元组(doc, page, quote)。仅依据给定材料；信息项在某阶段未提及即 NOT_DISCLOSED。"

user = f"任务问题：{question}\n三个时间节点：S1={s1_date}(公告080), S2={s2_date}(公告097), S3={s3_date}(公告098)\n\n三份公告的抽取结果：\n{upstream_e1_e2_e3}\n\n对六个信息项 × 三个阶段逐项判定三维状态。若某信息项在某阶段不该有状态记录（如该信息项本身在合同槽位中不存在），跳过该槽位。"
```

**隔离决策（记录在案）**：J1 提示词包含三维枚举值与通用语义规则（合同 annotation_rules 的措辞），**不包含任何 item×stage 的 Gold 取值**。枚举语义是任务定义的一部分（无它则输出无效）；Gold 映射不进入提示词。

### J2 层（现时汇总+跨阶段一致性，消费 J1）

```python
system = "你是状态汇总核验器。只输出 JSON：{\"current_state\": {item: S3三维摘要}, \"cross_stage_conflicts\": [{item, conflict, detail}], \"derived\": {\"is_final_finding\": bool, \"prior_notice_cited\": bool}}。冲突=同一信息项跨阶段状态出现不应有的回退或矛盾（如程序阶段从 PRIOR_NOTICE 退回 INVESTIGATION）。is_final_finding 仅在存在 FINAL_DECISION/FINAL_FINDING 证据时为 true。"

user = f"以下是 J1 的逐阶段状态判定：\n{upstream_j1}\n\n汇总当前(S3)各信息项状态；检查跨阶段一致性；输出派生判定。"
```

### SINK 层（终端，消费 J1+J2）

```python
system = "你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\": [...], \"unknown_slots\": [...], \"complete\": true/false}。不得使用给定上游材料之外的任何信息。"

user = f"任务问题：{question}\n\nJ1 判定与 J2 汇总：\n{upstream_j1_j2}\n\n输出：answers 数组逐槽位填写 {{\"fact_id\":..., \"dim1_factual\":..., \"dim2_procedural\":..., \"dim3_evidentiary\":..., \"quote\": J层携带的原句, \"doc\": 公告号, \"page\": 页码}}。\n槽位 ID：{17_slot_ids}\nunknown_slots：{{\"fact_id\": \"UNK_<id>\", \"item_id\": ..., \"action\": \"ABSTAIN\", \"dim1_factual\": \"UNKNOWN\"}}，拒判项 ID：{3_unknown_ids}。仅当某拒判项确有超出材料的把握时才改填具体值（action 省略即视为断言）。上游不完整无法负责作答则 complete=false。"
```

**隔离保证**：SINK 只见槽位 ID（VF_S1…FD_S3）与拒判项 ID，不见 Gold 值；quote 必须是 J 层携带原句（锚点三级评分：present/match/missing/mismatch）。

## 四、独立评分方案

**评分器**：`state_scorer.py :: score_state_evolution(gold_contract, model_answers)`（冻结，sha `3c6030d0…`）

**评价流程**：
1. SINK 输出 → 适配器原样映射为 `model_answers`（fact_id / 三维 / quote / item_id / action；适配器零语义改写）
2. 评分器内部断言合同 SHA = `a1c5d3a9…`（Fix 4）
3. 输出五维报告：dim1/dim2/dim3 准确率（分母恒 17，Fix 1 唯一映射）、关键门禁、UNKNOWN 四态（ABSTAIN/ASSERTED/MISSING/DUPLICATE）、锚点三级、完备性

**关键事实门禁**（5 项）：`VF_S2, TR_S3, PN_S2, FD_S2, FD_S3`（三维全对才算过）

**UNKNOWN 处理**：U_FD / U_TR_PRE / U_INV_DATE —— ABSTAIN 正确；ASSERTED 计失败；MISSING 计缺

**评分独立性**：评分器与执行模型零接触；quote 锚点与 Gold 证据句逐字比对（match 级），不可自证。

## 五、成本与时延统计

| 指标 | 记录方式 |
|---|---|
| 调用数 | 6 节点 × 3 重复 = 18 |
| Token in/out | 每次 API 调用 usage 字段 |
| 费用 | 冻结牌价核算（GLM ¥0.8/M in, ¥2.8/M out） |
| 时延 | 每次 API 调用墙钟（Gateway 串行化约束如实记录） |

## 六、重复与统计

- 3 次重复 × 1 任务 = 3 个 run；temperature = 0；每 run 独立 DAG 实例
- 统计：三维逐维准确率、关键 5 项全对率、UNKNOWN 拒判正确率（3/3）、锚点 match 率、J1 逐槽位跨重复稳定性
- 描述性统计（3 次重复不做推断性检验）；与 P0-1/P0-2 同批或分批执行均可，单独统计
