# Label Repair Experiment：最终受控验证

选中103个原uncertain query，四模型各新增10次，5→15 repeats。选题为每个冻结development折内信息增益前40题的并集；各折只使用自己的40题修复标签。

同一原始GTE、QueryOnly Ridge与现有最简单冻结MA训练流程；不改变模型/表示/loss/阈值。旧标签对照在补采前重训并封存，且复现历史Ridge与全部3个MA初始化决策。

## 标签转化

| uncertain → | 数量 |
|---|---:|
| switch | 6 |
| stay | 2 |
| tie | 83 |
| uncertain | 12 |

已判定比例：88.35%；修复子集严格margin switch：2。

| fold | 修复题数 | switch前 | switch后 | strict switch后 | uncertain后 |
|---|---:|---:|---:|---:|---:|
| 0 | 40 | 20 | 21 | 12 | 92 |
| 1 | 40 | 23 | 26 | 16 | 84 |
| 2 | 40 | 25 | 29 | 16 | 72 |

## 主检验：选中题目的新增10次回答

新旧Router均在同一批新回答上评价；每题使用原outer fold的预测，该题的新标签不进入自己的训练折。目标是主动选择的uncertain开发子集，不是新query或总体外部确认。

| Router | EQ | Gap Recovery |
|---|---:|---:|
| original_Ridge | 72.04% | 0.00% |
| original_MA | 72.10% | 2.38% |
| original_BestSingle | 72.04% | 0.00% |
| repaired_Ridge | 71.84% | -7.14% |
| repaired_MA | 72.14% | 3.57% |
| repaired_BestSingle | 72.04% | 0.00% |

| 比较 | EQ变化 pp [95% paired query CI] |
|---|---|
| MA_repaired_minus_original | +0.03 [0.00, 0.10] |
| Ridge_repaired_minus_original | -0.19 [-0.58, 0.00] |
| repaired_MA_minus_repaired_Ridge | +0.29 [0.00, 0.78] |
| repaired_MA_minus_original_Ridge | +0.10 [0.00, 0.29] |
| repaired_Ridge_minus_original_BestSingle | -0.19 [-0.68, 0.19] |

## 辅助：共同修复标签的全400题评估

| 比较 | EQ变化 pp [95% CI] |
|---|---|
| MA_repaired_minus_original | +0.24 [-0.05, 0.53] |
| Ridge_repaired_minus_original | +0.05 [-0.20, 0.40] |
| repaired_MA_minus_repaired_Ridge | -0.87 [-1.85, 0.02] |
| repaired_MA_minus_original_Ridge | -0.82 [-1.80, 0.07] |
| repaired_Ridge_minus_original_BestSingle | +1.15 [0.13, 2.27] |

## 最终闸门

no_confirmed_router_improvement_after_bounded_label_repair

正向配对提升支持本固定训练流程受益于监督分辨率，但不能证明它是唯一瓶颈。若标签更明确却没有确认收益，只能说明这次有限补采没有证明Router改善；不能以区间跨0证明完全不可学习。未判定仍不等于near-tie，只有满足后验band规则才报告confident tie。

## 限制与停止条件

- fresh-100替代模型仅在旧Router切换的10题采集，其缺少统计支持的切换不能代表总体机会迁移。此次不改动该确认集。
- confidence-only oracle与修复面板Oracle均为开发诊断上限，不是已证明可学习GAP。
- 信息增益使用独立Jeffreys后验的三个边际sign事件之和，非联合信息量；生成漂移与有限采样仍可能影响结果。
- 全部配对区间以query为单位，3个MA初始化先取实际质量均值。两项主比较另报97.5%区间；不按seed/参数挑选结果。
- 旧5/新10的均值差混合了选择导致的回归均值与时间/服务漂移，单凭它不能归因于后端模型变化。
- 本轮为唯一受控补采，不自动增到25次，不加query、不改encoder/loss/Router、不推GitHub，完成后停止。

Recovered and finalized via AMENDMENT_001_TRANSPORT_RESCUE post-collection path (collector interrupted at 720/1030 by session teardown, resumed to 1030/1030; validator budget extended to rescue ledger under the frozen amendment).
