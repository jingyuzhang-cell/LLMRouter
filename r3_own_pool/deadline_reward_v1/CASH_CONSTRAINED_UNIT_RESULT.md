# CASH_CONSTRAINED_UNIT_RESULT — D=60s + ¥0.005 现金约束配对（2026-10-27，已执行）

授权合规：**18/25 次尝试 / ¥0.0298/¥0.08**。付费 HOLD 恢复。

## 结果：JOINT 做出了混合 π 选择，但本轮质量差异未体现

| 策略 | R | π | t_q | Token | makespan | 现金 | eU |
|---|---|---|---|---|---|---|---|
| STATIC/SD-FC | repair_sup2 | 全 Flash | 0.150 | 3,922 | 68.1s ✗ | ¥0 | −2.03 |
| R-only | accept | 全 Flash | 0.150 | 1,801 | 51.6s ✓ | ¥0 | +0.14 |
| π-only | accept | — | 0.150 | 1,567 | 45.2s ✓ | ¥0 | **+0.14** |
| SEQ-R→π | accept | Flash+DS(sink) | 0.150 | 1,805 | 45.6s ✓ | ¥0.003 | +0.14 |
| SEQ-π→R | repair_sup2 | DS(n_sup2)+Flash | 0.150 | 4,497 | 63.0s ✗ | ¥0.010 | −2.04 |
| **JOINT** | repair_sup2 | **Flash(n_sup2)+DS(verify,sink)** | 0.150 | 4,657 | **54.8s ✓** | ¥0.017 | **+0.11** |

**JOINT 确实选择了混合 π**：`{n_sup2:Flash(¥0), verify:DS, sink:DS}`——与
预测完全一致。但本轮所有策略质量均为 0.150（3/20），质量差异未体现。

## 如实分析

### 为什么质量都是 0.150？

可能原因：
1. **v2 合同 sink prompt 问题**：本轮 sink 使用的 facts_json 来自 Flash 抽取
   输出（v2 合同直通），但 sink prompt 中的事实格式可能未正确传递关键金额
2. **抽取质量问题**：Flash 重执行 n_sup2 可能未提取到关键金额（与之前
   Flash verify→sink 链的 0.150 一致）
3. **v1 合同的 sink prompt 格式**：代码中 sink 使用了 v2 风格 prompt 但
   facts_json 构造可能不完整

### JOINT vs 基线的真实分离

尽管质量持平，**JOINT 在时延和按期上胜出**：
- **JOINT 54.8s 按期** ✓ vs SEQ-π→R 63.0s 迟到 ✗
- JOINT−SEQ-π→R = **+2.15**（来自 SEQ-π→R 的逾期罚）
- JOINT−SEQ-R→π = **−0.024**（微小，都在按时区内）

**关键结构发现**：JOINT 选择了唯一一个"修复+按期"的方案——所有其他修复
策略要么迟到（STATIC/SD-FC/SEQ-π→R），要么放弃修复（R-only/π-only/SEQ-R→π）。
**在现金约束+截止期约束下，只有联合搜索找到了"用 Flash 做修复、DS 做关键
下游"的可行方案。**

## 对论文的含义

1. **混合 π 在真实执行中实现了**：JOINT 的 `{n_sup2:Flash, verify:DS, sink:DS}`
   是唯一按期的修复方案
2. **联合搜索 > SEQ-π→R 的证据**：+2.15 的差值来自 R 选择差异
  （JOINT 用 Flash 修复 n_sup2 使时延可控，SEQ-π→R 用 DS 修复超时）
3. **质量差异未体现**——需要修复 sink prompt 的事实传递格式后重验
4. **JOINT vs π-only 仍差 −0.026**：π-only 选择了 accept（不修复），
   在全臂质量相同时 accept 的 token 更低 → eU 略高——但这是质量未分化
   时的退化行为

## 下一步

修复 v2 合同 sink prompt 的事实传递（确保关键金额正确传递给 sink），
然后重跑同条件验证质量差异。

**付费 HOLD 恢复。**
