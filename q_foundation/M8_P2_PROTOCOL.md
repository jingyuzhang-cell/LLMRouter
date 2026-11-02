# M8-P2 预注册协议（V1.1，冻结候选）

**状态**：待操作员冻结审查。本文档及其引用均为零调用产物，**不构成真实 API 调用授权**。
**V1.0→V1.1 修订**（操作员审查意见五项全改）：
1. 新增**节点执行合同**（§三①′，附录 D）：输入=自身 doc_refs 原文+直接父节点输出，禁止隐式上下文；冻结五种 kind 提示词模板/输出 Schema/截断规则。
2. **评分规则严格化**（附录 B 重写）：事实-证据预设映射，VALUE/LOCALIZATION/SUPPORT 三项分离核验，Evidence Localization 与 Evidence Support 两个指标分列。
3. **RQ1 结论范围限制**（§一）：只声明"当前优化器可识别的缺陷"，不等同全部缺陷；合并前后任务文本全留痕供独立复核。
4. **生成重复处理**（§二）：记录三次 Raw DAG 结构哈希；完全相同时的结论范围限制条款；禁止事后重新生成。
5. **联合成功条件**（§四）：五条判定 + 预注册 Q 容差/C/L 口径与阈值；预算按离线 token 核算修正为 **70 调用 / 220K token / ¥0**（V1.0 的 65K 经真实文档字符数核算不敷使用，见 §五）。

---

## 一、研究问题与结论边界

**LLM 生成的初始 DAG 是否存在结构冗余或依赖缺陷？通过独立的 DAG 结构优化，能否在相同资源约束下改善复杂任务的终端质量与执行效率？**

| 编号 | 子问题 | 结论边界（预注册措辞限制） |
|---|---|---|
| RQ1 | 初始 DAG 质量 | 只回答"**存在多少可被当前优化器规则识别的结构缺陷**及类型分布"（重复任务/冗余依赖/可合并节点/无效引用）。优化器识别数 ≠ 全部缺陷数；语义级依赖错误不在其检出能力内，如需评估另行人工审计。 |
| RQ2 | 优化器有效性 | 识别→修复的转换率 + 必要依赖保留（T1 不变量类检查 + 合并操作独立复核）。 |
| RQ3 | 终端收益 | 同源配对下的 Q/C/L 方向（§四联合条件）。 |

**合并操作留痕要求**：每次 MERGE 保存合并前两个节点的完整任务文本与合并后文本于 change log，供事后独立复核；误合并作为优化器发现如实报告，不得静默。实体级/目标事实级等价性检查为已知局限（合并判定为必要非充分条件）。

## 二、设计：同源配对三组

```
生成（3 次独立，glm53flash，temperature=0，提示词=附录 A 冻结全文）:
  Raw-1, Raw-2, Raw-3
执行（9 run）:
  A_i = 原样执行 Raw-i           (i=1..3)  原始基线
  B_i = 原样执行 optimize(Raw-i)  (i=1..3)  结构优化（与 A_i 同源）
  C_j = 原样执行冻结 Reference DAG (j=1..3) 诊断性参照
```

- **A/B 同源配对**是本设计核心：排除 LLM 初始分解随机性对优化收益判断的干扰。
- **C 组身份**：人工定义的诊断性参照，**非理论最优、非 Gold**（无独立证据不得作此声称）。
- **temperature=0 重复处理**：保留 temperature=0，不为制造 DAG 差异而改参数。每次生成后立即计算**结构哈希**（节点集+边集规范化排序后 sha256，规范法冻结于 runner）。若三次完全相同：A/B 配对与优化收益结论仍然有效；但**不得声称已验证不同初始结构下的优化泛化能力**，报告中须原样披露三哈希。**禁止为增加差异而重新生成或改参重生成**。
- 优化器对 Raw-i 的 change log 兼作 RQ1 缺陷普查（零额外调用）。

## 三、实验约束（冻结条文）

