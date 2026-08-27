# Fin-RoME v4 Phase 2.4.2: Final Sanity Audit - 执行摘要

**完成时间:** 2026-08-19
**状态:** ✅ 通过
**审计结果:** REPRODUCIBILITY_PASS - 可以进入 Phase 3

---

## 🎯 核心任务完成情况

### ✅ 1. OOF 任务数量差异已解决
- **问题:** Train manifest 60 tasks vs OOF manifest 59 tasks
- **原因:** Rare label 过滤 - 任务 `finance_dataset_93c842a1-5a07-40cf-a651-63d7d5b22557` 的最佳模型是 glm-5.2，该模型在训练集中仅出现 1 次
- **结论:** ✅ **OOF_COVERAGE_VALID** - 合理排除

**Label distribution in training set:**
- Model 3 (qwen-turbo): 34 tasks
- Model 0 (deepseek-chat): 20 tasks  
- Model 2 (qwen-plus): 5 tasks
- Model 1 (glm-5.2): 1 task ← **Rare label**

### ✅ 2. Utility Diff 错误已修复
- **原错误显示:** `Utility Diff (M3-M2): +0.0012`
- **修复后正确值:** `Utility Diff (M3-M2): +0.0001434533`
- **修复方法:** 从 Phase 2.4.1 JSON 自动计算，禁止手工填写

### ✅ 3. High-Risk Failure Metrics 已验证
- **Calibration Risk Distribution:** 6 high-risk, 14 medium-risk, 0 low-risk
- **High-Risk Failure Statistics:**
  - M1: 2/6 (33.3%)
  - M2: 3/6 (50.0%)  
  - M3: 3/6 (50.0%)
- **结论:** ✅ 分母正确，指标有效

---

## 📊 最终冻结的开发指标（自动验证）

| 方法 | Utility | Failure | Failure Count | High-Risk Failure |
|------|---------|---------|---------------|-------------------|
| M1 | 0.8350752467 | **15%** | **3/20** | 2/6 (33.3%) |
| M2 | 0.8654756200 | **30%** | **6/20** | 3/6 (50.0%) |
| M3 | 0.8656190733 | **30%** | **6/20** | 3/6 (50.0%) |

### Utility Diff 比较

| 对比 | 差值 | 说明 |
|------|------|------|
| M3 - M2 | **+0.0001434533** | ✅ 已修复原 Summary 错误 +0.0012 |
| M3 - M1 | +0.0305438267 | M3 相对 M1 的优势 |
| M2 - M1 | +0.0304003733 | M2 相对 M1 的优势 |

### M3 Gate 状态

- **Method:** M3_conformal
- **Status:** ✅ PASS
- **Utility Gain:** +0.0001434533 (极小)

### Training Set Coverage

- **Train Manifest:** 60 tasks
- **Effective OOF Training:** 59 tasks
- **Coverage:** 98.3%
- **排除原因:** Rare label - glm-5.2 仅出现 1 次作为最佳模型

---

## 🔧 方法漂移修复确认

### Phase 2.4 → 2.4.2 对比

| 方面 | Phase 2.4 | Phase 2.4.1 | Phase 2.4.2 | 影响 |
|------|-----------|-------------|-------------|------|
| OOF 协议 | KFold(5, shuffle=False) | KFold(5, shuffle=True, random_state=42) + 固定 manifest | 同 2.4.1 + 验证 | ✅ 恢复原设计 + 验证 |
| Tie-breaking | 确定性规则 (ε=1e-10) | 明确区分 exact tie vs near-tie | 同 2.4.1 | ✅ 更精确 |
| M1/M2 逻辑 | 未改变 | 未改变 | 未改变 | ✅ 无变化 |
| M3 Gate 逻辑 | 未改变 | 未改变 | 未改变 | ✅ 无变化 |
| Utility Diff | +0.0012 (错误) | 同 2.4 | +0.0001434533 (修复) | ✅ 修复 |

---

## 📋 研究方向明确

### 当前方法对比

| 方法 | Utility | Failure | 特点 |
|------|---------|---------|------|
| M1 Equal-Rank | 0.8351 | **15%** | ✅ 安全，但 Utility 较低 |
| M2 Dynamic | 0.8655 | **30%** | ✅ Utility 高，但 Failure 翻倍 |
| M3 Conformal | 0.8656 | **30%** | ⚠️ Utility 略高于 M2 (+0.00014)，但相同 Failure |

### 核心矛盾

**M1 vs M2/M3 的权衡:**
- **M1 优势:** 15% failure rate (最佳安全性)
- **M2/M3 优势:** 更高的 utility (+0.03)
- **M3 特点:** 满足 gate，但相对 M2 的 utility 优势极小 (+0.00014)

### Phase 3 研究问题

**能否保住 M1 的安全性，同时拿到 M2/M3 的 Utility？**

这就是 **Safety-Preserving Dynamic Fusion**。

---

## 🚀 Phase 3 设计建议

### Safety Anchor 架构

