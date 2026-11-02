# P0-1/P0-2 Static-π 实验设计（零调用）

> 科研线重启首项。基于 PHASE2B v2.1 合同（sha256 `f92090b0…`，23 事实 / 12 关键），不新建任何模块。

## 一、节点输入规格

### DAG 结构（7 节点）

```
E1(D1=祥源文旅) ──┐
E2(D2=交建股份) ──┼──→ J1(实体归一) ──→ J2(主体绑定计数) ──→ SINK
E3(D3=西王食品) ──┤         ↑                                    ↑
E4(D4=纳川股份) ──┘─────────┘────────────────────────────────────┘
```

| 节点 | 输入 | 消费上游 | 输出 |
|---|---|---|---|
| E1 | D1 全文 + 问题 | 无 | JSON: {subjects, notice_numbers, dates, cause, quotes} |
| E2 | D2 全文 + 问题 | 无 | 同上 |
| E3 | D3 全文 + 问题 | 无 | 同上 |
| E4 | D4 全文 + 问题 | 无 | 同上 |
| J1 | E1 输出 + E2 输出 + 问题 | E1, E2 | JSON: {judgments: [{kind, verdict, evidence}]}, kind ∈ {person_identity, notice_instance, receipt_event, announcing_companies} |
| J2 | J1 输出 + E3 输出 + E4 输出 + 问题 | J1, E3, E4 | JSON: {subject_binding, notice_binding, cause_specificity, counts, unresolvable} |
| SINK | J1 输出 + J2 输出 + 23 槽位 | J1, J2 | JSON: {answers(23), abstentions(1), complete} |

**关键约束**：SINK 只消费 J1/J2（无 E 旁路，已在 DAG 依赖审计中验证必要依赖）。

### 输入版本与哈希

| 输入 | 文件 | sha256（已冻结） |
|---|---|---|
| D1 | E10-xiangyuan.pdf | `4c930d15…` |
| D2 | E10b-jiaojian.pdf | `168f72a8…` |
| D3 | E07-xiwang.pdf | `dd764d9f…` |
| D4 | E05-nachuan.pdf | `0c62e50f…` |
| 合同 | TASK_CONTRACT_PHASE2B_v2_1.json | `f92090b0…` |
| 评分器 | terminal_quality v1.2.3 | 永久冻结 |

## 二、静态模型分配 π

**分配原则**：从 Batch-1 校准矩阵出发（金额/日期/主体→GLM，跨文档一致性→DS），结合 P0-1/P0-2 的节点类型。

| 节点 | 类型 | 分配模型 | 依据 |
|---|---|---|---|
| E1-E4 | 文档抽取 | GLM-5.3-Flash | Batch-1 抽取零错误（两模型），取廉价者 |
| J1 | 实体归一 | GLM-5.3-Flash | 校准日期文号 GLM 0.78 vs DS 0.82，但 E04-J1 两模型收敛全对；取廉价者 |
| J2 | 主体绑定计数 | GLM-5.3-Flash | 同上 |
| SINK | 汇总 | GLM-5.3-Flash | 汇总类 GLM 0.80 = DS 0.80，取廉价者 |

**备选分配**（用于后续能力配对对照）：
- 全 DS：J1/J2/SINK 换为 DeepSeek-flash，E 不变
- 交叉：J1=DS, J2=GLM, SINK=GLM

**当前设计只执行全 GLM 一臂**（Static-π 基线）；备选臂在获得授权后按需执行。

## 三、提示词构造

### E 层（4 节点，完全相同结构）

```python
system = "你是精确的文书信息抽取器。只输出一个 JSON 对象：{ \"subjects\": [...], \"notice_numbers\": [...], \"dates\": [...], \"cause\": [...], \"quotes\": [...] }，每项为 {field, value, quote(完整原句逐字引用), page}。不得编造。"

user = f"任务问题：{question}\n\n文档{doc_id}全文：\n{doc_text}\n\n请抽取：立案对象(公司/个人/两者及姓名)、告知书编号(逐个)、全部日期(注明性质：落款/收到)、立案事由(原句)、以及对应完整原句引用。"
```

### J1 层（实体归一，消费 E1+E2）

