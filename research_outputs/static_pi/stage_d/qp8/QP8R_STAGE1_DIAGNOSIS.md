# QP8R 阶段 1 零调用诊断：原始响应核查（最终根因）

---

## 结论：值在原始输出中存在，但解析器不识别

**模型确实提取了值——它们以普通字符串形式存在于嵌套字典中，但 `P3.normalize_stage` 只识别 `{value: ...}` 字段格式，将所有其他格式视为 value=None。**

## 逐调用证据

| 调用 | 原始输出中的值（举例） | 解析器 value | 原因 |
|---|---|---|---|
| E06 DS e1 | `"归母净利润": "亏损：12,500.00 万元"` | **None** | 值是普通字符串，非 `{value: ...}` |
| MVR1 DS e0 | `"罚款": "1000万元"` | **None** | 同上 |
| KANGMEI DS e1 | `"调查通知书编号": "粤证调查通字180199号"` | **None** | 同上 |
| KANGMEI GLM e0 | `"value": "粤证调查通字180199号"` | **有值** | 恰好用了 `value` 字段名 |
| KANGMEI GLM e1 | `"日期": "2018-12-28"` | **None** | 值是普通字符串 |
| E06 GLM e1 | `"value": "亏损12,500.00万元"` | **有值** | 恰好用了 `value` 字段名 |

## 统计

| 调用 | 原始输出中的实际值数 | 解析器识别的值数 | **丢失率** |
|---|---:|---:|---:|
| E06 DS e1 | **21** | 0 | 100% |
| MVR1 DS e0 | **20** | 10 | 50% |
| KANGMEI DS e1 | **22** | 0 | 100% |
| KANGMEI GLM e1 | **26** | 0 | 100% |
| E06 GLM e1 | **36** | 18 | 50% |
| KANGMEI GLM e0 | **20** | 20 | 0% |

**6 个有值的调用中，解析器丢失了 4 个的全部或一半值。**

## 根因链（最终版）

```
模型输出: {bucket: {sub_key: "实际值字符串"}}
                ↓
解析器 (P3.normalize_stage): 只识别 {value: ...} 格式
                ↓
普通字符串 "实际值" 被当作结构键而非值 → value=None
                ↓
verify_evidence: 无值 → 拒绝
                ↓
证据表空 → SINK 无证据 → Q 低
```

## 与 QP4 的差异

QP4 GLM 输出恰好使用了 `{facts: [{field, value, doc, page, quote}]}` 平铺格式（有显式 `value` 字段名），解析器能识别。QP8R 的模型（同提示修复后）有时输出这种格式（KANGMEI GLM e0）、有时输出嵌套字符串格式（E06 DS e1）。**模型输出格式不稳定是根本问题。**

## 修复方向

**增强解析器**（非提示工程）：让 `P3.normalize_stage` 或适配层识别嵌套字典中的普通字符串值：

```python
# 当前: 只识别 {value: "xxx"} 格式
if 'value' in node: → 使用 node['value']

# 修复后: 也识别 {sub_key: "xxx"} 格式
if isinstance(v, str) and len(v.strip()) > 0 and k not in ('doc','page','quote'):
    → 将 v 作为 value，k 作为 field
```

这是**代码级解析修复**，无需新模型调用。
