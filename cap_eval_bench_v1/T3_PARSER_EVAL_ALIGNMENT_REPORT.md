# T3 对齐报告：Conservative Parser ↔ E08/E05 客观事实评价规则

**日期**: 2026-10-31 | **任务**: T3（规则与实现的对齐审查，非开发）
**授权边界（已遵守）**: 零模型调用、零 GPU、零 API；不修改 Parser / E08/E05 冻结参考 / P0 评分器 / 历史账本；不产生正式 Q 标签；不触碰 P1 人工 Gold 门禁；本报告为唯一新增文件。
**方法**: 四份对齐对象全文通读 + 18 项零调用执行探针（只读导入 Parser，无任何写入）。

## 对齐对象版本指纹

| 对象 | SHA256（前 16 位） | 状态 |
|---|---|---|
| `integration/conservative_parser.py`（774 行） | `b740c377263226c3` | SPEC v2.6 实现，P1–P20 回归 20/20 |
| `CONSERVATIVE_PARSER_SPEC.md`（v2.6 冻结） | `e5aebd5222090d96` | 冻结 |
| `E08_OFQ_DESIGN.md`（v2.2-final） | `433b9e078cd8803d` | 冻结，T1 已 PASS 24/24 |
| `e08_ofq_test.py`（T1 执行器） | `c70b57d91f2ede9a` | 冻结 |
| `e05_ofq_test.py`（T4 执行器） | `ccf40246d1432ea5` | 冻结，T4 已 PASS 24/24 |

---

## 总结论（先回答操作员的核心问题）

**问题**：已修复的 Conservative Parser，能否真正按照 E08/E05 客观事实评价规则，产生一致、可信的节点质量反馈？

**分层回答**：

1. **原则层——对齐。** 两套机制共享同一保守判定哲学：不可证明 ≠ 可证伪（E08 `UNSUPPORTED` ↔ Parser `INSUFFICIENT_EVIDENCE`；E08 `CONTRADICTED` ↔ Parser `REFUSED`）；不做隐式换算（万元↔元、单位、时区）；不做实体消歧；保留 UNKNOWN。执行探针逐项确认（见任务一/二/三）。

2. **类型层——部分对齐。** Parser 7 类 TypedValue 中 `date`/`amount`/`entity`/`interval_days`（及 `text` 兜底）与 OFQ 事实的值核验规则**逐条等价**（探针 1–11 全部 CONFIRMED）；但 OFQ 需要的 `numeric_range`、`identifier`、`qualified_fact`、`status_fact`、日期子类型、人员职务、推导算术**不在类型系统内**。

3. **结构层——不对齐（本报告最重要的发现）。** Parser 的 claim 模型是**比较主张**（"一致/不一致"，面向 R10 换股比例复盘场景）；E08/E05 的评价对象是**原子谓词事实 + 跨文档推导**。执行验证：E08 式原子事实报告输入 `extract_claims()` 产出 **0 条 claims**；qualified_fact 陈述同样产出 **0 条**。注册表 `ITEM_KIND_REGISTRY` 仅 5 项（M&A 场景），OFQ 两案谓词共 18 种。

4. **因此**：Parser 在其设计职责（R10 比较主张解析）上已达成且无需继续修改；但它**不能直接当作 E08/E05 事实评价器使用**，也无需为此"继续修 Parser"。两套机制是**互补的两层**——Parser=模型输出主张层，OFQ=参考事实层——设计上在 P3 汇合。若未来要让可信质量信号进入联合调度（P5），需要的是一个**账本映射层**（OFQ 事实结构 → Parser 九字段 Binding）与**注册表扩展**，属于后续独立授权的工作，T3 依约不做。

---

## 任务一：事实类型对齐

### 类型系统对照表

