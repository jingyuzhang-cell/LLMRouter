# 统一报告：六方法工程接入最终核对（2026-10-09）

## 1. 官方 qNEHVI 基线目标一致性核对

| 项目 | 官方 BoTorch qNEHVI | 自建 proposed | 一致性 |
|---|---|---|---|
| 优化目标 | (Q, -C_norm) 双目标 HV | (Q, -C_norm) 双目标 EHVI | ✅ 同一双目标 |
| 目标方向 | Q 最大化，C 最小化（转 -C 最大化）| 同上 | ✅ |
| 归一化 | Q/C 各自 min-max 到 [0,1]（从观测范围）| 同上 | ✅ 同一方法 |
| 参考点 | (0.0, 0.0)（归一化后）| 同上 | ✅ |
| 状态信息权限 | SearchSession 隔离——选择器仅见 candidates+observations，不见 states/faults/gold | 同上 | ✅ |
| L 目标 | 采集函数不含 L（L 仅在 evaluator 输出中记录）| 同上 | ✅ 一致（均未参与选点）|

**已知差异（非不一致，如实登记）**：
- BoTorch 用 `SingleTaskGP`（联合建模 Q 和 C），自建版用 sklearn GP 分别建模 Q
- BoTorch 用 `SobolQMCNormalSampler(64)`，自建版用独立 MC 采样
- 这些是**算法实现差异**，不是目标/方向/口径差异

## 2. 六方法版本对齐核对

所有六方法在**同一版本**的代码上运行（`9d770ef`）：

| 方法 | 选择器实现 | 测试来源 | PASS |
|---|---|---|---|
| proposed_state_incremental | sklearn GP + MC-EHVI + incr_cost predictor | closed_loop_v2 + unified_test | ✅ |
| random | 确定性种子均匀采样 | closed_loop_v2 | ✅ |
| scalarized_bo | sklearn GP + Chebyshev EI | closed_loop_v2 | ✅ |
| official_qnehvi_same_state | **BoTorch SingleTaskGP + qNEHVI** | qnehvi_integration_test | ✅ (9/9) |
| proposed_without_state | 同 proposed，Z 特征置零 | unified_test Part B/C | ✅ |
| proposed_without_incremental_cost | 同 proposed，无成本除数 | unified_test Part B/C | ✅ |

## 3. 证据登记修正

### 3a. "候选数 46→43"更正

**原报告声称**："obs_influence: PASS（分数集从 46→43）证明观测影响选择"

**更正**：候选数从 46 减到 43 仅证明**已选候选被移出候选集**（SearchSession.selected 集合增长），不证明观测改变了选择器的评分或排名。要验证后者需固定剩余候选与采样种子、仅改变已观测 Q/C/L、比较公共候选的分数排名变化。此项登记为"候选集缩减正常"，观测影响选择待专项验证。

### 3b. 此前失败项（按实际结果登记，不改判）

| 项目 | 实际结果 | 状态 |
|---|---|---|
| closed_loop_v2 quality_q_varies | Q 全为 1.0（选择器学到正确行为）| 未通过（需初始含 medium-e 失败配置）|
| closed_loop_v2 quality_q_has_failure | 同上 | 未通过 |
| qNEHVI 对齐 Spearman ρ | 0.345 (p=0.272) | **弱正相关诊断**，未达显著；不宣称数值等价 |
| 成本预测器反例（Track B）| HET-LOCAL +245% → 已修复（增量 vs 部署分离）| PASS（修复后）|

### 3c. 成本预测器登记

Track B 20/20 PASS，但 MAPE=4.5% 基于 Stub shaped 成本；真实模型成本下的精度待真实验证。

## 4. 当前接入状态总表

| 项目 | 状态 | 证据 |
|---|---|---|
| 48 配置空间 | ✅ | evaluator.py:space() |
| JointEvaluator + MeteredExecutor + Budget | ✅ | test_evaluator.py 8/8 + test_runtime.py 10/10 |
| 六方法选择器 | ✅ 全部接通 | closed_loop_v2 + unified_test + qnehvi_integration_test |
| 官方 BoTorch qNEHVI | ✅ 接入 | 9/9 PASS（直接采集函数调用）|
| 增量成本预测器 | ✅（Stub 级）| Track B 20/20 |
| Q 评分正/负对照 | ✅ | 9/9（评分链正常）|
| 消融隔离 | ✅ | unified_test Part B/C |
| FULL 可达性 | ✅ | wiring_test 13/13 + exact_qnehvi_test 8/8 |
| **观测影响选择（专项）** | ❌ 待验证 | 需固定候选+种子，仅变 Q/C/L |
| **真实 LLM 上的 Q 差异化** | ❌ 待真实验证 | Stub 已验证 |
| **成本预测在真实调用下的精度** | ❌ 待真实验证 | Stub shaped 成本已验证 |

## 5. 下一步（按优先级）

1. **FULL/新故障计费小规模真实验证协议**（主任务）
   - 冻结任务、正负对照、调用/Token/墙钟上限、停止规则
2. 数据窗口：独立任务划分 + 样本量依据
3. 观测影响选择专项验证（固定候选+种子，仅变 Q/C/L）
4. 真实六算法比较实验（需全部前置项通过后审批）

---

**声明**：以上为工程接入证据，未证明算法优势，无新增真实调用授权。
