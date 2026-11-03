# ALL_NODETYPE_SCHEMA_V3 — 四类节点统一 Schema 与五态判定（零付费冻结）

## 一、五态判定体系（替代旧 Q=0）

| 状态 | 定义 | 评分影响 | 可触发恢复？ |
|---|---|---|---|
| `JSON_FAIL` | 输出不是合法 JSON | Q 不可评 | ✅ 可触发格式修复重试 |
| `CONTRACT_FAIL` | JSON 合法但顶层键名/结构不匹配 Schema | Q 不可评（不是 Q=0） | ✅ 可触发格式修复重试 |
| `SEMANTIC_PARSED` | Schema 合法且适配器可提取内容 | Q = 探索性产出量 | — |
| `SUPPORTED` | 有逐字引文且在证据中找到 | Q = 有证据支持 | — |
| `UNRESOLVED` | 证据不足以判定 | 正确行为（不扣分） | — |

**禁止**将 CONTRACT_FAIL 计为 Q=0——这是格式问题不是能力问题。

## 二、四类节点统一 Schema

### 1. fact_extraction（现有，100% 通过——保留）
```json
{"facts": [{"fact_key": "主题", "value": "事实描述", "doc_id": "来源", "quote": "≤30字引文"}]}
```
System prompt 已验证有效。**无需修改。**

### 2. timeline（88% 通过——微修提示词）
```json
{"timeline": [{"date": "YYYY-MM-DD", "event": "事件描述", "doc_id": "来源"}]}
```
**增强提示词**（强调键名）：
```
你是时间线分析节点。只输出一个JSON对象，必须使用"timeline"作为唯一的顶层键名。
格式：{"timeline":[{"date":"YYYY-MM-DD","event":"描述","doc_id":"来源"}]}
注意：timeline 是顶层数组键名。不输出其他文字。
```

### 3. entity_relations（62% 通过——需修复）
```json
{"relations": [{"subject": "主体", "relation": "关系", "object": "客体", "doc_id": "来源"}]}
```
**修复提示词**：
```
你是主体关系分析节点。只输出一个JSON对象，必须使用"relations"作为唯一的顶层键名。
格式：{"relations":[{"subject":"主体","relation":"关系","object":"客体","doc_id":"来源"}]}
注意：relations 是顶层数组键名（不要用 triplets、三元组 或 entities）。不输出其他文字。
```

### 4. crosssource_check（5% 通过——完全重建）
```json
{"verdicts": [{"fact": "事实", "verdict": "CONSISTENT|CONTRADICTORY|COMPLEMENTARY|INSUFFICIENT",
"source_a": "A表述", "source_b": "B表述", "quote_a": "引文", "quote_b": "引文"}]}
```
**新提示词**（已在 CROSSSOURCE_SCHEMA_FIX_REPORT.md 冻结）。

## 三、执行器 Schema 校验（新增强制）

在 `evaluate()` 函数中添加：
```python
def validate_contract(text, expected_key):
    """三层校验：JSON → Schema → 语义"""
    try:
        obj = json.loads(text.strip())
    except:
        return 'JSON_FAIL', None
    if not isinstance(obj, dict) or expected_key not in obj:
        return 'CONTRACT_FAIL', obj
    if not isinstance(obj[expected_key], list):
        return 'CONTRACT_FAIL', obj
    return 'SEMANTIC_PARSED', obj
```

**CONTRACT_FAIL 自动触发格式修复重试**（不消耗额外模型调用——使用确定性打捞）。

## 四、公平性保证

- 四模型使用**完全相同的 system prompt**（仅证据内容不同）
- 不设置模型专属评分优惠
- 适配器对全部模型统一适用（预注册键名列表）
- 原始契约通过率与适配后可解析率**分开记录**