| Parser TypedValue | 规范化/等价规则 | E08/E05 对应 | 对齐状态 | 探针 |
|---|---|---|---|---|
| `date` | 中文→ISO、`datetime.date` 日历验证、多候选→不可判定 | DATE_NORMALIZE / DATE_CALENDAR_VALID | **对齐** | ISO/中文/2026-02-31/多候选 4 项 CONFIRMED |
| `date`（子类型） | — | DATE_TYPE_AWARE（receipt/announcement/event/decision/signing 五子类） | **部分**：Parser 无日期子类型，B2 型"类型混淆"只能作为值错误被捕获 |
| `amount` | Decimal 精确 + 单位全等 + 负号保留 | DECIMAL_EXACT / UNIT_MATCH（F11–F14、E05-F11/F12） | **对齐** | 负数、大额、符号翻转、万元≠元 4 项 CONFIRMED |
| `entity` | NFC 规范化精确匹配，无别名替换 | FULL_NAME_MATCH / ENTITY_NOT_SUBSTITUTE / 实体层级 2.4 节 | **对齐**（值级）：全称≠同业、全称≠简称 CONFIRMED；**部分**（谓词级）：Parser 无"谓词-名称类型约束"（F8 只收全称、F2 只收简称），靠账本事实正确性间接保证 |
| `entity`（自然人） | 同上 | PERSON_ROLE_MATCH（姓名+职务，F16 安振山+董事长） | **部分**：Binding 无人员职务字段 |
| `interval_days` | 整数天数精确相等 | E05-D1 / E08-D1–D3 | **部分**：值比较对齐；**推导算术不在 Parser 范围**（`(end-start).days` 由 OFQ 侧计算） |
| `text` | NFC 精确 | qualified/status 事实的兜底 | **部分**：全短语精确匹配能令限定语丢失表现为"不匹配"，但无法区分 qualifier_lost / qualifier_escalation / 值错误 |
| `ratio` / `price` | 换股比例语法、元/股 | OFQ 无对应事实 | Parser 特有（R10 场景），非缺口 |
| —（不存在） | — | `numeric_range`（F11/F12 数学区间、RANGE_NORMALIZE、闭区间） | **缺口** |
| —（不存在） | — | `identifier`（F6 立案编号、F1 证券代码、F3 公告编号） | **缺口**；探针确认仅能以 text 兜底且无空白规范化 |
| —（不存在） | — | `qualified_fact`（F7"涉嫌"、F9"可能涉及"限定语不可丢失） | **缺口** |
| —（不存在） | — | `status_fact`（F10"尚未收到"状态翻转，C6） | **缺口** |

**中文数字日期**：E05-F16"二〇二六年九月四日"在 Parser `_norm_date_multi`（要求 ASCII 数字）下解析失败（探针 CONFIRMED）。E08/E05 全部 ASCII 日期不受影响。

## 任务二：证据规则对齐

| E08 规则（设计 §3.5） | Parser 对应实现 | 对齐状态 |
|---|---|---|
| DOC_ID_VALID（doc_id 须在文书中） | `source_doc not in evidence_docs` → `doc_not_in_evidence` → INSUFFICIENT | **对齐** |
| SHA256_MATCH（原始字节哈希比对） | `DocumentSnapshot.sha256` vs `Binding.source_doc_version` → `doc_version_mismatch` → INSUFFICIENT（P17 覆盖） | **对齐** |
| 文本读取：`read_bytes()` + `decode('utf-8')`，禁自动换行转换 | `DocumentSnapshot.from_file` 同法（另 `errors='replace'`、保留 BOM；对无 BOM 冻结文书行为一致） | **对齐** |
| SPAN_OFFSET_UNIT（Unicode 码点偏移，`[start,end)`） | Python `str` 切片、左闭右开 | **对齐** |
| span 越界/缺失 → 证据不完整（非模型错误） | `span_missing`/`span_out_of_bounds` → INSUFFICIENT（对应 B8→UNSUPPORTED） | **对齐** |
| SPAN_CONTENT_VERIFY（跨度原文包含声称值） | 类型化 span 核验（F25）：解析片段 + `typed_equal`，**比子串包含更严**（P20 覆盖） | **对齐（Parser 更强）** |
| SPAN_FROM_RAW（独立定位，非 Silver 自引用） | Parser 不定位 span——span 来自账本事实，Parser 只验证；独立定位是 OFQ T1/T4 执行器的职责 | **职责分层，非缺口**：两机制各管一段 |
| 多次出现→首现 + 上下文谓词核验（R7） | Parser 采用**唯一绑定**：候选 >1 → `ambiguous_binding` → INSUFFICIENT（拒绝任选，P11 覆盖） | **部分**：保守性等价（都不接受歧义），机制不同（首现+上下文 vs 唯一性） |
| 账本九字段（fid/version/operand_role/document_role/time_stage） | Parser Binding 完整要求（Fix 2A/2B/6）；E08/E05 事实结构仅含 value/span/doc/kind/unit/qualifier/predicate | **缺口（映射层）**：OFQ 事实 → Parser 账本事实的转换器不存在，是 P3 汇合前唯一的结构性缺件 |

