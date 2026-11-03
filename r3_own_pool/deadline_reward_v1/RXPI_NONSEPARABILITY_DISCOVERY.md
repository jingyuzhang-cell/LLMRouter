# RXPI_NONSEPARABILITY_DISCOVERY — R×π 不可分离性发现（2026-10-27，零调用）

## 重大发现：R×π 不可分离性在实测参数空间中真实存在

穷举搜索 **145 个参数组合**（6 截止期 × 7 现金预算 × 4 前缀时延），发现 **45 个
不可分离场景**——最优 R 的选择随 π 改变而翻转。

## 关键场景（D=55s, cash=¥0.020, prefix=30s）

| 策略 | R | π | eU | 与 JOINT 差 |
|---|---|---|---|---|
| STATIC | repair_both | Flash-only | **违反** | — |
| **R-only** | **accept** | Fl(v)+Fl(s) | +0.110 | **+0.598** |
| **SEQ-R→π** | **accept** | Fl(v)+DS(s) | +0.118 | **+0.589** |
| **π-only(FULL)** | repair_sup2 | DS(sup2)+Fl(v)+DS(s) | +0.708 | **0** |
| **SEQ-π→R** | repair_sup2 | DS(sup2)+Fl(v)+DS(s) | +0.708 | **0** |
| **Alternating** | repair_sup2 | DS(sup2)+Fl(v)+DS(s) | +0.708 | **0** |
| **JOINT** | **repair_sup2** | **DS(sup2)+Fl(v)+DS(s)** | **+0.708** | — |

## 不可分离性的精确机制

```
SEQ-R→π 的决策过程：
  Step 1: 用 Flash 检查 R → repair 需 27s+ 但 Flash-only 时延不够 → 选 accept
  Step 2: 对 accept 优化 π → Fl(v)+DS(s) → eU=+0.118

JOINT 的决策过程：
  同时枚举所有 (R,π) → 发现 repair_sup2 + DS(sup2)+DS(v)+Fl(s) = 15.6s ¥0.019 可行
  → eU=+0.708

关键：Flash-only 假设下 repair 不可行（Flash 时延太长）
      但用 DS 替换 sup2+verify 后，repair 变得可行且质量大幅提升
      SEQ-R→π 在 Step 1 就锁定了 accept，永远无法发现这一点
```

**这是真正的 R×π 耦合**：
- π 决定 R 的可行性（Flash-only 下 repair 不可行；混合 π 下 repair 可行）
- R 决定 π 的最优分配（accept 时不需要 DS；repair 时需要 DS 关键节点）

## 对各策略的影响

| 策略 | 找到最优？ | 原因 |
|---|---|---|
| STATIC | ✗ | 不重规划，违反约束 |
| R-only | ✗ (差 0.60) | Flash-only 检查锁定 accept |
| **SEQ-R→π** | **✗ (差 0.59)** | **Flash-first R 决策锁死了 repair 选项** |
| π-only(FULL) | ✓ | 重分配所有节点模型，包括将 DS 用于使 repair 可行 |
| SEQ-π→R | ✓ | 先优化 π（发现 DS 使 repair 可行），再选 R |
| Alternating | ✓ | 迭代中第二次 R 检查用了 DS 更新后的时延 |
| **JOINT** | ✓ | 联合枚举自然发现最优 |

## 诚实边界

1. **JOINT ≡ π-only(FULL) ≡ SEQ-π→R ≡ Alternating**——四者等价
2. **JOINT > SEQ-R→π (+0.59)**——首个真实的顺序决策失败
3. **不可分离性来自现金维度**（Flash 免费+慢 vs DS 付费+快），不需要非单调时延
4. **用户先前的理论判断正确**：非单调矩阵不是必要条件，预算竞争足够

## 论文贡献的精确定位

| 已证明 | 未证明 |
|---|---|
| R×π 不可分离性存在（45/145 场景） | JOINT > π-only/SEQ-π→R/Alternating |
| SEQ-R→π 在不可分离场景失败（+0.59 差距） | 联合搜索相对完整重规划的独有优势 |
| 混合 π 在现金约束下最优 | 多时点反馈中的持续优势 |
| 动态重规划使不可行变为可行 | |

**核心发现**：联合调度的价值不在于"找到比 π-only 更好的动作"（它们等价），而在于
**避免"Flash-first 顺序决策锁死恢复选项"**——这是 R 与 π 耦合时顺序策略的结构性盲区。

**付费 HOLD 保持。**
