# CAPABILITY_TABLE_V3_REBUILD_PLAN — 能力表 V3 重建计划

## 1. V2 → V3 变更映射

| V2 行 | V2 Q | 审计结果 | V3 处理 |
|---|---|---|---|
| fact_extraction × 4 模型 | 0.63-1.00 | ✅ 12/12 契约通过 | **保留** |
| timeline glm53 | 1.00 | ✅ 6/6 | **保留** |
| timeline glm53flash | 0.90 | ✅ 6/6 | **保留** |
| timeline deepseek | 0.70 | ⚠ 4/6 契约+1 适配+1 未恢复 | 保留，标注 |
| timeline qwen | 0.50 | ⚠ 5/6 契约+1 未恢复 | 保留，标注 |
| entity_relations glm53 | 1.00 | ⚠ 5/6 契约 | 保留，标注 |
| entity_relations glm53flash | 0.78 | ⚠ 5/6 契约 | 保留，标注 |
| entity_relations deepseek | 0.69 | ⚠ 5/6 契约 | 保留，标注 |
| entity_relations **qwen** | **0.00** | ❌ **0/6 契约+6 适配** | **作废→重测** |
| crosssource glm53 | 1.00 | ❌ 1/5 契约 | **作废→重测** |
| crosssource 其余 3 行 | 0.00 | ❌ 0/5 契约 | **作废→重测** |

## 2. V3 结构改进

- Q 指标更名为 `contract_pass_rate`（契约通过率）与 `output_count`（产出条目数）
- 新增 `adapter_recovered_items`（适配器恢复条目数）
- 新增 `actual_capability`（Gold 校准后的真实能力——当前 PENDING）
- **禁止**将 CONTRACT_FAIL 记为 Q=0

## 3. 重测需求

| 节点类型 | 需重测组合 | 原因 |
|---|---|---|
| entity_relations/qwen | 6 样本×1 模型=6 | 0/6 契约通过（键名不匹配） |
| crosssource/全部 | 5 新样本×4 模型=20 | 1/20 契约通过+样本设计缺陷 |
| **合计** | **26 次** | |

不需要重测的：
- fact_extraction（12 次：全部契约通过）
- timeline（24 次：88% 契约通过，3 次非标可适配器修复）
- entity_relations 非 Qwen（18 次：83% 契约通过）

## 4. "28 次"的计算解释

此前提出的"28 次"= crosssource 20 次 + entity_relations 约 8 次（估计值）。
经完整审计后修正为 **26 次**（crosssource 20 + entity_relations/qwen 6）。
时间线 3 次非标可通过适配器零成本修复，不需要重测。
