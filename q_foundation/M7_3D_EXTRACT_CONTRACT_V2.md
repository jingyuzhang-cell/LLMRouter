# Extract 节点输出合同 V2（日期角色消歧 + 证据锚定）

**版本**: V2 | **日期**: 2026-11-01 | **状态**: 冻结待 GO

## 修正原因

V1 合同仅要求"提取相关日期"——未区分日期语义角色（披露/收到/落款），导致：
1. 同一文档有时提取 2025-12-19（收到日期）、有时 2025-12-20（披露日期）——跨运行不一致
2. 处罚日期 2026-09-11 存在于文档中但未被标记为 penalty_date——报告节点无法消费

## V2 合同定义

### 提示词模板
```
从以下文档中提取与立案调查、行政处罚、退市风险相关的关键事实。
每个日期必须标注其语义角色（date_role）。

输出JSON:
{
  "key_facts": [
    {
      "fact_type": "filing_date" | "penalty_date" | "risk_warning_date" | "other_date" | "amount" | "authority" | "reason",
      "value": "具体值",
      "date_role": "披露日期|收到日期|落款日期|处罚日期|其他",
      "source_document": "文档标识",
      "evidence_quote": "原文证据引用（截取关键句，含日期上下文）",
      "confidence_status": "SUPPORTED" | "UNKNOWN"
    }
  ],
  "unknown_facts": ["无法确定的事实类型列表"]
}

要求：
1. 区分"披露日期"（在交易所网站发布公告的日期）与"收到日期"（收到监管机构文书的日期）。
2. 如果文档中同时出现两个日期，必须分别提取并标注各自的 date_role。
3. 没有足够原文依据时，confidence_status 必须为 UNKNOWN，不得猜测。
4. 事实必须附带原文证据引用。
5. key_facts 必须存在（可为空数组），不得省略字段。

文档：
{document_content}
```

### 三项硬约束
1. **日期角色消歧**：每个日期必须标注 date_role（披露/收到/落款/处罚），不允许无角色日期
2. **证据锚定**：每个事实附 evidence_quote（原文引用）
3. **真实性**：无足够依据时返回 UNKNOWN，不猜测

## 与 V1 的差异

| 项 | V1 | V2 |
|---|---|---|
| 日期处理 | 泛提取"相关日期" | 按 date_role 分类（披露/收到/落款/处罚） |
| 多日期文档 | 随机取一 | 全部提取并标注角色 |
| 证据引用 | 无要求 | evidence_quote 必需 |
| 置信度 | 无 | SUPPORTED / UNKNOWN |
| 输出结构 | 泛 JSON 数组 | 结构化 key_facts + unknown_facts |

## 适用范围
- 配对实验中的 V2 组使用此合同
- V1 组保持原合同不变
- 下游合同（split V2、report）不变
- 评分器、参考事实不变
