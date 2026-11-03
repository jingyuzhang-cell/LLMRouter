# V2.3 评分体系修复（候选版）

**状态**：候选实现完成，50/50 测试通过；**未产生任何真实调用**；冻结评分器 `terminal_quality.py` v1.2.3 未修改（SHA256 已由测试断言）。
**日期**：2026-11-02
**范围**：只修评分链路，不改任务、不改执行器、不改 V2 数据。

---

## 1. 四项阻断的根因（逐条，含代码证据）

V2 的 36 次执行全部 `Q_final=None`，阻断原因为同一组四项。逐条定位：

| # | 阻断 | 根因 | 性质 |
|---|---|---|---|
| 1 | `CLAIM_EXTRACTION_INCOMPLETE` | `stage_a/executor.py::build_terminal_output` 返回的字典**从未包含** `claims_complete` 键；评分器读 `terminal_output.get("claims_complete", False)` 恒为 False | 适配器缺失，不是评分器缺陷 |
| 2 | `DELIVERY_INVALID_SEMANTIC_QUALITY_UNAVAILABLE` | 同一适配器**从未包含** `delivery_valid`；评分器要求 `is True` | 同上 |
| 3 | `GOLD_CONTRACT_INVALID_VALUE:E3` | 合同 E3 的 `value_kind="number"`，但 `value="2(公司+自然人王勇)"`；`_decimal()` 解析失败 | 合同数据录入缺陷 |
| 4 | `QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED` | `question_relevance` 需要"双盲人工裁决"或"已校准 judge + 注册表"；V2 两者都没有 | 缺少裁决工件，代码无法单方面解决 |

测试用例 `frozen adapter leaves delivery_valid unset` / `leaves claims_complete unset` 直接证明了第 1、2 项：冻结适配器的输出里根本没有这两个键。

---

## 2. 候选链路做了什么

```
SINK 原始输出
  → 适配器（契约感知）
      · claims / abstentions（沿用冻结槽位表）
      · claims_complete：结构完整（sink 是 dict、answers 是列表、每个元素有非空 fact_id、
        id 可映射且无重复）——与"任务是否答全"分离，后者由 necessary_completeness 度量
      · delivery_valid：交付物非空且结构良好（不采用模型自报的 complete 标志，避免奖励过度自信）
      · doc-id 归一化：优先取字符串中的 D[1-4]；否则把节点前缀 E1/E2/E3/E4 及其 _pos/_rest/_merge
        后代映射为 D1/D2/D3/D4
  → 规范化层（canonicalization）
      · 把语义等价、但措辞不同的答案映射到冻结 gold token
      · 规则按 gold 语义编写，逐条列在 §4；含"部分答案一律不规范化"的保护
  → 冻结 terminal_quality.evaluate_terminal_quality（原样调用，不改一行）
```

**没有做的事**：没有改评分器；没有改阈值；没有用模型答案反推接受列表；没有伪造 relevance；没有放宽 critical gate。

---

## 3. 证据：50 项独立测试（`V23_SCORING_TESTS.json`）

关键断言：

- 冻结 `terminal_quality.py` 与 `stage_a/executor.py` 的 SHA256 与基线一致（防止静默修改）。
- 冻结适配器确实不产出 `delivery_valid` / `claims_complete`（根因复现）。
- 候选适配器在结构良好时置真；答案缺 `fact_id`、重复 `fact_id`、空 answers 时置假。
- doc-id 归一化：`E1(D1)→D1`、`E2_pos→D2`、`E1_merge→D1`、`D3→D3`、`X9→X9`。
- 候选合同清除第 1、2、3 项阻断；提供合法 relevance 工件后清除第 4 项；满分合成答案 `Q_final=1.0`。
- 不提供 relevance 时 Q 仍然阻断（不伪造）。
- 规范化正向：A4/A5/C1/C2/D_1/D_2/D_3/D_4 的等价措辞被映射；E2 答 "4" 被拒绝。
- 规范化反向：D_4 答"同一人"、A1/A3 答 `PERSON_ONLY_王勇`、A4 答 `PERSON_ONLY_俞发祥`、C1 答 `GENERIC_`、D_1 答"不同自然人"、A5 答"兼董事长"、C2 答"D1/D2 无法判定"——全部保持错误。
- critical gate 与 evidence 要求仍然生效：关键事实答错 → `Q_final=0`；值对但 quote 为空 → gate FAIL。

---

## 4. 规范化规则（需人工批准后冻结）

规则按 gold 语义编写，**不是**从 V2 答案枚举出来的接受串；但必须承认：规则是在看过 V2 输出之后写的，因此只可用于机制验证，确认性实验前需在独立任务上复核。

