# HISTORICAL_80_REPARSE_RESULT — 全部 80 份历史响应三层审计（零付费）

## 完整矩阵（16 格 = 4 类型 × 4 模型）

| 类型 | 模型 | 调用 | JSON✓ | 契约✓ | 适配 | 未恢复 | 契约条目 | 适配条目 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| **fact_extraction** | glm53 | 3 | 3 | **3** | 0 | 0 | 22 | 0 | ✅ CLEAN |
| | glm53flash | 3 | 3 | **3** | 0 | 0 | 17 | 0 | ✅ CLEAN |
| | deepseek | 3 | 3 | **3** | 0 | 0 | 27 | 0 | ✅ CLEAN |
| | qwen | 3 | 3 | **3** | 0 | 0 | 20 | 0 | ✅ CLEAN |
| **timeline** | glm53 | 6 | 6 | **6** | 0 | 0 | 10 | 0 | ✅ CLEAN |
| | glm53flash | 6 | 6 | **6** | 0 | 0 | 9 | 0 | ✅ CLEAN |
| | deepseek | 6 | 6 | 4 | 1 | 1 | 7 | 2 | ⚠ PARTIAL |
| | qwen | 6 | 6 | 5 | 0 | 1 | 6 | 0 | ⚠ PARTIAL |
| **entity_relations** | glm53 | 6 | 6 | 5 | 0 | 1 | 32 | 0 | ⚠ PARTIAL |
| | glm53flash | 6 | 6 | 5 | 0 | 1 | 25 | 0 | ⚠ PARTIAL |
| | deepseek | 6 | 6 | 5 | 1 | 0 | 22 | 3 | ⚠ PARTIAL |
| | **qwen** | 6 | 6 | **0** | **6** | 0 | 0 | **39** | ❌ **INVALID** |
| **crosssource** | glm53 | 5 | 5 | **1** | 1 | 3 | 6 | 7 | ❌ INVALID |
| | glm53flash | 5 | 5 | **0** | 1 | 4 | 0 | 5 | ❌ INVALID |
| | deepseek | 5 | 5 | **0** | 0 | 5 | 0 | 0 | ❌ INVALID |
| | qwen | 5 | 5 | **0** | 2 | 3 | 0 | 9 | ❌ INVALID |

## 关键发现

### 1. JSON 语法：80/80 全部合法
所有模型在所有节点类型上都能产出合法 JSON——**没有模型"不会输出 JSON"**。

### 2. 契约遵循差异巨大
- **fact_extraction 100%**（12/12）——`"facts"` 键是所有模型的自然选择
- **timeline 88%**（21/24）——大部分用 `"timeline"`，DeepSeek 偏好 `"events"`
- **entity_relations 63%**（15/24）——GLM 系用 `"relations"`/`"entities"`；**Qwen 全部用 `"triplets"`/`"三元组"`**
- **crosssource 5%**（1/20）——仅 GLM-5.3 在 XC1 上用了 `"verdicts"`

### 3. Qwen 的 entity_relations 真相
**Qwen 在全部 6 个样本中产出了 39 条关系三元组**（适配后可提取），但 0 条通过标准契约解析。
这不是"Qwen 不会关系分析"——是"Qwen 不用 `relations` 这个键名"。

### 4. 适配器恢复量
- entity_relations Qwen: **39 条**（全部通过适配器恢复）
- crosssource 4 模型合计: **21 条**（部分通过适配器恢复）
- 这些内容**存在**但**未经 Gold 验证正确性**

## 对能力表 V3 的含义

| 行 | 状态 | 行动 |
|---|---|---|
| fact_extraction 全部 4 行 | ✅ 有效 | **保留** |
| timeline glm53/flash | ✅ 有效 | **保留** |
| timeline deepseek/qwen | ⚠ 部分 | 3 次非标可适配修复，不需要重测 |
| entity_relations glm53/flash/deepseek | ⚠ 大部分有效（各 5/6 契约通过） | **基本保留**，标注 1 次非标 |
| entity_relations **qwen** | ❌ **作废** | **需重测**（0/6 契约通过） |
| crosssource **全部** | ❌ **作废** | **需重测**（1/20 契约通过） |