**规范-实现偏差登记（新发现，未修复，留待独立授权）**：SPEC v2.6 规则 2 失败映射表要求 span 解析失败 → `REFUSED("span_type_mismatch")`、多候选 → `INSUFFICIENT("span_ambiguous_parse")` 两种状态；实现中 `typed_parse` 对两种情形均返回 None，统一落到 `span_ambiguous_parse` → INSUFFICIENT（`_bind_operand` 无 `span_type_mismatch` 标签，探针 CONFIRMED）。影响：span 覆盖纯文字（类型性错误）时被判 INSUFFICIENT 而非 REFUSED——方向偏保守，与"保留 UNKNOWN"原则不冲突，但与冻结 SPEC 文字不一致。

## 任务三：三态判定对齐

### 状态体系对照

| E08 维度 | E08 状态 | Parser 对应 | 保守原则一致性 |
|---|---|---|---|
| 证据判定 | CONTRADICTED（可证伪：文书写 X 候选说 Y） | REFUSED（`span_value_mismatch`/`type_mismatch`/`wrong_source_doc`/角色 FAIL） | **一致**：均有文书侧可验证依据才判死 |
| 证据判定 | UNSUPPORTED（无法从文书找到依据） | INSUFFICIENT_EVIDENCE（`operand_not_in_ledger`/`document_unavailable`/歧义） | **一致**：不可证明 ≠ 可证伪 |
| 参考一致性 | MATCHED_REFERENCE | CREDITED（+RELEVANT→SCORED） | **一致**：双层判定进一步区分"事实成立"与"口径相关" |
| 完整性 | OMITTED（关键事实缺失，B10） | **无对应**：Parser 是主张驱动，不检测缺席 | 缺口（终态层职能，属评价器非 Parser） |
| 完整性 | UNKNOWN_ABSTAINED（正确拒判，C3） | **无对应**：无弃权奖励状态；需 U1 类事实注册表配合 | 缺口（同上） |
| — | — | AMBIGUOUS / UNKNOWN_SCOPE / CONTRACT_CONFLICT | Parser 特有（口径治理），OFQ 无此维度，非缺口 |

### 保守原则逐条验证（探针 + 测试回放）

| 原则 | E08/E05 行为 | Parser 行为 | 结论 |
|---|---|---|---|
| 不替模型推理 | 仅解析比对候选值 | 仅绑定账本已有事实，不生成新值 | 一致 |
| 不做隐式换算 | 万元≠元、无时区/工作日换算 | `typed_equal` 单位全等（探针 CONFIRMED） | 一致 |
| 不做实体消歧 | 全称/简称/同业三级拒绝（探针 CONFIRMED） | NFC 精确匹配无别名 | 一致 |
| 保留 UNKNOWN | UNSUPPORTED 终态、C 组边界 | INSUFFICIENT/AMBIGUOUS/UNKNOWN_SCOPE 三处保留 | 一致 |
| 不可证 ≠ 可证伪 | B6 qualifier_lost → UNSUPPORTED（非 CONTRADICTED，v2.2-R2） | 值不匹配且无文书反证 → operand_not_in_ledger → INSUFFICIENT | **一致（语义等价路径）**：删除"涉嫌"的全短语在账本中无匹配 → 不可证明 → INSUFFICIENT ≈ UNSUPPORTED |
| 矛盾三态优先级 | — | 任一 MISMATCH→FALSE > 任一 UNKNOWN→UNKNOWN > 全 MATCH+相反→TRUE（F26，P19 覆盖） | Parser 特有，无冲突 |

**一处严重度分歧（登记，非错误）**：E08-C6"尚未收到→已收到"判 **CONTRADICTED**（文书明确写"尚未收到"，可证伪）；Parser 中该候选同样因全短语不匹配落入 INSUFFICIENT。根因：Parser 不做否定/反义检测，文书侧断言比对是 OFQ 执行器能力。该分歧不影响保守性（都不会误接受），只影响错误严重度标签。

## 任务四：E08/E05 事实规则 → Parser 映射表