| 槽位 | gold | 接受条件（摘要） | 明确拒绝 |
|---|---|---|---|
| A1/A2 | `PERSON_ONLY_实际控制人俞发祥` | 前缀 `PERSON_ONLY_` 且含"俞发祥"，无 `BOTH_`/`COMPANY_ONLY_` | 含"公司被立案/公司及实控人"、错人名 |
| A3 | `BOTH_公司及实际控制人王勇` | 前缀 `BOTH_` 且含"王勇" | 单主体前缀、错人名 |
| A4 | `COMPANY_ONLY_纳川公司` | 前缀 `COMPANY_ONLY_` 且含"纳川" | 其他主体 |
| A5 | `均无职务(仅实际控制人)` | 含"实际控制人"且含"仅/均无职务/均为实际控制人"，不含其他职务词 | 含董事长/总经理/法定代表人/监事 |
| B3 | 两个编号存在 | 同时含 `0042026002` 与 `0042026003` | 只含一个 |
| B3b | 编号→主体对应 | 两编号 + "王勇" + "公司" + 对应关系词 | 缺对应 |
| C1 | `SPECIFIC_因公司2023年年报…` | 含 `SPECIFIC`、"2023年年报"、"信息披露违法违规" | `GENERIC_` |
| C2 | `GENERIC_…未指明` | 含 `GENERIC`、"涉嫌信息披露违法违规"，不含"未指明" | 部分不可判定 |
| D_1 | `SAME_PERSON` | "同一人/同一自然人/同一个人"，不含否定 | "不同" |
| D_2 | `SAME_NOTICE_INSTANCE` | "同一份"+（告知书/文书），不含否定 | "不同" |
| D_3 | `SAME_RECEIPT_EVENT` | "同一收到事件"或"同日收到"，不含否定 | "不同" |
| D_4 | `DIFFERENT_COMPANY` | "非同一公司/不同公司/两家不同" | "同一人"等 |
| E1/E2/E3 | 1 / 2 / 2 | 数值前缀相等；E3 需同时出现"公司"或"王勇" | 3、4 等 |
| F4 | 落款日不同、收到日相同 | 同时含"落款日"+差异词+"收到日/收到事件"，且不含"不可判定" | 只说收到日相同 |

全局保护：答案含"无法判定/不可判定/无法确定/不能判定/不确定"时，一律不规范化。

---

## 5. 回溯应用（机制验证，**非确认性证据**）

将候选链路套用到 V2 已存的 36 份 SINK 输出（零调用，`RETROSPECTIVE_V23.json`）：

| 臂 | 冻结 TP 中位 | 候选 TP 中位 | 证据支持型 TP | Q_partial 中位 | critical gate PASS/FAIL | 剩余阻断 |
|---|---|---|---|---|---|---|
| Static-GLM | 6.0 | 16.0 | 10.0 | 0.737 | 0/6 | 仅 relevance |
| Static-DS | 5.5 | 18.0 | 14.5 | 0.810 | 0/6 | 仅 relevance |
| Retry-only | 6.5 | 18.0 | 10.0 | 0.781 | 0/6 | 仅 relevance |
| Z-only | 5.0 | 17.0 | 9.5 | 0.734 | 0/6 | 仅 relevance |
| pi-only | 6.0 | 17.5 | 13.5 | 0.804 | 0/6 | 仅 relevance |
| Joint | 6.0 | 19.5 | 16.0 | 0.848 | 0/6 | 仅 relevance |

**必须同时读出的三件事**：

1. 前三项阻断（适配器缺失 + E3 合同缺陷）确实被清除；只差 relevance 工件，Q 即可形式化计算。
2. 冻结 TP 与候选 TP 的差距（约 10–14 分）说明 V2 的臂间差异绝大部分由**措辞格式**造成，而不是知识差异。
3. **新的瓶颈是证据支持，不是值格式。** 候选值修复后，critical gate 仍几乎全 FAIL；拆解 12 个关键事实：值错 2.0–3.2 个，**证据不满足 2.5–5.3 个**。因此下一轮必须解决"引用必须是连续逐字原文"，否则 Q 会继续被 gate 归零。

回溯表的用途仅限机制验证：规范化规则是在看到这 36 份输出之后写的，表内数字不得作为任何臂优劣的证据。

---

## 6. 仍需操作员裁定的四件事

1. **relevance 裁决机制**（阻断 4 的唯一出口）。两个可选项：
   - 双盲人工裁决：每任务 2 名独立评审，判定"任务问题是否被 23 个槽位完整覆盖"，给出 0–1 分；每任务一次，可复用。这是评分器接受的形式（`assessor_type="human_adjudicator"`）。
   - 已校准 judge + 注册表：需要校准工件 SHA256 与 judge_id 注册表。成本更高，且引入模型裁决。
   建议：人工裁决，每任务一次；在任务冻结前完成并写入 `RELEVANCE_REGISTRY.json`。
2. **规范化规则表是否批准**。建议批准为"候选",并在独立任务上做一次盲复核；发现误接受就回滚该条规则，不得按臂调整。
3. **证据策略**。建议在 V2.3 管道中要求 SINK 输出**连续的逐字引文**（不允许"……"拼接），六臂同一提示、同一约束；这是管道修复，不是评分放宽。若不改，critical gate 会继续把 Q 归零。
4. **critical gate 是否维持全有全无**。建议维持：它是当前唯一能区分"答对但无据"与"答对且有据"的机制。

---

## 7. 产物

| 文件 | 说明 |
|---|---|
| `contract_v23_candidate.json` | 候选合同：E3 修复 + accepted_values 提议 + 适配器策略；父合同 SHA256 已记录 |
| `scorer_v23_candidate.py` | 适配器 + 规范化 + 冻结评分器调用 |
| `test_scoring_v23.py` | 39 项独立测试 |
| `V23_SCORING_TESTS.json` | 测试结果与冻结件哈希 |
| `retrospective_v23.py` / `RETROSPECTIVE_V23.json` | 对 V2 输出的零调用回溯（非确认性） |
