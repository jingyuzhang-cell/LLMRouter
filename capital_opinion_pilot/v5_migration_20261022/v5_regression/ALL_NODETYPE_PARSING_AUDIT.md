# ALL_NODETYPE_PARSING_AUDIT — 全节点类型解析一致性审计（零付费）

## 核心发现：解析器问题不限于 crosssource——entity_relations 也严重受影响

### 全节点类型解析一致性总览

| 节点类型 | 标准契约键名 | 标准/总计 | 比率 | 状态 |
|---|---|---|---|---|
| fact_extraction | `facts` | 12/12 | **100%** | ✅ CLEAN |
| timeline | `timeline` | 21/24 | **88%** | ⚠ 3 次非标 |
| entity_relations | `relations` | 15/24 | **62%** | ❌ **严重问题** |
| crosssource_check | `verdicts` | 1/20 | **5%** | ❌ **完全失效** |

### entity_relations 详细审计（与 crosssource 同型问题）

**Qwen 全部 6 样本 Q=0 的真相**：Qwen 产出了**完整的关系三元组**，但使用了 `"三元组"`（中文）
或 `"triplets"` 作为键名，而非要求的 `"relations"`。**这不是模型无能力——是解析器不认 Qwen 的键名。**

| 模型 | 标准键 | 非标键使用 | 非标次数 | 实际有三元组？ |
|---|---|---|---|---|
| GLM-5.3 | `relations`/`entities` | `主体关系`(中文) | 1 | ✅ |
| GLM-Flash | `relations`/`entities` | JSON 解析失败 | 1 | — |
| DeepSeek | `entities`/`relations` | `subject_relations` | 1 | ✅ |
| **Qwen** | **无** | **`三元组`/`triplets`（全部 6 次）** | **6** | **✅ 有完整三元组** |

### Qwen 原始响应示例（证明有能力）
```json
{"三元组": [["元道通信股份有限公司", "被处罚", "中国证监会"], ["李晋", "被处罚", "中国证监会"]]}
{"triplets": [["江苏舜天股份有限公司", "被处罚", "中国证监会"], ["高松", "任职于", "江苏舜天股份有限公司"]]}
```
Qwen 的三元组格式完全正确（主体-关系-客体），只是键名不同。

### timeline 非标详情（3/24）
| 调用 | 模型 | 问题键名 | 实际有内容？ |
|---|---|---|---|
| TL2/DeepSeek | deepseek | `events` | ✅ 有日期+事件 |
| TL4/DeepSeek | deepseek | `events`(空数组) | 合理（输入为空） |
| TL5/Qwen | qwen | 裸数组（无键名包裹） | ✅ 有时间线 |

## 对能力表 V2 的全面影响

| 行 | V2 Q 值 | 实际状态 | 需要行动 |
|---|---|---|---|
| fact_extraction 全行 | 有效 | ✅ 12/12 标准解析 | 保留 |
| timeline 全行 | 大部分有效 | 21/24 标准（3 次边缘） | 基本保留，标注 3 次非标 |
| **entity_relations Qwen 行** | Q=0.00 | **作废**——Qwen 有三元组但键名不匹配 | 需重测或适配 |
| entity_relations 其他行 | 部分有效 | 15/24 标准（GLM-53/Flash/DS 各 1 次非标） | 基本保留 |
| **crosssource 全行** | 作废 | **完全失效**——仅 1/20 标准 | 已标记 INVALID |

## 对 S6 结论的进一步影响

此前已撤回的结论（基于 crosssource Q=0）仍维持撤回。**新增**：
- "Qwen 在主体关系上持续零产出" → **作废**（键名不匹配，非能力缺陷）
- 能力表 V2 entity_relations Qwen 行 → **作废**
- S6 决策中排除 Qwen 做主体关系的依据 → **失效**

## 根因分析

**统一根因：提示词未严格强制 JSON Schema 的键名**。
- fact_extraction 的 `"facts"` 键恰好是所有模型的自然选择 → 100% 通过
- 其他类型的键名（`relations`/`verdicts`/`timeline`）各模型有不同偏好 → 大量不匹配
- **修复方向**：所有节点的 system prompt 都必须包含明确的 JSON 格式示例，
  并强调"必须使用 [具体键名] 作为顶层键"

## 修复优先级

1. **crosssource**（5% 通过率）：已冻结新 Schema+Prompt → 待 20 次重测
2. **entity_relations**（62% 通过率）：需类似修复——冻结明确 Schema+Prompt → 可与 crosssource 重测合并
3. **timeline**（88% 通过率）：基本可用，3 次非标可适配器修复
4. **fact_extraction**（100% 通过率）：无需修复