```python
system = "你是跨文档实体归一核验器。只输出 JSON：{\"judgments\": [{\"kind\": ..., \"verdict\": ..., \"evidence\": [{\"doc_id\", \"page\", \"quote\", \"source_raw_sha256\"}], \"reasoning\": ≤15字}]}。kind ∈ {person_identity, notice_instance, receipt_event, announcing_companies}，verdict ∈ {SAME_PERSON, DIFFERENT_PERSON, SAME_NOTICE_INSTANCE, DIFFERENT_NOTICE_INSTANCE, SAME_RECEIPT_EVENT, DIFFERENT_EVENT, SAME_COMPANY, DIFFERENT_COMPANY, UNKNOWN}。每个判断必须携带证据锚点五元组。仅依据给定材料。"

user = f"任务问题：{question}\n\n以下是两份公告的抽取结果：\n{upstream_e1_e2}\n\n请判定：两份公告中的'俞发祥'是否同一自然人；告知书是否同一份实例；收到事件是否同一事件；公告主体是否同一公司。"
```

### J2 层（主体绑定计数，消费 J1+E3+E4）

```python
system = "你是主体绑定与计数核验器。只输出 JSON：{\"subject_binding\": [{doc, subject_type, entities, evidence}], \"notice_binding\": [{doc, numbers, per_number_binding_or_null, rule_applied, evidence}], \"cause_specificity\": [{doc, class, evidence}], \"counts\": {personal_filing_instances, announcing_company_count, d3_subject_count, evidence}, \"unresolvable\": [{field, reason}]}。subject_type ∈ {COMPANY_ONLY, PERSON_ONLY, BOTH}。D3两编号按'分别…分别'顺序对应规则逐号绑定。无法判定列入 unresolvable。每项判断必须携带证据锚点五元组。"

user = f"任务问题：{question}\n\n以下是实体归一结果与另两份公告抽取：\n{upstream_j1_e3_e4}\n\n请完成：四份公告各自的主体绑定与编号归属（含D3逐号绑定）；事由特定性分类；三项计数。"
```

### SINK 层（终端汇总，消费 J1+J2）

```python
system = "你是严谨的最终答案汇总器。只输出一个 JSON 对象：{\"answers\": [...], \"abstentions\": [...], \"complete\": true/false}。不得使用给定上游材料之外的任何信息。"

user = f"任务问题：{question}\n\n以下是实体归一与主体绑定计数结果：\n{upstream_j1_j2}\n\n输出格式：answers 按槽位逐项填写 {{\"fact_id\":..., \"value\":..., \"quote\": 上游J层携带的原句锚点, \"doc\": 文档ID, \"page\": 页码}}。\n数值只填数字；日期 YYYY-MM-DD。\n槽位：{slots_without_description}\nunknown 项：{unknowns}\n如认为上游不完整无法负责作答，置 complete=false。"
```

**隔离保证**：所有槽位剥离 description（runner2 白名单已验证），Gold 枚举不进入提示词。

## 四、独立评分方案

**评分器**：terminal_quality v1.2.3（永久冻结，64/64 测试通过）

**评价流程**：
1. SINK 输出 JSON → 适配器提取 claims（fact_id/value/quote/doc/page）
2. 适配器从合同 source_pages 补充锚点哈希（模型不接触）
3. `evaluate_terminal_quality(contract, terminal_output, source_pages)`
4. 报告：三维度 + critical_gate + fact_metrics + unmapped + unknown_rejection

**关键事实门禁**（12 项）：A1-A4（立案对象）、B3/B3b（编号结构/逐号绑定）、D_1/D_2/D_4（实体归一）、E1/E2（计数）、F4（落款日差≠事件差）

**UNKNOWN 处理**：U2（D3 收到日期仅"近日"）→ 正确拒判加分；断言计失败

**Q_MVR 口径**：Q_final = NULL（relevance 未评价）；报告 dimensions + critical_gate + fact_metrics

## 五、成本与时延统计

| 指标 | 记录方式 |
|---|---|
| 调用数 | 7 节点 × 3 重复 = 21 |
| Token in/out | 每次 API 调用 usage 字段 |
| 费用 | 按冻结牌价核算（GLM ¥0.8/M in, ¥2.8/M out） |
| 时延 | 每次 API 调用墙钟（注意 Gateway 串行化约束） |

## 六、重复与统计

- 3 次重复 × 1 任务 = 3 个 run（P0-1 与 P0-2 同批执行、单独统计）
- temperature = 0
- 每个 run 独立 DAG 实例（上游快照独立）
- 统计：各维度准确率、关键事实全对率、UNKNOWN 拒判率、逐节点输出稳定性
- 结果形式：描述性统计（3 次重复不足以做推断性检验）