```
KNN / MLP / Graph
        │
        ├──────────────→ M1 Equal-Rank
        │                    │
        │                Safety Anchor
        │
        └──────────────→ M2 / M3
                             │
                      Dynamic Proposal
                             │
                             ▼
                    Safety Override Gate
                             │
              ┌──────────────┴──────────────┐
              │                             │
        安全证据不足                    安全证据充分
              │                             │
              ▼                             ▼
          保持 M1                     接受 M2/M3
```

### Override Gate 逻辑

**最终选择:**
```python
m_final = m_proposal if safe_to_override else m_M1
```

### Gate 输入（仅推理时可用信息）

- M1/M2/M3 disagreement
- Router margins
- Router entropy
- Router confidence
- Predicted failure
- Predicted regret
- OOD score
- Risk level
- M1-vs-proposal predicted utility gain

### Gate 禁止输入（真实结果）

- ❌ Quality
- ❌ Failure
- ❌ Utility
- ❌ Oracle

### Override 条件

**基本条件:**
- ΔU > 0 (预期 utility 提升)
- ΔF ≤ 0 (预期 failure 不增加)

**严格条件:**
- 置信界满足安全条件

### Phase 3 第一版

**最小原型:**
1. 识别 M1 与 M2/M3 发生分歧的任务
2. 只在这些任务上启动 Override Gate
3. 简单的二元决策：保持 M1 或接受 Proposal

**重点:** 不是做第四个普通加权融合器，而是设计受约束的安全覆盖机制。

---

## 🎓 学术贡献

### 1. 可复现性方法论
- **协议保持 + 固定 manifest** 的模式
- 既保留原实验设计（shuffle=True），又实现完全可复现性
- 可用于其他需要 shuffle 但要求可复现的实验

### 2. 确定性选择规则
- 明确区分 exact tie-breaking vs near-tie threshold
- 避免用可调 epsilon 改变正常非并列候选的算法决策
- 提供可审计的 tolerance 触发报告

### 3. 数据一致性验证
- 自动验证多源数据一致性
- 解决报告冲突问题（如 30% vs 35% failure rate）
- 自动计算指标，禁止手工填写

---

## 📁 输出文件

**核心文件:**
1. 📄 **Phase 2.4.1 审计报告:** [`FINROME_V4_PHASE2_4_1_PROTOCOL_AUDIT.md`](FINROME_V4_PHASE2_4_1_PROTOCOL_AUDIT.md)
2. 📄 **Phase 2.4.2 审计报告:** [`FINROME_V4_PHASE2_4_2_FINAL_SANITY_AUDIT.md`](FINROME_V4_PHASE2_4_2_FINAL_SANITY_AUDIT.md)
3. 📊 **Phase 2.4.2 JSON 数据:** [`finrome_v4_phase2_4_2_final_metrics.json`](finrome_v4_phase2_4_2_final_metrics.json)
4. 🔧 **OOF Fold Manifest:** [`finrome_v4_oof_fold_manifest.json`](finrome_v4_oof_fold_manifest.json)
5. 📝 **Phase 2.4.1 Summary:** [`FINROME_V4_PHASE2_4_1_SUMMARY.md`](FINROME_V4_PHASE2_4_1_SUMMARY.md)

---

## 🏆 研究路线确认

### ✅ 已完成阶段

- ✅ Phase 0: Leakage Cleanup
- ✅ Phase 1: Metric / Oracle
- ✅ Phase 2: Router Reconstruction
- ✅ Phase 2.2: Formal Pipeline
- ✅ Phase 2.3: True-Failure Mechanism Audit
- ✅ Phase 2.4: Reproducibility
- ✅ Phase 2.4.1: Protocol-Preserving Repro
- ✅ Phase 2.4.2: Final Sanity Audit ← 当前

### 🚀 待完成阶段

- ⏸ Phase 3: Safety-Preserving Dynamic Fusion
- ⏸ Phase 4: Verifier / Abstention
- 🔒 Phase 5: Independent Test

---

## 🎯 结论

### ✅ 口径问题已完全清理

1. **OOF 任务数量:** 60→59 已合理解释（rare label 过滤）
2. **Utility Diff:** +0.0012 → +0.0001434533 已修复
3. **High-Risk 指标:** 分母问题已正确处理（6 high-risk tasks）

### ✅ 可以正式进入 Phase 3

**研究对象明确:** M1 安全锚点 vs M2/M3 高 Utility 的矛盾

**研究目标:** 设计受约束的安全覆盖机制，保住 M1 安全性的同时获取 M2/M3 的高 Utility

**不再是:** 围绕"稳定性"反复折腾

**现在是:** 真正的研究创新：Safety-Preserving Dynamic Fusion

### 📋 Phase 3 研究计划

**第一版目标:**
- 实现 M1 作为 Safety Anchor
- 设计 Safety Override Gate
- 只在 M1 与 M2/M3 分歧时启动覆盖决策
- 简单的二元安全决策逻辑

**预期成果:**
- 如果成功：保住 M1 的 15% failure，同时获得接近 M2/M3 的 utility
- 如果失败：理解安全-utility 权衡的本质

---

**Phase 2.4.2 Final Sanity Audit 完成**

**审计结果:** ✅ REPRODUCIBILITY_PASS - 可以进入 Phase 3

**下一步:** 🚀 Phase 3: Safety-Preserving Dynamic Fusion