### ① DAG 生成固定
模型 `glm53flash`、temperature=0、输出上限 2000 token；提示词**附录 A 全文冻结**（输入仅任务问题+三文档标题编号，不含正文）；结构约束：节点 ≤8、kind ∈ {extracts, timeline, reasoning, verification, report}、恰一个 report 终端、JSON schema 固定；生成结果无论合法与否原样保存，共 3 次调用。

### ①′ 节点执行合同（V1.1 新增，核心）
**每个节点的输入由且仅由两部分组成**：
1. 自身 `doc_refs` 声明文档的**全文原文**；
2. DAG 中**直接父节点**的执行输出（每父截断至 1500 字符，截断位置=保头部）。

**未声明的文档不得隐式注入；非直接父节点的信息不得通过任何隐藏上下文绕过依赖边。** 不同 DAG 的结构差异必须真实转化为信息流差异——否则依赖边失去意义，实验失效。Runner 必须为每个节点记录输入清单（文档 id 列表+父节点 id 列表+各部分字符数）入账，供审计验证合同遵守。

五种 kind 的提示词模板、输出 JSON Schema、输出 token 上限见**附录 D 冻结全文**；截断与上限汇总：

| kind | 输入构成 | 父输出截断 | 输出 token 上限 |
|---|---|---|---|
| extracts | doc_refs 全文 + 模板 | —（无父或仅任务） | 900 |
| timeline | doc_refs 全文 + 直接父输出 + 模板 | 1500 字/父 | 800 |
| reasoning | 直接父输出 + 模板 | 1500 字/父 | 600 |
| verification | 直接父输出 + 模板 | 1500 字/父 | 500 |
| report | 直接父输出 + 事实 id 清单（仅 id+类别，无期望值） + 模板 | 1500 字/父 | 1200 |

### ② 配对关系
B_i = optimize(Raw_i)，优化器代码冻结于 SHA `0e28bb1d…`；优化只减不增节点，|B_i| ≤ |A_i|；change log（含合并前后全文）入账。

### ③ 执行公平性（统一约束上限，不统一实际消耗）

| 项 | 值（三组一致） |
|---|---|
| 文档 | doc1=立案进展公告(2026-09-10, 651 字) / doc2=重大违法退市第四次风险提示(2026-10-09, 2444 字) / doc3=股价低于1元终止上市首次提示(2026-10-13, 3051 字)（三文档正文合计 6146 字，均为冻结文本） |
| 模型分配 | kind ∈ {extracts, timeline} → glm53flash；{reasoning, verification, report} → glm53；未知 kind → glm53 |
| 并发槽位 | glm53×2，glm53flash×2 |
| 单节点 | 单次调用，无重试/切换/Z/R/π |
| 单 run 截止 | 600 s（超时停止派发，INCOMPLETE_DEADLINE） |
| 全局预算 | Meter v2.2 硬停（¥0 现金） |
| 信息合同 | extracts 按 Extract V2 精神（date_role/evidence_quote），五 kind 模板见附录 D |

### ④ 终端评价（独立事实集 + 程序化分离核验）
- `E04_P2_REFERENCE_FACTS.json`（待冻结附件 1）：六类事实（立案原因与日期 / 风险提示次数与日期 / 退市类型判断 / 关键财务数据 / 股价面值事实 / 因果链），每条含 fact_id、category、expected_value、allowed_expressions、evidence_doc、**evidence_span（该文档内准确原文跨度）**、critical、value_match_rule。**在任何生成/执行调用之前冻结**，与 M7-3D 参考事实完全独立。
- 报告节点输出结构化 claim：`fact_id, value, evidence_doc, evidence_quote`（对不可判定事实允许 value="UNKNOWN"，不惩罚性扣分，按未覆盖计）。三组收到**完全相同**的事实 id 清单（仅 id+类别，无期望值），无差别泄漏。
- 评分三项分离（附录 B 全文）：**VALUE**（值匹配）/ **LOCALIZATION**（引用确在其所指文档原文）/ **SUPPORT**（引用与该事实的**预设证据跨度**重叠）。Localization 与 Support **两个指标分列报告**。SUPPORT 为冻结映射上的确定性核验（重叠判定规则见附录 B），**不声称语义级证据支持**——语义级评分不在本轮程序化范围内，如需另行设计。
- 盲化：评分器零 LLM 调用，输入仅脱敏 run_id；组别映射独立保存，分析阶段才合并。