可映射性三档：**端到端**（类型✓+注册表✓+可验证）/ **类型级**（TypedValue 可承载，注册表缺项 → `item_not_registered` → INSUFFICIENT）/ **不可映射**（类型缺失或结构不兼容）。

### E08（17 事实 + U1 + D1–D3）

| 事实 | 类型/谓词 | 映射档位 | 说明 |
|---|---|---|---|
| F8 立案对象（法定全称） | entity_subject | **端到端** ✓ | entity + `entity_identity` 注册项；B1 替换被拒（探针 CONFIRMED）。两案中唯一全通事实 |
| F4 收到日期 | date_receipt | 类型级 | date 类型全对齐；注册表无 date_receipt |
| F5 发文机关 | entity_attribute | 类型级 | entity 对齐；注册表缺项 |
| F13/F14 净利润点值 | numeric_point | 类型级 | amount 全对齐（含负数）；注册表语义项为 penalty_amount，不匹配 |
| F15/F17 日期（event/announcement） | date | 类型级 | 同 F4 |
| F1/F3 代码/公告编号 | entity_attribute | 不可映射 | 无 identifier 类型 |
| F2 证券简称 | entity_attribute | 不可映射 | 无谓词-名称类型约束 |
| F6 立案编号 | identifier | 不可映射 | 无 identifier 类型 |
| F7/F9 限定语事实 | qualified_fact | 不可映射 | 无 qualifier 语义 |
| F10 结论状态 | status_fact | 不可映射 | 无状态翻转检测 |
| F11/F12 净利润区间 | numeric_range | 不可映射 | 无区间类型 |
| F16 董事长 | entity_person | 不可映射 | 无姓名+职务 |
| U1 | unknown | 不可映射 | 无弃权状态 |
| D1–D3 | 推导 | 类型级（值比较） | interval_days 类型在；算术验证不在 |

### E05（16 事实 + D1 + U1）

| 事实 | 映射档位 | 说明 |
|---|---|---|
| F8 立案对象（福建纳川管材…） | **端到端** ✓ | 同 E08-F8 |
| F16 签署日期 | 注册表✓ 但**被阻断** | `signing_date`→date 注册项命中；"二〇二六年九月四日"中文数字解析失败（探针 CONFIRMED）→ INSUFFICIENT |
| F4/F9/F10 日期三类 | 类型级 | 同 E08 |
| F11/F12 负数大额（元） | 类型级 | amount 负数支持已验证 |
| F13 审计机构（全称） | 类型级 | entity 对齐；注册表缺项 |
| F14/F15 审计意见类型 | 不可映射 | 无语义类别核验 |
| F1/F2/F3/F5/F6/F7 | 不可映射 | 同 E08 对应类型 |
| D1 跨文档 163 天 | 类型级 | 值可比；算术在 OFQ 侧 |
| U1 | 不可映射 | 同 E08 |

**覆盖率统计**：E08+E05 共 33 条事实级条目——端到端 2 条（两案 F8）+ 1 条被解析阻断（E05-F16）；类型级 11 条；不可映射 19 条。端到端覆盖率 **2/33（6%）**，类型级以上 **14/33（42%）**。

## 任务五：差异清单（已实现 / 部分实现 / 尚未实现）

### 已实现且对齐（9 项，均有探针或测试编号背书）

1. 日期规范化（中文→ISO）+ 真实日历验证 + 多候选保守化（探针 4 项；P10b）
2. 金额 Decimal 精确 + 单位全等 + 负号保留 + 无隐式换算（探针 4 项）
3. 实体 NFC 精确匹配 + 三类替换拒绝（探针 2 项）
4. 文档字节级 SHA256 版本验证（P17）
5. doc_id ∈ 证据集合检查（`doc_not_in_evidence`）
6. span 码点偏移/左闭右开/越界→INSUFFICIENT（P12a/b；B8 等价）
7. span 类型化精确核验优于子串包含（P20）
8. 字节读取无换行转换（与 E08 §3.5 读取规范一致）
9. 不可证明≠可证伪的全链路保守分界（REFUSED/INSUFFICIENT ↔ CONTRADICTED/UNSUPPORTED）

### 部分实现（7 项）

