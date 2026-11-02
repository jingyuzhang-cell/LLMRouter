# 执行器保守解析机制设计方案（CONSERVATIVE PARSER SPEC v2.6）

**日期**: 2026-10-30 | **修订**: v2.6（落实操作员第五轮审查 F23–F28 六项修正）
**状态**: 设计修订后待最终冻结，**未经授权不实施**
**前版**: v2.5（F18–F22 已落实）；v2.6 补充 entity TypedValue（F23）、去重加入 conclusion（F24）、span 类型化精确核验（F25）、C2 角色唯一绑定与三态优先级（F26）、修正 P19 并增 R1 缺失测试（F27）、补全规则 3/5 独立正文（F28）。

---

## 一、问题定义（不变）

模型输出中正确结论与错误结论并存于不同表达层，解析器需要保守地提取可辩护的结论，同时拒绝不可辩护的。解析器须区分"主张在事实层面是否成立"与"主张是否符合当前任务合同要求的比较口径"——二者独立判定。

## 二、四条冻结原则（不变）

1. **不替模型推理**
2. **事实绑定来源**
3. **不纠正选错的操作数**
4. **保留 UNKNOWN**

## 三、双层判定体系（不变，v2.4 冻结）

| 维度 | 状态集 |
|---|---|
| **factual_verdict** | CREDITED / REFUSED / INSUFFICIENT_EVIDENCE / AMBIGUOUS |
| **task_relevance** | RELEVANT / NOT_RELEVANT / UNKNOWN_SCOPE / CONTRACT_CONFLICT |

**计分矩阵**：

| factual \ task | RELEVANT | NOT_RELEVANT | UNKNOWN_SCOPE | CONTRACT_CONFLICT |
|---|---|---|---|---|
| **CREDITED** | SCORED | NOT_SCORED_VERIFIED | NOT_SCORED_SCOPE_UNKNOWN | NOT_SCORED_CONTRACT_CONFLICT |
| **REFUSED** | REFUSED | REFUSED | REFUSED | REFUSED |
| **INSUFFICIENT** | INSUFFICIENT | INSUFFICIENT | INSUFFICIENT | INSUFFICIENT |
| **AMBIGUOUS** | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS | AMBIGUOUS |

**事实状态优先级**（正式冻结）：REFUSED > INSUFFICIENT_EVIDENCE > AMBIGUOUS > CREDITED

**三层状态体系**：内部传播（refused/held/unaffected）、对外事实（四态）、计分（SCORED/NOT_SCORED_*/四态）。三层不得混用。

## 四、统一绑定 Schema（v2.5 冻结 + **v2.6 修正：entity 类型 + DocumentSnapshot**）

### 九字段 Binding

```
Binding = {
    "fid":                 str,
    "source_doc":          str,
    "source_doc_version":  str,      # 完整 SHA256（64 字符）
    "fact_kind":           str,
    "canonical_value":     TypedValue,
    "span":                [int, int],
    "operand_role":        OperandRole,
    "document_role":       DocumentRole,
    "time_stage":          TimeStage
}
```

### TypedValue 类型体系（**v2.6 修正——F23：增加 entity**）

```
TypedValue = {
    "kind":  str,   # ratio | price | date | interval_days | amount | entity | text
    "value": str,   # 类型内规范化精确表示
    "unit":  str    # 仅 price/amount 使用
}
```

**各类型规范化和等价判定规则**：

| kind | 规范化方式 | 等价判定 | 禁止的隐式换算 |
|---|---|---|---|
| **ratio** | Decimal 数值（去尾零）；`1:X` 语法仅限换股比例（如"1股换0.1335股"），做比例语法→Decimal 转换后比较 | Decimal 精确相等 | 不转百分比；不与 price 互换 |
| **price** | Decimal + 币种/单位 | 数值+币种+单位**全部**相同 | 万元↔元不换算除非合同授权 |
| **date** | ISO 8601（YYYY-MM-DD）；中文日期规范化为 ISO | 日期精确相同 | 不做时区转换 |
| **interval_days** | 整数天数 | 整数精确相等 | 不做工作日/自然日换算 |
| **amount** | 同 price | 同 price | 同 price |
| **entity** | **NFC 规范化 + 精确匹配**；不做简称/全称替换 | NFC 规范化后字符串精确相等 | 不做实体消歧或别名替换 |
| **text** | Unicode NFC 规范化 | 精确匹配 | 不做同义词替换 |

