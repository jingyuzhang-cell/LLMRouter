# CROSSSOURCE_SCHEMA_FIX_REPORT — 统一跨源核查 Schema 与适配器（零付费）

## 1. 统一 JSON Schema（冻结）

```json
{
  "verdicts": [
    {
      "fact": "被比较的事实描述",
      "verdict": "CONSISTENT|CONTRADICTORY|COMPLEMENTARY|INSUFFICIENT",
      "source_a": "来源A的表述或数值",
      "source_b": "来源B的表述或数值",
      "quote_a": "≤30字逐字引文",
      "quote_b": "≤30字逐字引文"
    }
  ]
}
```

**必须**使用 `"verdicts"` 作为**唯一的顶层键名**。verdicts 是顶层数组，不嵌套在其他对象内。

## 2. 统一 System Prompt（冻结）

```
你是调查DAG中的跨来源事实核查节点。比较两个来源关于同一事实的表述。
只输出一个JSON对象，必须使用"verdicts"作为唯一的顶层键名。
格式：{"verdicts":[{"fact":"事实描述","verdict":"CONSISTENT|CONTRADICTORY|COMPLEMENTARY|INSUFFICIENT","source_a":"来源A表述","source_b":"来源B表述","quote_a":"≤30字引文","quote_b":"≤30字引文"}]}
注意：verdicts 是顶层数组键名，不是嵌套在其他对象内。不输出其他文字。
```

## 3. 预注册语义适配器（非评分优惠）

适配器仅用于**历史响应的重新解析审计**，不改变原始契约通过率。

| 层次 | 检查内容 | 记录方式 |
|---|---|---|
| JSON 语法 | 输出是否合法 JSON | `json_syntax: pass/fail` |
| 原始契约 | 顶层键=verdicts + 数组结构 | `standard_contract: pass/fail` |
| 适配后解析 | 通过预注册键名 fallback 提取内容 | `adapter_parsed: pass/fail` |

**适配器键名列表（预注册）**：`verdicts`, `comparison_result`, `analysis`, `consistency`, `comparisons`, `detail`
**中文键名 fallback**：`一致性`, `矛盾`, `互补`, `证据不足`

**重要**：适配器成功提取内容不等于原始契约通过——两者必须分开记录。适配器仅证明模型有
能力产出结构化核查内容，不证明其能遵循指定 JSON Schema。

## 4. 三层评价体系

| 层 | 指标 | 说明 |
|---|---|---|
| 1. JSON 语法合法率 | 合法 JSON / 总调用 | 基础格式能力 |
| 2. 契约遵循率 | 顶层键=verdicts / 总调用 | Schema 遵循能力 |
| 3. 核查内容质量 | 正确判定数 / Gold 参考判定数 | 需 Gold 校准 |