### ⑤ Q/C/L 记录（每 run，Feedback Schema V1 字段映射）
Q：事实覆盖数/总数、localization 率、support 率、关键事实正确数、类别覆盖（6 类）、Q_terminal=covered/total。
C：总调用、总 token（in/out）、per-model、wasted_tokens（失败节点消耗）、现金 ¥0。
L：makespan_s、关键路径深度、截止期内完成。
结构：节点/边/深度/宽度 + 优化变更计数。可靠性：合法执行率、节点完成率。

### ⑥ 异常处理（全纳入，禁事后删除）
合法性门（执行前程序化判定入账）：环 / 无 report 终端 / 引用不存在文档 → `INCOMPLETE_DAG_ILLEGAL`（附缺陷明细），不执行，其配对 run 照常并在分析中标注配对残缺；孤儿/不可达等不阻碍执行的缺陷 → 原样执行并记入 RQ1 普查。
执行中：节点失败（contract/parse/transport/timeout）→ 不重试、下游 blocked、`INCOMPLETE_NO_RECOVERY`；超截止 `INCOMPLETE_DEADLINE`；预算触顶 `INCOMPLETE_BUDGET`（Meter v2.2 硬停）。
**任何 run 一律保留于结果文件**；剔除失败 run 属违规（M7-3F 教训）。

## 四、成功判定（预注册，含阈值）

**联合成功条件（五条同时满足才可认定"结构优化有收益"）**：
1. **Q 无实质性下降**：Q_terminal(B_i) ≥ Q_terminal(A_i) − 0.05（绝对值），且 **critical 事实不得减少**；
2. **C 或 L 至少一项改善**：C 改善 = run 总 token(in+out) 严格下降；L 改善 = makespan 严格下降（均以配对 B_i vs A_i 计）；
3. **另一项无不可接受恶化**：C 恶化 = token 增加 >15%；L 恶化 = makespan 增加 >25%（时延噪声大，阈值放宽）；
4. **可靠性不降**：合法执行率与节点完成率 B_i 不低于 A_i；
5. **方向一致性**：三对配对中 ≥2 对呈现一致收益方向。

三种虚假成功模式（任一出现即不得认定）：节点减少但关键事实丢失；更快但质量下降；质量微升但成本大增（>15% token 即"大增"）。
n=3 探索性定位：只做描述统计与配对方向计数，禁止 p 值与"统计显著/确认性优势"措辞。

## 五、预算（V1.1 修正：离线核算）

真实文档字符数：doc1=651、doc2=2444、doc3=3051（去空白正文）。按 §三①′ 合同逐节点核算（模板 500 字/节点、父输出截断 1500 字/父、输出上限如表、中文按期望 0.65 tok/字、最坏 1.0 tok/字）：

| 项 | 期望(0.65) | 最坏(1.0) |
|---|---|---|
| C 组单 run（6 节点实测结构） | 18,282 | 25,490 |
| 最坏 Raw 单 run（8 节点假设：4 extracts+timeline+reasoning+verification+report） | 24,488 | 34,071 |
| 3×C | 54,846 | 76,470 |
| 3×A（≤最坏 Raw） | 73,464 | 102,213 |
| 3×B（≤3×A） | ≤73,464 | ≤102,213 |
| 生成 3 次 | 4,500 | 4,500 |
| **合计上限** | **≈206,274** | **≈285,396** |

