# CASH30_FIXED_FINAL_RESULT — 修复后 ¥0.030 八策略配对（2026-10-27，已执行）

授权合规：**19/25 次尝试 / ¥0.0494/¥0.10 / CashGuard 全臂合规 ✓**。付费 HOLD 恢复。

## 🎯 修复后：JOINT 全面胜出——质量 0.750、按期 58.4s、预算内 ¥0.022

| 策略 | R | π | t_q | Token | makespan | 现金 | 按期 | **eU** |
|---|---|---|---|---|---|---|---|---|
| STATIC/SD-FC | repair_sup2 | 全 Flash | 0.500 | 5,402 | 69.2s | ¥0.000 | ✗ | −2.05 |
| R-only | repair_sup1 | 全 Flash | 0.300 | 3,552 | 60.9s | ¥0.000 | ✗ | −2.03 |
| SEQ-R→π | repair_sup1 | DS(n_sup1,sink)+Flash | 0.350 | 4,045 | 50.8s | ¥0.013 | ✓ | +0.32 |
| SEQ-π→R | repair_sup2 | DS(n_sup2,sink)+Flash | 0.600 | 4,634 | 49.2s | ¥0.015 | ✓ | +0.56 |
| **π-only/Alt/JOINT** | **repair_both** | **Flash(n_sup1,verify)+DS(n_sup2,sink)** | **0.750** | 7,230 | **58.4s** | **¥0.022** | **✓** | **+0.69** |

## JOINT 差值

| 对比 | 差值 | 来源 |
|---|---|---|
| **JOINT − SEQ-π→R** | **+0.13** | 质量 0.750 vs 0.600（修复双分支 vs 单分支） |
| JOINT − SEQ-R→π | +0.37 | 质量+按期差 |
| JOINT − Alternating | 0 | 同动作共享 |
| JOINT − R-only | +2.72 | R-only 迟到 |
| JOINT − SD-FC | +2.73 | SD-FC 迟到 |

## 修复验证

| 指标 | 修复前（bug） | **修复后** |
|---|---|---|
| JOINT sink 输入 | 118 token（空） | **~2000 token（完整事实）** |
| JOINT 质量 | 0.000 | **0.750** |
| repair_both vs repair_sup2 | 0.000 vs 0.550 | **0.750 vs 0.600** |
| "额外恢复导致质量下降" | 表面成立 | **不成立——bug 伪影** |

## 混合 π 机制验证

```
JOINT 选择：repair_both + {n_sup1: Flash(¥0), n_sup2: DS(¥0.007), verify: Flash(¥0), sink: DS(¥0.015)}
总计：¥0.022 ≤ ¥0.030 ✓ | makespan 58.4s ≤ 60s ✓

为什么这是最优联合决策？
- repair_both > repair_sup2：修复双分支比单分支多恢复 13% 独有事实 → 质量 +0.150
- Flash(n_sup1) > DS(n_sup1)：n_sup1 关键事实少（13%），Flash 免费足够
- DS(n_sup2) > Flash(n_sup2)：n_sup2 关键事实多（75%），DS 质量更高
- DS(sink) > Flash(sink)：终端质量决定性节点，DS 优势 +0.100
- Flash(verify) > DS(verify)：verify 不影响 Silver（v2 合同），Flash 免费即可
```

## 三轮实验汇总（bug 修复前后）

| 轮次 | JOINT eU | 最强基线 eU | JOINT 赢？ | 有效？ |
|---|---|---|---|---|
| ¥0.005（超支） | +0.35 | +0.31(SEQ-R→π) | ✓ | **✗ 预算违规** |
| ¥0.030（bug） | −0.04 | +0.51(SEQ-π→R) | ✗ | **✗ facts_json bug** |
| **¥0.030（修复）** | **+0.69** | +0.56(SEQ-π→R) | **✓** | **✓ CashGuard 合规 + 无 bug** |

## 诚实结论

1. **修复后 JOINT 首次在合规条件下胜出**：eU=+0.69，质量 0.750（15/20），按期 58.4s，预算内 ¥0.022
2. **JOINT ≡ π-only ≡ Alternating 仍成立**——联合搜索与最强独立优化等价（同动作）
3. **JOINT > SEQ-π→R (+0.13)** 来自 R 选择差异（repair_both > repair_sup2），非 π 差异
4. **混合 π 机制验证**：Flash 用于免费/低价值节点 + DS 用于付费/高价值节点 = 预算内最优
5. **三轮对比**：修复后 +0.69 是唯一合规且无 bug 的正结果——前两轮的结论分别被预算违规和实现缺陷削弱

**付费 HOLD 恢复。**
