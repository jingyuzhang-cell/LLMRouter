# V2.3 六臂统一执行合同（等待冻结）

**适用**：Static-GLM、Static-DS、Retry-only、Z-only、pi-only、Joint —— **完全相同的输出与证据要求**。
**状态**：候选文本已定稿；在与新任务集一起冻结前不得启动付费运行。

---

## 1. 输出结构（SINK）

```json
{
  "answers": [
    {"fact_id": "A1", "value": "...", "doc": "D1", "page": 1, "quote": "连续原文片段"}
  ],
  "abstentions": [
    {"item_id": "U2", "text": "无法判定的明确理由"}
  ],
  "complete": true
}
```

- `fact_id` 必须是合同槽位之一；未知项只能在 `abstentions` 中出现。
- `doc` 必须是 `D1`–`D4`（不接受节点名；适配器的 E→D 归一化仅作防御，不作为许可）。
- `page` 为整数页码；`quote` 必须是被引文书中**连续出现**的原文片段。

## 2. 证据规则（六臂相同）

1. 每个 `answer` 必须携带一条 `doc/page/quote`；`quote` 必须逐字连续，**禁止使用省略号或拼接**。
2. `quote` 必须真正支持该 `fact_id` 所问事实，不能只是"出现在同一文书中"。
3. 一个事实一条引文；若原文需要跨段才能支持，则该事实应拆分为两个槽位（任务集侧解决），不得要求模型拼接。
4. `abstentions` 中的 UNKNOWN 不需要引文，但必须给出拒答理由；**不得为满足引用要求编造证据**。
5. 引文长度建议 15–120 字；超长引文允许，但必须是连续片段。

## 3. 模型与 thinking 口径

- GLM-5.3-Flash：`thinking=enabled`, `reasoning_effort=low`。
- DeepSeek：`thinking=disabled`；仅当提示包含 "json" 时强制 `response_format`。
- π 只重写状态为 READY/PENDING 的模型节点；不得改写 Running/Completed，不得改写已删除节点。

## 4. 评分口径

- 评分器：冻结 `terminal_quality` v1.2.3，原样调用。
- 适配器：`scorer_v23_candidate.build_terminal_output`（claims_complete / delivery_valid / doc-id 归一化）。
- 规范化：`scorer_v23_candidate.canonicalize`，规则表见 `SCORING_REPAIR_V23.md` §4；六臂同一规则。
- 正式 Q 仅在 I-2（逐输出答案相关性）人工裁决存在时可计算；缺裁决时 `Q_final=NULL`。
- 必须同时报告：关键事实值正确率、证据定位成功率、证据支持率、Critical Gate 通过率、`Q_partial_diagnostic`。Gate 与解释性指标不得互相替代。

## 5. 冻结与校验

- 本合同的 SHA256 与 `evidence_contract_v23.py::contract_sha256()` 必须一致。
- 任何一条约束的变更都需要新版本号；不得在运行中途修改。
- 六臂共用同一 `EVIDENCE_DIRECTIVE` 常量；测试断言六臂生成的证据指令哈希完全相同。
