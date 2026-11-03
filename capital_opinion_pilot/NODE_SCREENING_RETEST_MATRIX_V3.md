# NODE_SCREENING_RETEST_MATRIX_V3 — 重测矩阵与预算

## 重测需求（基于 80 次审计结果精确计算）

| 类别 | 组合 | 调用 | 原因 |
|---|---|---|---|
| crosssource（新样本×4 模型） | 5×4=20 | 20 | 旧样本跨事件不可比+旧提示词无键名约束 |
| entity_relations/qwen（修复提示词） | 6×1=6 | 6 | Qwen 0/6 契约通过（键名不匹配） |
| **合计** | | **26** | |

## 不需要重测的（可复用）

| 类别 | 组合 | 契约通过率 | 处理 |
|---|---|---|---|
| fact_extraction 全部 | 3×4=12 | 100% | 直接复用 |
| timeline glm53/flash | 6×2=12 | 100% | 直接复用 |
| timeline deepseek/qwen | 6×2=12 | 88% | 适配器修复 3 次非标 |
| entity_relations 非 Qwen | 6×3=18 | 83% | 适配器修复 3 次非标 |

## 统一提示词（重测用，V3 Schema）

### crosssource_check
```
你是跨来源事实核查节点。只输出一个JSON对象，必须使用"verdicts"作为唯一的顶层键名。
格式：{"verdicts":[{"fact":"描述","verdict":"CONSISTENT|CONTRADICTORY|COMPLEMENTARY|INSUFFICIENT",
"source_a":"A表述","source_b":"B表述","quote_a":"引文","quote_b":"引文"}]}
注意：verdicts 是顶层数组键名。不输出其他文字。
```

### entity_relations（仅 Qwen 重测）
```
你是主体关系分析节点。只输出一个JSON对象，必须使用"relations"作为唯一的顶层键名。
格式：{"relations":[{"subject":"主体","relation":"关系","object":"客体","doc_id":"来源"}]}
注意：relations 是顶层数组键名（不要用 triplets 或 三元组）。不输出其他文字。
```

## 预算

| 项 | crosssource | entity/qwen | 合计 |
|---|---|---|---|
| 调用 | 20 | 6 | **26** |
| 输入 tok/次 | ~700 | ~300 | — |
| 输出上限 | 2,048 | 2,048 | — |
| 估算 tok | ~26,000 | ~5,400 | **~31,400** |
| 最坏 tok | ~55,000 | ~14,000 | **~69,000** |
| 守卫保证线 | — | — | **80,000** |
| 现金 | DS 5×¥0.005+Qwen 5×¥0.001≈¥0.03 | Qwen 6×¥0.001≈¥0.006 | **≈¥0.04** |
| 现金上限 | — | — | **¥0.10** |

## 与旧"28 次"的差异

| 项 | 旧"28" | 修正 V3 |
|---|---|---|
| 调用 | 28 | **26** |
| 组成 | crosssource 20 + entity 估计 8 | crosssource 20 + entity/qwen 精确 6 |
| 说明 | 估计值 | 精确计算（基于审计结果） |