**V1.0 申请的 65K 经核算不敷使用（C 组三个 run 即需 ~55K）——正如操作员所料，平均量推算不可用。** 修正申请：**调用上限 70 / token 上限 220,000（期望 ~150K，覆盖期望情形最坏结构）/ 现金 ¥0**。Meter v2.2 全局硬停兜底；若触顶按 INCOMPLETE_BUDGET 如实截断入账。核算脚本随协议归档，冻结后不得改口径。**上述为预算申请，不构成授权。**

## 六、执行顺序
冻结 → 操作员明文 GO（批次名+调用上限+token 上限）→ 生成 Raw-1..3（结构哈希+合法性门+RQ1 普查）→ 9 run 静态执行 → 程序化盲评 → 配对方向分析 → 报告。中途不得修改已冻结规则；发现缺陷零调用审计后由操作员裁决。

## 七、冻结清单（hash-pinned）

| 件 | SHA/状态 |
|---|---|
| dag_optimizer.py | 0e28bb1d…（27/27 通过；M7 回归 34/34） |
| m8_p1_optimizer_tests.py | 9dd8f7f7… |
| E04_reference_dag.json | 369de52a…（C 组输入） |
| 本协议 V1.1 + 附录 A/B/D/E | 待冻结时哈希 |
| E04_P2_REFERENCE_FACTS.json | **待建**（附件 1；GO 前冻结，验收=每条事实有原文依据/准确跨度/匹配规则） |
| m8_p2_runner.py + 零调用模拟测试 | **待建**（附件 2；验收=附录 E 十项全过） |
| token 核算脚本 | 随协议归档 |

## 附录 A：DAG 生成提示词（冻结候选全文，V1.0 不变）

```
你是任务规划器。根据以下调查任务和文档清单，将任务分解为执行 DAG。

任务：调查*ST卓然从立案调查到退市风险的完整演变：立案原因与进展、
各次退市风险提示的触发条件与时间线、公司目前面临的退市类型判断。

可用文档：
- doc1: 上海卓然 关于公司立案调查进展暨退市风险提示公告（2026-09-10）
- doc2: 上海卓然 关于公司股票可能被实施重大违法强制退市的第四次风险提示公告（2026-10-09）
- doc3: 上海卓然 关于公司股票可能存在因股价低于1元而终止上市的首次风险提示（2026-10-13）

要求：
1. 节点数不超过 8 个；
2. 每个节点 kind ∈ {extracts, timeline, reasoning, verification, report}；
3. 恰好一个 report 节点作为唯一终端；
4. 每个节点声明其直接读取的文档（doc_refs），非抽取类节点可为空；
5. 依赖边只表达真实数据依赖；
6. 只输出 JSON，格式：
{"nodes": [{"id": "...", "task": "...", "kind": "...", "doc_refs": ["doc1", ...]}],
 "edges": [{"from": "...", "to": "..."}]}
```

## 附录 B：评分规则（V1.1 重写，随事实集冻结）

**事实条目 Schema**：`{fact_id, category, expected_value, allowed_expressions[], evidence_doc, evidence_span, critical, value_match_rule}`。value_match_rule ∈ {exact_string, numeric（去千分位/单位/全半角后精确数值比较，金额以万元计）, date（归一 YYYY-MM-DD）, set（元素齐全）}。

**claim 核验三项分离**（对每条 fact_id 取报告输出对应 claim）：
1. **VALUE**：claim.value 按 value_match_rule 与 expected_value/allowed_expressions 匹配。value="UNKNOWN" 或无 claim → 该事实 missing（计入未覆盖，无额外惩罚）。
2. **LOCALIZATION**（Evidence Localization 指标）：claim.evidence_quote 去空白后为 claim.evidence_doc 全文的子串。
3. **SUPPORT**（Evidence Support 指标）：claim.evidence_quote 与该事实冻结 evidence_span 去空白后**双向包含**（quote ⊇ span 或 quote ⊆ span）。此为**预设事实-证据映射上的确定性核验**，不称语义级支持判定。

