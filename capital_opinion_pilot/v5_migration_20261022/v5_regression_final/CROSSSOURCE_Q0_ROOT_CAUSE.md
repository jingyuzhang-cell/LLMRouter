# CROSSSOURCE_Q0_ROOT_CAUSE — 跨源核查 Q=0 根因：提示词适配问题（非模型能力缺陷）

## 诊断结论

**全部 4 模型都能执行跨源核查分析**——Q=0 的原因是它们使用了不同的 JSON 键名，而解析器只认 `"verdicts"`。

## 证据（逐模型原始响应分析）

| 模型 | XC1 输出键名 | 有实质分析？ | 解析结果 | 根因 |
|---|---|---|---|---|
| GLM-5.3 | ✅ `"verdicts"` | ✅ 6 条判定 | count=6 | **唯一遵循契约的模型** |
| GLM-Flash | ❌ `"comparison_result"` + `"detail"` | ✅ 完整对比分析 | count=0 | 键名不匹配 |
| DeepSeek | ❌ `"consistency"` + `"analysis"` 内含 `"consistent_facts"` 等 | ✅ 结构化分析 | count=0 | 完全不同的输出架构 |
| Qwen | ❌ `"consistency"` 数组 + `"contradiction"` 数组 | ✅ 带来源标注的对比 | count=0 | 键名不匹配 |

### XC3/XC4/XC5（跨事件比较）的额外发现
**全部 4 模型（含 GLM-5.3）都正确输出"证据不足/不可比较"**——因为这些样本比较的是**不同事件/不同公司**
的文档（元道退 vs 舜天 vs 康得新），根本没有可比事实。这是**样本设计问题**，不是模型问题。

## 修复方案

### 方案 A：修提示词（推荐）
在 system prompt 中给出具体的输出格式示例：
```
只输出JSON，格式如下（必须使用 "verdicts" 作为顶层键名）：
{"verdicts": [{"fact": "描述", "verdict": "CONSISTENT|CONTRADICTORY|COMPLEMENTARY|INSUFFICIENT", "source_a": "...", "source_b": "..."}]}
```

### 方案 B：修解析器（兼容方案）
在 evaluate() 中接受多种键名作为 fallback：
```python
verdicts = obj.get('verdicts') or obj.get('comparison_result') or obj.get('analysis') or obj.get('consistency') or []
```

### 方案 C：同时修两者（最稳健）
提示词更明确 + 解析器有 fallback → 确保跨模型兼容性。

### 样本设计修复
XC3/XC4/XC5 应改为**同一事件内不同文档**的交叉比较（如康得新的问询回复 vs 处罚决定书），
而非跨事件比较（元道退 vs 舜天 = 无可比性）。

## 对能力表和 S6 的影响

| 修复前 | 修复后（预期） |
|---|---|
| 仅 GLM-5.3 在 crosssource Q>0 | 全部 4 模型可能 Q>0 |
| S6 唯一"独有优势"= 识别 crosssource 不可行 | **此优势消失**（其他模型也能做了） |
| 能力表 crosssource 行：3/4 模型 Q=0 | 需要重新测量（预计 4/4 Q>0） |
| S6 vs S5+CloGate: 0/8 独有 | 决策空间可能进一步收窄 |

## 必须重新审视的结论

1. ~~"仅 GLM-5.3 能做跨源核查"~~ → **错误**（全部模型都能做，只是格式不同）
2. ~~"S6 通过质量门禁识别不可行恢复"~~ → **不可靠**（Q=0 是解析问题，不是模型无能力）
3. 能力表 V2 中 crosssource_check 行的全部 Q 值 → **需要修复提示词后重新测量**
4. 80 次筛选的 crosssource 结果 → **不可用于能力表构建**（提示词+样本双重问题）

## 建议下一步
1. 修复提示词（方案 C）+ 修复样本设计（改为同事件交叉）
2. 重新运行 crosssource_check 的 4 模型×5 样本 = 20 次筛选（需授权 ~¥0.01）
3. 用修复后数据重新构建能力表 V3
4. 重新评估 S6 vs S5+CloGate 的决策空间