1. 日期子类型（DATE_TYPE_AWARE）——类型在、子类型不在
2. 谓词-名称类型约束（实体层级 2.4 节）——值级在、谓词级不在
3. 人员职务（PERSON_ROLE_MATCH）——姓名在、职务不在
4. 多次出现处理——唯一绑定 vs 首现+上下文，保守性等价、机制不同
5. interval_days——值比较在、推导算术不在
6. qualified_fact——全短语不匹配能拦截、不能分类（lost/escalation）
7. 注册表覆盖——5/18 谓词，全部 OFQ 新谓词未注册

### 尚未实现（8 项，按对 P3/P5 汇合的阻断度排序）

1. **OFQ 事实 → Parser 账本的映射层**（九字段 Binding 转换器）——两套机制汇合的唯一结构性缺件
2. numeric_range 类型（区间端点、数学排序、闭区间）
3. identifier 类型（编号/代码规范化匹配）
4. qualifier 语义（限定语保留/升级分类：B6/B11/C4/C5）
5. status_fact 翻转检测（C6 类可证伪判 CONTRADICTED 的能力）
6. OMITTED / UNKNOWN_ABSTAINED（完整性/弃权终态——属评价器层职能）
7. 推导算术验证（B9 类 `(end-start).days` 核验）
8. 中文数字日期解析（E05-F16 阻断点）

### 规范-实现偏差登记（1 项，本报告新发现）

- `span_type_mismatch`（REFUSED）与 `span_ambiguous_parse`（INSUFFICIENT）在实现中合并为后者——方向偏保守，与冻结 SPEC §规则2 文字不一致。**T3 不修复**；是否修属于 Parser 冻结变更，需独立授权。

---

## 对后续路线的含义（陈述，不启动）

1. **Parser 无需继续修改**：其 R10 职责（比较主张解析）已由 P1–P20 20/20 回归闭环；上述缺口不是"缺陷"而是"职责边界"。
2. **T3 后暂停评价基础设施扩展**（按操作员指示）：E08/E05-OFQ 已 PASS，Parser 已对齐审计，扩展第三案例无增量信息。
3. **P3 汇合的前置件**＝差异清单"尚未实现"第 1 项（映射层）+ 注册表扩展——但按治理顺序，P1 人工 Gold 仍在前（P2/P3 被阻塞），映射层工作应排在 P1 之后、P3 之前。
4. **可信质量信号进入联合调度（P5/TGV）**是主线科学问题：同任务/预算/截止期/异常条件下，(Z,R,π) 联合调度能否优于 π-only、R-only、Static。T3 的贡献是把"什么信号可信、以什么口径进入调度"钉死：客观事实层（OFQ 三维状态）与主张层（Parser 双层判定）各自的可信边界现已成文。

**T3 结论**：对齐审计完成，两套机制原则一致、类型层 42% 可映射、结构层互补而非包含；无新增缺陷需立即处理；唯一规范-实现偏差已登记待裁。零调用、零修改、单一交付物，任务关闭。

---

## ERRATUM（2026-10-31 append-only，回应操作员跨报告不一致裁定）

操作员指出：本报告将 P11、P20 列为覆盖项，而审计基线包指出 P11 缺失、P20 断言不足。核查结论：**两份报告引用的是同一版本测试文件**（两者指纹表均为 `9219b908…`），不存在版本漂移；不一致源于本报告的三处引用/表述缺陷，更正如下：

1. **第 67 行"（拒绝任选，P11 覆盖）"**——P11 在测试文件中不存在。歧义绑定行为的实际覆盖测试为 **P10b**（重复 f3 → `ambiguous_binding` → INSUFFICIENT）。行为结论（唯一绑定、拒绝任选）不变，引用更正为 P10b。
2. **第 65/147 行"（P20 覆盖）"**——P20 存在但断言仅为 `≠CREDITED`（弱断言，本次复现实测 INSUFFICIENT + `span_ambiguous_parse`）。类型化 span 核验的强覆盖实为 **P12c**（`span_value_mismatch` → REFUSED）。"Parser 比子串包含更严"的结论不变，但应由 P12c 背书；P20 的断言强度问题见审计基线包发现 2。
3. **第 11/180 行"P1–P20 回归 20/20"**——该表述易误导。20/20 是对**实有 20 个断言**的通过；SPEC §八矩阵中 P9a–e、P11、P13a–f、P16、P18 五组未实现（审计基线包发现 1），测试计划未全覆盖。

本勘误不改变 T3 的对齐结论（相关行为主张由 P10b/P12c 及 18 项探针继续背书），但引用准确性以本节为准。