**指标**：Coverage=VALUE✓数/总事实数；Localization 率=VALUE✓ 且 LOCALIZATION✓；Support 率=VALUE✓ 且 SUPPORT✓。三者分列报告，关键事实单列。评分器零 LLM 调用、输入仅 run_id（盲化由构造保证）。

## 附录 D：节点提示词模板（V1.1 新增，冻结候选全文）

通用头（所有 kind）：`【任务】{node.task}\n【输出要求】只输出 JSON，不输出其他文字。`

**extracts**（+`【文档】[{doc_id}] 原文全文`）：
```
从文档中提取与任务相关的关键事实。每条事实必须给出来自文档原文的证据引用。
输出：{"key_facts": [{"fact": "...", "value": "...", "date_role": "披露|收到|落款|处罚|交易|无", "evidence_quote": "...", "doc_id": "..."}]}
```
**timeline**（+`【文档】doc_refs 全文` +`【上游抽取结果】各直接父节点输出`）：
```
结合文档与上游抽取结果，按时间顺序构建事件时间线。日期必须标注 date_role。
输出：{"events": [{"date": "YYYY-MM-DD", "date_role": "...", "event": "...", "source": "doc_id|parent_node_id"}]}
```
**reasoning**（+`【上游输入】各直接父节点输出`）：
```
仅基于上游输入完成推理判断，不得引入上游未提供的信息。每个结论注明依据的父节点。
输出：{"conclusions": [{"claim": "...", "basis_parent": "node_id", "confidence": "high|medium|low"}]}
```
**verification**（+`【上游输入】各直接父节点输出`）：
```
核验上游各结论之间的一致性（日期、金额、因果）。逐项给出核验结果。
输出：{"verdict": "CONSISTENT|PARTIAL|INCONSISTENT", "checks": [{"check": "...", "result": "PASS|FAIL|UNVERIFIABLE", "note": "..."}]}
```
**report**（+`【上游输入】各直接父节点输出` +`【事实清单】[{fact_id, category}]×N（三组完全相同，无期望值）`）：
```
基于上游输入生成调查结论。对事实清单中每个 fact_id 给出一条结论；上游信息不足以判定的，
value 填 "UNKNOWN"，不得编造。evidence_quote 必须取自上游输入中出现过的原文。
输出：{"claims": [{"fact_id": "...", "value": "...", "evidence_doc": "doc1|doc2|doc3", "evidence_quote": "..."}], "summary": "..."}
```

## 附录 E：执行器零调用模拟测试（附件 2 验收标准，十项全过方可冻结）

1. 合法 DAG（参考 DAG）拓扑执行正常，节点执行顺序符合依赖；
2. 环检测 → INCOMPLETE_DAG_ILLEGAL；
3. 未知文档引用 → INCOMPLETE_DAG_ILLEGAL；
4. 节点合同失败（非 JSON/缺字段）→ NODE_FAILED_contract；
5. 上游失败后下游全部 blocked，run INCOMPLETE_NO_RECOVERY；
6. 并发槽位正确（glm53×2 / flash×2，超槽等待）；
7. 600 s 截止触发停止派发 → INCOMPLETE_DEADLINE（模拟时钟）；
8. 全局预算触顶硬停 → INCOMPLETE_BUDGET；
9. 所有失败 run 保留于结果文件（无删除路径）;
10. A/B 同源验证：B 的输入 DAG 哈希 == A 的输入 DAG 哈希经 optimize 后的输出哈希；
附：每节点输入清单（doc ids+父 ids+字符数）入账，验证执行合同无隐式注入。

## 附录 C：异常分类（入账枚举，V1.0 不变）

`DAG_ILLEGAL_CYCLE / DAG_ILLEGAL_NO_TERMINAL / DAG_ILLEGAL_UNKNOWN_DOC / NODE_FAILED_contract / NODE_FAILED_parse / NODE_FAILED_transport / NODE_FAILED_timeout / INCOMPLETE_DEADLINE / INCOMPLETE_BUDGET / COMPLETE`
