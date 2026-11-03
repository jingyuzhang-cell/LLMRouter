# KDX_GOLD_FIRST_BATCH_GUIDE — 康得新 Gold 首批标注指南（15-20 条流程校准）

## 目的
首批 15-20 条仅用于**标注流程校准**（检验标注指南清晰度、计算一致性工具），不冒充完整 Gold。

## 首批选取规则
从 `KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/candidates_reference.json` 的 80 条候选中，
按以下规则选取 18 条（确保覆盖多文档、多类型）：

### 按文档分布（确保覆盖全部 5 份文档）
| 文档 | 选取数 | 理由 |
|---|---|---|
| D3 kdx_penalty_2020（处罚决定书） | 6 | 最丰富的事实来源 |
| D1 kdx_inquiry_2018（2018问询回复） | 4 | 跨年度证据 |
| D2 kdx_inquiry_2019（2019问询回复） | 3 | 跨年度证据 |
| D4 kdx_notice_2019（2019事先告知） | 3 | 监管过程 |
| D5 kdx_notice_2020（2020事先告知） | 2 | 监管过程 |

### 按类型分布
| 事实类型 | 选取数 | 示例 |
|---|---|---|
| 日期 | 5 | 立案日期/告知日期/处罚日期 |
| 金额 | 4 | 罚款金额/虚增金额 |
| 主体 | 4 | 当事人/实控人/监管机构 |
| 监管行为 | 3 | 立案/处罚/禁入 |
| 文号 | 2 | 处罚字〔2024〕56号 |

## 标注者工作文件

### 标注者 A 填写
```json
[
  {"fact_id":"FB01","question":"...","answer":"...","answer_type":"date|amount|entity|text",
   "doc_id":"...","quote":"≤30字逐字引文","support_status":"SUPPORTED|REFUTED|INSUFFICIENT|CONFLICTING"},
  ...
]
```

### 标注者 B 填写（同格式，独立完成）

### 裁决表（第三标注者填写）
```json
[
  {"fact_id":"FB01","A_answer":"...","B_answer":"...","ruling":"...","reason":"..."}
]
```

## 标注步骤
1. **阅读** `KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/` 中的全部 5 份文档文本
2. **参考** `candidates_reference.json` 中的候选（仅作提示，不照抄）
3. **独立** 为 18 条事实填写 question/answer/type/doc_id/quote/support_status
4. **不确定的** 标为 INSUFFICIENT——不要猜测
5. **发现候选之外的重要事实** 可自行新增

## 一致性检查
两人完成后运行：
```bash
python3 annotate_agreement.py annotator_A.json annotator_B.json
```
通过标准：κ ≥ 0.75 且人工复核分歧清单后确认裁决合理。

## 首批 18 条候选清单（已在 candidates_reference.json 中标注 first_batch=true）
详见 `KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/first_batch_18.json`（程序生成，标注者须独立核验）。

## 重要提醒
- **不要**因为模型输出了某条事实就标为 SUPPORTED
- **不要**参考任何模型的输出或评分结果
- **必须**逐字核对证据原文中的引文
- **证据不足以判定时**标 INSUFFICIENT，不要猜
- **Gold=PENDING** 直到双人标注+裁决+抽查全部完成
