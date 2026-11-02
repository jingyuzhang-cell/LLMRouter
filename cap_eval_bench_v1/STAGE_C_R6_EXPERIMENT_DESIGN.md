# STAGE-C-R6: 最小配对实验设计（零调用，待授权后执行）

## 一、前缀不可替代性审查结果

**6/6 事实通过全部四项检查：**

| Fact | 类型 | 单文档 | 前缀输出 | 反事实 | 判定 |
|---|---|---|---|---|---|
| E1-DD-1 间隔350天 | temporal | NO ✓ | NO ✓ | 双侧必需 ✓ | **GENUINELY DOWNSTREAM** |
| E1-DD-2 违法认定一致 | cross_doc | NO ✓ | NO ✓ | 双侧必需 ✓ | **GENUINELY DOWNSTREAM** |
| E2-DD-1 间隔0天 | temporal | NO ✓ | NO ✓ | 双侧必需 ✓ | **GENUINELY DOWNSTREAM** |
| E3-DD-1 换股比例不一致 | cross_doc | NO ✓ | NO ✓ | 双侧必需 ✓ | **GENUINELY DOWNSTREAM** |
| E3-DD-2 终止上市首次披露 | cross_doc | NO ✓ | NO ✓ | 双侧必需 ✓ | **GENUINELY DOWNSTREAM** |
| E4-DD-1 间隔22天 | temporal | NO ✓ | NO ✓ | 双侧必需 ✓ | **GENUINELY DOWNSTREAM** |

**核心区分**：前缀节点（n1-n2）提供的是**输入**（各文档的日期/数值），下游节点（n3-n5）执行的是**转换**（跨文档计算/比较）。输入在前缀，结果不在——这就是真正的下游依赖。

## 二、最小配对实验矩阵

| 参数 | 值 | 理由 |
|---|---|---|
| 事件 | 2（E1獐子岛 + E3中国船舶） | E1有temporal+cross_doc，E3有cross_doc×2 |
| 异常 | 1（transport） | 恢复场景（evidence_fail在前批已证明COMPLETE） |
| 臂 | 5（排除Joint(Z,R,π)） | Z=NOT_TESTED，排除避免虚假比较 |
| 重复 | 2 | 探索性配对最低要求 |
| **总 run** | **2×1×5×2 = 20** | 最小可辨识矩阵 |

## 三、评分体系（四指标独立报告）

| 指标 | 对象 | Silver 子集 |
|---|---|---|
| Q_terminal | 最终报告 | 全部 32 条 |
| Q_prefix | 前缀可获事实 | 原 26 条 |
| Q_downstream | 下游依赖事实 | 新增 6 条 |
| ΔQ_recovery | 恢复后新增覆盖 | Q_downstream(恢复) - Q_downstream(无恢复基线) |

## 四、预算估算

| 项 | 估算 | 硬上限 |
|---|---|---|
| 调用 | 20 × ~6.5 = ~130 | **200** |
| Token | 20 × ~6500 = ~130K | **200,000** |
| GLM-5.3 | ~80% | **160,000** |
| Flash | ~20%（如果触发） | **40,000** |
| 现金 | ¥0/$0 | 订阅制 |

## 五、关键成功标准

1. **ΔQ_recovery > 0**：恢复使下游事实覆盖增加（至少在1个事件中）
2. **臂间 Q_downstream 差异**：恢复臂 vs Static 在下游事实上存在可测量差异
3. **Flash 切换触发**：预算设计使 Flash 至少被选择一次

## 六、等待授权

> "授权执行 Stage-C-R6（最小配对实验），上限 200 次调用、200,000 Token，GLM≤160K、Flash≤40K。"
