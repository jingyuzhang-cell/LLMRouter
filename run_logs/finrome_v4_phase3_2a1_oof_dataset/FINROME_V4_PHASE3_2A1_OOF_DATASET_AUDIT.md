# Fin-RoME v4 Phase 3.2A.1: Train OOF Anchor–Proposal Dataset Audit

**生成时间:** 2026-08-19T14:50:30.205271+00:00
**版本:** 3.2a1_oof_dataset_audit

## Phase 3.2A.1 概述

Phase 3.2A.1 专门审计 Train OOF Anchor–Proposal Dataset 的构建状态。

### 核心问题

- **OOF Status:** `OOF_COVERAGE_OK`
- **Training Data Status:** `SUFFICIENT_GATE_DATA`

## Train OOF Coverage 统计

| 指标 | 数量 | 说明 |
|------|------|------|
| Manifest Train Count | 60 | Split definition 中的 train 任务数 |
| OOF Holdout Eligible | 59 | OOF fold 中的 holdout 任务数 |
| Rare Train Only | 0 | 稀有 train-only 样本 |
| OOF Prediction Count | 59 | 实际生成的 OOF 预测数 |
| Coverage Ratio | 98.3% | OOF 覆盖率 |

## M1-M3 Disagreement 统计

| 指标 | 数量 | 百分比 |
|------|------|--------|
| M1=M3 (Agree) | 9 | - |
| M1≠M3 (Disagree) | 50 | - |
| Total OOF Tasks | 59 | 100% |

## Override Label 分布

| Label | 数量 | 百分比 |
|-------|------|--------|
| BENEFICIAL | 41 | - |
| SAFETY_HARM | 2 | - |
| UTILITY_HARM | 7 | - |
| NEUTRAL | 9 | - |
| Total | 59 | 100% |

## 状态分析

### ✅ SUFFICIENT_GATE_DATA

**含义：** 生成了合法的 OOF Selections，Disagreement Samples 数量充足 (>= 10)

**M1≠M3 (Disagree):** 50
**Training Data Status:** Sufficient

**处理：** 可以进入 Phase 3.2A.2 训练 Gate predictor。
## 关键发现

### ✅ 成功生成 Train OOF Dataset

**Disagreement Count:** 50
**Training Data Status:** Sufficient

**Override Label 分布：**
- BENEFICIAL: 41
- SAFETY_HARM: 2
- UTILITY_HARM: 7
- NEUTRAL: 9

可以进入 Phase 3.2A.2 训练 Gate predictor。
## 下一步建议

### ✅ 可以继续 Phase 3.2A.2

- 训练 Gate predictor (ΔU 和 ΔP_F 预测器)
- 实现 SPDF Gate with 真实 OOF 预测
## 项目状态更新

| Phase | 状态 | 说明 |
|-------|------|------|
| Phase 3.1 Baseline Fidelity | ✅ | 冻结 baseline，5次运行完全可复现 |
| Phase 3.2 Frozen SPDF pipeline | ✅ | 工程链路打通 |
| Phase 3.2 SPDF effectiveness | ❌ | 尚未证明（当前为NO-OP）|
| Phase 3.2A Gate diagnosis | ✅ | 完成诊断，发现FAILURE_GATE_BLOCKED |
| Phase 3.2A.1 OOF dataset | 🔄 | **本阶段完成** |
| Phase 3.2A.2 Gate predictor | ⏸ | 待根据本阶段结果决定 |
| Phase 3.2B Threshold calibration | ⏸ | 暂时禁止 |
| Phase 4 Verifier/Abstention | 🔒 | 暂时禁止 |
| Independent Test | 🔒 | 暂时禁止 |