**ratio 方向限定**：`1:0.1335` 与 `0.1335` 的等价仅适用于**换股比例**语法（1 股换取 X 股）；一般数学比例（如 1:2 vs 0.5）不经合同授权不做等价转换。

### DocumentSnapshot 接口（**v2.6 新增**）

```
DocumentSnapshot = {
    "raw_bytes":  bytes,   # 原始文件字节（含 BOM、原始换行符）
    "doc_text":   str,     # UTF-8 解码后文本（BOM 保留为 U+FEFF）
    "sha256":     str      # SHA256(raw_bytes) 完整十六进制
}
```

- `raw_bytes` 用于哈希计算与版本验证
- `doc_text` 用于 span 核验
- `sha256` 用于与 Binding.source_doc_version 比较
- 解码方式：UTF-8，检测 BOM 但**保留 U+FEFF**（不使用 `utf-8-sig` 等剥除 BOM 的编解码器）

### span 坐标规范（不变，v2.5 冻结）

`[start, end)` 左闭右开；Unicode 码点偏移；保留原样。

## 五、五条规则的完整独立执行契约

### 规则 1：明确结论提取 + 多来源处理（**v2.6 修正——F24：去重加入 conclusion**）

**执行流程**：

```
extract_claims(node_output) → List[RawClaim]

输入源扫描：
  1. comparisons 结构化字段
  2. report 自由文本
  3. new_facts 派生事实

RawClaim = {
    "source_layer": ...,
    "item": str | null,
    "conclusion": "一致" | "不一致" | null,
    "operand_values": [str, str] | null,
    "comparison_scope": str | null,
    "model_declared_scope": str | null
}
```

**多来源去重条件（v2.6 修正：六条件，含 conclusion）**：

两条 RawClaim 合并为同一主张，当且仅当以下**全部**相同：
1. `item`（比较对象）
2. 按 operand_role 对应的 TypedValue
3. `comparison_scope`（比较口径）
4. `time_stage`
5. `document_role`
6. **`conclusion`（结论）**

**如果结论相反**（一条"一致"一条"不一致"），即使其余五项完全相同，也**不得合并**——保留为独立主张，交给规则 4 判定是否构成矛盾。

### 规则 2：操作数唯一绑定与精确匹配（**v2.6 修正——F25：span 从子串包含改为类型化精确核验**）

**执行流程**：

```
verify_operands(raw_claim, ledger, evidence_docs, doc_snapshots) →
    {factual_status, bindings, refusal_reasons}
```

步骤 S1–S4（不变，v2.5 冻结），但 **S3.d 的 span 核验方式修正**：

**span 核验（v2.6 重写——F25，含失败状态精确映射）**：

```
verify_span(binding, doc_snapshot) → PASS | REFUSED | INSUFFICIENT_EVIDENCE

  # 前置检查（技术性不可用 → INSUFFICIENT，非模型错误）
  如果 doc_snapshot 为 None 或 doc_text 不可获取：
      → INSUFFICIENT_EVIDENCE（reason: "document_unavailable"）
  如果 binding.source_doc_version ≠ doc_snapshot.sha256：
      → INSUFFICIENT_EVIDENCE（reason: "doc_version_mismatch"）
  如果 binding.span 为 None 或 span 越界：
      → INSUFFICIENT_EVIDENCE（reason: "span_missing" / "span_out_of_bounds"）

  # 类型化核验（内容不匹配 → REFUSED，属模型/绑定错误）
  fragment = doc_snapshot.doc_text[binding.span[0] : binding.span[1]]
  parsed = TypedParse(fragment, binding.canonical_value.kind)

  如果 parsed 成功且 TypedEqual(parsed, binding.canonical_value)：
      → PASS
  如果 parsed 成功但 TypedEqual 不通过（值不同）：
      → REFUSED（reason: "span_value_mismatch"）
  如果 parsed 失败（fragment 无法解析为该类型）：
      → REFUSED（reason: "span_type_mismatch"）
  如果 parsed 成功但解析出多个候选值（无法唯一确定）：
      → INSUFFICIENT_EVIDENCE（reason: "span_ambiguous_parse"）

  TypedParse 规则：
    ratio：  从 fragment 中提取比例模式（含换股比例语法），Decimal 化
    price：  从 fragment 中提取价格模式（数值+币种+单位）
    date：   从 fragment 中提取日期（含中文日期→ISO 转换）
    entity： 从 fragment 中提取实体名称，NFC 规范化
    interval_days：从 fragment 中提取整数天数
    amount： 从 fragment 中提取金额模式
    text：   fragment 本身作为 text
```

