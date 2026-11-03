# CROSSSOURCE_HISTORICAL_REPARSE_AUDIT — 历史跨源核查响应零成本重审计

## 审计范围
80 次筛选中的 20 次 crosssource_check 调用（5 样本 × 4 模型），使用已保存的原始响应文本，
零新增模型调用。

## 核心发现

### 逐模型×逐样本状态矩阵

| Call | Sample | Model | 原始 count | JSON 合法 | 适配后 items | 根因 |
|---|---|---|---|---|---|---|
| 49 | XC1 | glm53 | **6** | ✓ | 6 | **唯一标准契约通过** |
| 50 | XC1 | glm53flash | 0 | ✓ | **5** | PARSER_MISMATCH |
| 51 | XC1 | deepseek | 0 | ✓ | **6** | PARSER_MISMATCH |
| 52 | XC1 | qwen | 0 | ✓ | **1** | PARSER_MISMATCH |
| 53 | XC2 | **glm53** | **0** | ✓ | **7** | **PARSER_MISMATCH** |
| 54 | XC2 | glm53flash | 0 | ✓ | 0 | STRUCTURE_MISMATCH |
| 55 | XC2 | deepseek | 0 | ✓ | 0 | STRUCTURE_MISMATCH |
| 56 | XC2 | qwen | 0 | ✓ | **8** | PARSER_MISMATCH |
| 57-68 | XC3-5 | 全部 | 0 | ✓ | 0 | STRUCTURE_MISMATCH（跨事件不可比） |

### 惊人发现：GLM-5.3 在 XC2 上也 Q=0！

Call 53（GLM-5.3, XC2）原始 count=0——**GLM-5.3 使用了 `"comparisons"` 键而非 `"verdicts"`**。
适配后恢复 7 条判定。这证明即使 GLM-5.3 也不能稳定遵循契约——不是"仅 GLM-5.3 能做核查"，
而是"GLM-5.3 恰好在 XC1 上用了正确键名"。

### 统计汇总

| 指标 | 数量 | 占比 |
|---|---|---|
| 原始标准契约通过 | **1/20** | 5% |
| JSON 语法合法 | **20/20** | 100% |
| 适配后可恢复内容 | **6/20** | 30% |
| 跨事件不可比（XC3-5） | 12/20 | 60% |
| 适配后结构不匹配但仍有内容 | 2/20 | 10% |

### 原始 Q=0 的归因

| 原因 | 调用数 | 可修复？ |
|---|---|---|
| 键名不匹配（PARSER_MISMATCH） | 5 | ✅ 适配器可恢复 |
| 结构不同（STRUCTURE_MISMATCH，同事件） | 2 | ⚠ 需更强适配器或修提示词 |
| 跨事件不可比（XC3-5 全部） | 12 | ❌ 样本设计问题 |
| 实际无内容 | **0** | — |

**关键结论：0/20 是"模型实际无法产出核查内容"。全部 Q=0 来自解析器不兼容或样本设计问题。**

## 对能力表 V2 的影响

能力表 V2 中 crosssource_check 行的 Q_output_ratio **全部作废**：

| 模型 | V2 Q | 重审计后实际 | 状态 |
|---|---|---|---|
| glm53 | 1.00 | XC1 有 6 条；XC2 有 7 条(适配)；XC3-5 正确判不可比 | **需重测** |
| glm53flash | 0.00 | XC1 有 5 条(适配) | **需重测** |
| deepseek | 0.00 | XC1 有 6 条(适配) | **需重测** |
| qwen | 0.00 | XC1 有 1 条；XC2 有 8 条(适配) | **需重测** |
