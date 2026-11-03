# Relevance 人工裁决协议（V2.3）

**状态：HOLD** —— 尚无两名独立盲评员完成裁决。按操作员裁定，未经校准的 LLM Judge **不得**冒充人工 Gold。本协议定义工件与流程，不代表裁决已完成。

---

## 1. 两个仪器，不得混用

| 仪器 | 评价对象 | 复用性 | 用途 |
|---|---|---|---|
| **I-1 任务—材料相关性** | 任务问题能否由给定材料回答 | 每任务一次，可复用 | 任务集准入；**不进入** terminal_quality |
| **I-2 答案—题目相关性** | 某一份 SINK 答案是否回应题目 | 每份输出一次 | 唯一可提供 `question_relevance` 维度的来源 |

评分器的 `question_relevance` 是终端输出的维度，因此只能由 I-2 提供。把 I-1 的分数填进该维度属于作用域混用，禁止。

---

## 2. I-1 任务—材料相关性

**输入**：任务问题 + 该组的四份文书原文（不含 Gold、不含任何模型输出）。
**评审员**：2 名独立评审，互不参考。
**评分**：0–1。
- 0：题目与材料不相关，或材料不足以回答题目。
- 1：题目与材料充分相关，且材料足以回答。
**分歧规则**：两名评审分差 ≥ 0.4 时，由第三名评审仲裁并记录理由；最终分与理由一并写入注册表。
**记录字段**：`reviewer_ids`（≥2 个不同 id）、`review_status: ADJUDICATED`、`blind_to_strategy: true`、`blind_to_model: true`、`score`、`arbitration`（如有）。

---

## 3. I-2 答案—题目相关性

**输入**：一份 SINK 输出（仅 `answers` / `abstentions` / `complete`），以规范化 JSON 的 SHA256 为键；**不提供**实验臂、模型、节点、成本、执行轨迹。
**评审员**：2 名独立评审，互不参考。
**评分**：0–1。
- 0：交付的答案没有回应题目（答非所问、空答、拒答但题目本可回答）。
- 1：交付的答案直接回应题目。
**输出**：写入 `ANSWER_RELEVANCE_REGISTRY.json` 的 `entries[<sink_sha256>]`，结构：

```json
{
  "scope": "output_answer",
  "assessment": {
    "assessor_type": "human_adjudicator",
    "review_status": "ADJUDICATED",
    "reviewer_ids": ["r1", "r2"],
    "blind_to_strategy": true,
    "blind_to_model": true,
    "score": 1.0
  },
  "adjudication_notes": "optional"
}
```

评分器只接受 `scope == "output_answer"` 且通过凭证检查的条目；其余一律忽略。

---

## 4. 盲法操作

1. 从账本中只取 SINK 的 `text` 字段，重新解析为 JSON 并按键排序序列化，计算 SHA256。
2. 评审包只含：题目、材料、答案 JSON、哈希；不含臂名、模型名、时间戳、调用序号。
3. 评审顺序随机化；两位评审的分开收集后才合并。
4. 注册表一经写入即冻结；后续不得按实验臂或结果修改。
5. 裁决记录与评审包哈希一同存档，便于复核。

---

## 5. 未完成时的行为

- I-2 无有效条目 → `Q_final = NULL`，`blocking_reasons` 含 `QUESTION_RELEVANCE_NOT_VALIDLY_ASSESSED`。
- 不得用 I-1 分数替代；不得用模型自评替代；不得用未校准 LLM Judge 替代。
- 允许以 `Q_partial_diagnostic` 做机制解释，但不得表述为"终端质量"。