**失败状态映射总结**：

| 情形 | 最终状态 | 理由 |
|---|---|---|
| 文档不可获取 | INSUFFICIENT_EVIDENCE | 技术性不可用，非模型错误 |
| 文档版本不匹配 | INSUFFICIENT_EVIDENCE | 证据来自不同版本，非模型错误 |
| span 缺失 / 越界 | INSUFFICIENT_EVIDENCE | 证据不完整，非模型错误 |
| span 解析成功但值不同 | **REFUSED** | 模型/绑定明确绑定了错误数值 |
| span 类型与声明类型不匹配 | **REFUSED** | 绑定类型错误 |
| span 解析出多个候选值 | INSUFFICIENT_EVIDENCE | 无法唯一确定，非明确错误 |

**核验失败的示例**：
- span 覆盖一整段文字，其中碰巧包含 "0.1339" 但 Binding 绑定的是 "0.1335" → TypedParse 得到 0.1339 ≠ 0.1335 → FAIL
- span 对应 "37.59元/股" 但 Binding.canonical_value 是 ratio 类型 → TypedParse 按 ratio 解析失败 → FAIL

**其他检查项**（不变）：source_doc ∈ evidence_docs、source_doc_version 匹配、两操作数 source_doc 不同、唯一绑定。

### 规则 3：文书角色验证（**v2.6 修正——F28：三态返回 + 完整处理**）

```
role_check(claim, binding_A, binding_B) → PASS | FAIL(reason) | INSUFFICIENT(reason)
```

**类型注册表**：

| item 类型 | 所需 fact_kind |
|---|---|
| exchange_ratio | ratio |
| signing_date | date |
| penalty_amount | amount |
| entity_identity | entity |
| interval_days | interval_days |

**三维角色枚举**（不变，v2.5 冻结）：
- OperandRole: initial_plan | adjusted_plan | implementation_result | announcement | execution_result
- DocumentRole: plan_document | listing_document | penalty_document | notice_document | announcement_document
- TimeStage: initial_pricing | post_adjustment | pre_announcement | post_announcement | execution_phase

**执行步骤与返回状态**：

| 检查 | 结果 | 返回 |
|---|---|---|
| claim.item 不在类型注册表中 | 未知 item 类型 | INSUFFICIENT("item_not_registered") |
| binding_A.fact_kind ≠ 所需 kind | 类型不匹配 | FAIL("fact_kind_mismatch") |
| binding_B.fact_kind ≠ 所需 kind | 类型不匹配 | FAIL("fact_kind_mismatch") |
| binding_A.document_role 为空 | 角色缺失 | INSUFFICIENT("document_role_missing") |
| binding_B.document_role 为空 | 角色缺失 | INSUFFICIENT("document_role_missing") |
| binding_A.operand_role 为空 | 角色缺失 | INSUFFICIENT("operand_role_missing") |
| binding_B.operand_role 为空 | 角色缺失 | INSUFFICIENT("operand_role_missing") |
| 全部通过 | — | PASS |

### 规则 4：矛盾判定（**v2.6 修正——F26：C2 角色唯一 + 三态优先级**）

#### C1–C5 + R1 完整定义

**C1 比较对象相同**：`item` 精确匹配。无法判定：任一为 null。

**C2 两侧操作数按角色对应关系的值相同（v2.6 修正）**

```
c2_check(claim_A, claim_B) → MATCH | MISMATCH | UNKNOWN

  前提：每条主张中每个必需 operand_role 唯一对应一个 Binding。
  - 零个绑定该角色 → UNKNOWN
  - 多个绑定该角色 → 绑定歧义，整体 UNKNOWN（不得任选）

  对每个 operand_role r：
    val_A = A 中 operand_role=r 的 TypedValue
    val_B = B 中 operand_role=r 的 TypedValue

    如果 val_A 和 val_B 均存在且唯一：
      TypedEqual(val_A, val_B) → 该角色匹配
      否则 → 该角色不匹配 → C2 = MISMATCH
    如果任一缺失或多于一个 → C2 = UNKNOWN

  全部角色匹配 → C2 = MATCH
```

**TypedEqual 按类型分派**：

| kind | 比较方式 |
|---|---|
| ratio | Decimal 精确相等 |
| price / amount | Decimal + 币种 + 单位 全部相等 |
| date | ISO 8601 日期精确相等 |
| interval_days | 整数精确相等 |
| entity | NFC 规范化后字符串精确相等 |
| text | NFC 规范化后字符串精确相等 |

**C3 时间状态相同**：按 operand_role 对应比较 time_stage。无法判定：任一为 null。

**C4 文书角色对应关系相同**：按 operand_role 对应比较 document_role 对应模式。无法判定：任一为 null。

**C5 比较口径相同**：`comparison_scope` 精确匹配。无法判定：任一为 null。

**R1 结论相反**：一条"一致"另一条"不一致"。无法判定：任一为 null。

#### 三态判定优先级（**v2.6 冻结——F26**）

```
def contradiction(claims):
    results = [c1_check(...), c2_check(...), c3_check(...), c4_check(...), c5_check(...)]

    if any(r == MISMATCH for r in results):
        return FALSE        # 至少一项明确不匹配 → 排除矛盾

    if any(r == UNKNOWN for r in results) or r1_check(...) == UNKNOWN:
        return UNKNOWN      # 某项无法判定 → 暂缓

    if r1_check(...) == OPPOSITE:
        return TRUE         # 全部匹配 + 结论相反 → 真正矛盾

    return FALSE            # 全部匹配 + 结论不相反 → 非矛盾
```

**优先级顺序**：任一 MISMATCH → FALSE（明确排除）> 任一 UNKNOWN → UNKNOWN（暂缓）> 全 MATCH + R1 相反 → TRUE。

**互斥性保证**：三态结果互斥，不可能同时为 TRUE 和 UNKNOWN。

### 规则 5：合同口径解析与模型操作数验证（**v2.6 补全独立正文——F28**）

**过程 1：合同口径解析**

```
resolve_scope(task_contract, silver_reference) →
    {scope: str | null, specified: bool, conflict: bool, source: str}

优先级与冲突处理（五种情形完整枚举）：

  | 情形 | task_contract | silver_reference | scope | specified | conflict | source |
  |---|---|---|---|---|---|---|
  | 双方一致 | 指定口径 A | 指定口径 A（相同） | A | true | false | "both" |
  | 双方冲突 | 指定口径 A | 指定口径 B（不同） | null | false | **true** | "conflicting" |
  | 仅任务合同 | 指定口径 A | 未指定/null | A | true | false | "task_contract" |
  | 仅 Silver | 未指定/null | 指定口径 B | B | true | false | "silver_reference" |
  | 双方均未指定 | 未指定/null | 未指定/null | null | false | false | "none" |

单侧缺失处理（明确规则）：
  - 仅一方指定 → **采用已指定方的口径**（specified=true, conflict=false）
  - 双方均未指定 → **scope=null, specified=false** → 所有主张 task_relevance=UNKNOWN_SCOPE
  - 解析器**不自行选择或推测**任何口径

冲突处理：
  conflict=true → task_relevance=CONTRACT_CONFLICT（独立状态）
  解析器不自行选择哪个口径是"正确的"
  factual_verdict 不受影响
```

**过程 2：模型操作数事实验证**

```
verify_model_operands(claim, bindings) →
    PASS | FAIL(internal_inconsistency) | INSUFFICIENT

  - 模型声称使用某种口径（model_declared_scope 非空）+ 绑定的操作数与该口径一致 → PASS
  - 模型声称使用初始口径 + 绑定的是调整后口径的操作数 → FAIL（内部不一致）
    → factual=REFUSED, reason="internal_inconsistency"
  - model_declared_scope 为空 → 跳过此检查（无法判定内部一致性）
  - 操作数证据不足 → INSUFFICIENT
```

**过程 3：任务相关性判定**

```
task_relevance(claim, resolved_scope) →
    RELEVANT | NOT_RELEVANT | UNKNOWN_SCOPE | CONTRACT_CONFLICT

  - resolved_scope.conflict=true → CONTRACT_CONFLICT
  - resolved_scope.specified=true + claim.comparison_scope == resolved_scope.scope → RELEVANT
  - resolved_scope.specified=true + claim.comparison_scope ≠ resolved_scope.scope → NOT_RELEVANT
  - resolved_scope.specified=true + claim.comparison_scope=null → UNKNOWN_SCOPE
  - resolved_scope.specified=false → UNKNOWN_SCOPE
```

## 六、解析器输出格式（不变，v2.5 结构 + v2.6 TypedValue）

结构与 v2.4/v2.5 相同。`operands` 中 Binding 的 `canonical_value` 为 TypedValue 对象。`contradiction_checks[]` 为顶层数组。

## 七、对 R10 三型失败的预期行为（不变）

| Run | v2.6 预期 |
|---|---|
| r1 | INSUFFICIENT |
| r2 | 声称初始但操作数为调整后 → REFUSED；明确说调整后 → NOT_SCORED_VERIFIED |
| r3 | A=SCORED, B=NOT_SCORED_VERIFIED, f17=REFUSED |

## 八、零调用测试计划（v2.6：P1–P20）

| 测试 | 内容 | 预期 | 职责 |
|---|---|---|---|
| P1 | r3 完整回放 | A=SCORED, B=NOT_SCORED_VERIFIED, f17=REFUSED | 真实数据 |
| P2 | 无歧义"不一致"自由文本 | SCORED | 基准 |
| P3 | 声称初始但操作数为调整后 | REFUSED（内部不一致） | F12 |
| P4 | 完整六条件矛盾 | 全 REFUSED | 完整矛盾 |
| P5 | 空输出 | INSUFFICIENT | 边界 |
| P6 | E1 350天派生 | 不受影响 | 隔离 |
| P7 | 分阶段比较 | A=SCORED, B=NOT_SCORED_VERIFIED | 双层 |
| P8 | 合同未指定+多候选 | AMBIGUOUS + UNKNOWN_SCOPE | 口径歧义 |
| P9a–e | 矛盾条件变异（C1–C5 各一项 MISMATCH） | 各→FALSE | 逐条件 |
| P10a | 声明比较比例，引用价格 | REFUSED | 类型化 |
| P10b | 无类型数值+双候选 | INSUFFICIENT | 唯一绑定 |
| P11 | 多 fid 同值 | INSUFFICIENT | 唯一绑定 |
| P12a | span 缺失 | INSUFFICIENT | S2 |
| P12b | span 越界 | INSUFFICIENT | S3 |
| P12c | span 类型化核验不匹配 | REFUSED | S4（F25） |
| P13a–e | C1–C5 各一字段缺失 | UNKNOWN，主张 held | F2 |
| **P13f** | **R1 缺失（conclusion=null）** | **UNKNOWN**，主张 held | F26（R1 缺失） |
| P14 | 合同冲突 | CONTRACT_CONFLICT，事实独立 | F15 |
| P15 | 角色错误+span 缺失 | REFUSED（优先级） | 优先级 |
| P16 | TRUE+UNKNOWN 并存 | TRUE 双方 REFUSED；其余 held | 传播 |
| P17 | 文档版本变化 | INSUFFICIENT | F13 |
| P18 | 多条 UNKNOWN 关联 | 该主张不 CREDITED | 多关联 |
| **P19** | **角色交换+结论相反**：A=(init→0.1335, impl→0.1339, 不一致)，B=(init→0.1339, impl→0.1335, 一致) | C2=MISMATCH→FALSE→非矛盾→两条独立判定 | F20+F27 |
| **P20** | **span 覆盖宽泛段落**：span 覆盖一整段，其中碰巧含正确数值但 Binding 绑定的是不同事实 | TypedParse(fragment) ≠ canonical_value → **REFUSED** | F25 |

**P19 详细设计（v2.6 修正——F27：结论必须相反）**：

```
A: initial_plan=0.1335, implementation=0.1339, conclusion=不一致
B: initial_plan=0.1339, implementation=0.1335, conclusion=一致

C1= MATCH（item 同）
C2= MISMATCH（initial_plan 角色值 0.1335≠0.1339）
C3~C5= MATCH（假设其余条件均满足）
R1= OPPOSITE（不一致 vs 一致）

判定：C2=MISMATCH → FALSE（不构成矛盾）
→ 两条独立进入规则 2/3/5

验证点：如果 C2 实现为错误的集合比较（{0.1335,0.1339}={0.1339,0.1335}→MATCH），
则 C1~C5 全 MATCH + R1 OPPOSITE → TRUE（误判为矛盾）→ 两条均被 REFUSED → 测试 FAIL
因此此测试只有在 C2 正确实现角色对应比较时才能通过。
```

**P20 详细设计（v2.6 新增）**：

```
构造：Binding 绑定 fid=f5 (canonical_value=ratio 0.1335, span=[100, 200])
实际文档 doc_text[100:200] 包含一段长文字，其中偶然出现 "0.1339"

TypedParse(doc_text[100:200], ratio) → 提取到 0.1339
TypedEqual(0.1339, 0.1335) → False
→ FAIL（span_content_mismatch）→ factual=REFUSED

验证点：子串包含方式会因 "0.1339" 在 span 内而误判 PASS；
       类型化精确核验方式正确拒绝。
```

## 九、实施边界（不变）

## 十、后续研究链条（不变）
