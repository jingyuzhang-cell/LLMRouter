# Fin-RoMe v4 Phase 2.4: Reproducibility Hardening Report

**生成时间:** 2026-08-19T01:51:15.337174+00:00
**版本:** 2.4_reproducibility_hardening
**随机种子:** 42
**运行次数:** 5

## 执行摘要

**总体一致性:** ❌ 失败
**首次不一致阶段:** FINAL_SELECTIONS
**原因:** Selection hashes 不一致

## 环境配置

**系统配置:**
- Python 版本: 3.12.3
- NumPy 版本: 2.3.2
- PyTorch 版本: 2.8.0+cu128
- CUDA 版本: 12.8
- cuDNN 版本: 91002
- Device: NVIDIA GeForce RTX 4090

**环境变量:**
- PYTHONHASHSEED: 42
- CUBLAS_WORKSPACE_CONFIG: :4096:8
- OMP_NUM_THREADS: 1
- MKL_NUM_THREADS: 1

**随机性配置:**
- torch.backends.cudnn.deterministic: True
- torch.backends.cudnn.benchmark: False
- torch.use_deterministic_algorithms: True
- Python random: seeded
- NumPy random: seeded
- PyTorch random: seeded

## 运行详情


### Run 1

- **成功:** ✅
- **时间戳:** 2026-08-19T01:49:37.237045+00:00
- **Selections Hash:** `9bfb7351216ba2c7`
- **M3 Gate:** ❌ FAIL

**关键指标:**

| 方法 | Utility | Failure | High-Risk Failure |
|------|---------|---------|-------------------|
| M1 | 0.8350752467 | 0.1500000000 | 0.0000000000 |
| M2 | 0.8646829742 | 0.3000000000 | 0.0000000000 |
| M3 | 0.8644851708 | 0.3000000000 | 0.0000000000 |

**M3 vs M2:**
- Utility 差: -0.0001978033
- Failure 差: 0.0000000000

### Run 2

- **成功:** ✅
- **时间戳:** 2026-08-19T01:50:01.558229+00:00
- **Selections Hash:** `9bfb7351216ba2c7`
- **M3 Gate:** ❌ FAIL

**关键指标:**

| 方法 | Utility | Failure | High-Risk Failure |
|------|---------|---------|-------------------|
| M1 | 0.8350752467 | 0.1500000000 | 0.0000000000 |
| M2 | 0.8646829742 | 0.3000000000 | 0.0000000000 |
| M3 | 0.8644851708 | 0.3000000000 | 0.0000000000 |

**M3 vs M2:**
- Utility 差: -0.0001978033
- Failure 差: 0.0000000000

### Run 3

- **成功:** ✅
- **时间戳:** 2026-08-19T01:50:28.729546+00:00
- **Selections Hash:** `8d96d32246724d9a`
- **M3 Gate:** ✅ PASS

**关键指标:**

| 方法 | Utility | Failure | High-Risk Failure |
|------|---------|---------|-------------------|
| M1 | 0.8350752467 | 0.1500000000 | 0.0000000000 |
| M2 | 0.8646829742 | 0.3000000000 | 0.0000000000 |
| M3 | 0.8654404733 | 0.3000000000 | 0.0000000000 |

**M3 vs M2:**
- Utility 差: 0.0007574992
- Failure 差: 0.0000000000

### Run 4

- **成功:** ✅
- **时间戳:** 2026-08-19T01:50:50.344948+00:00
- **Selections Hash:** `72dc1c68e3f1a440`
- **M3 Gate:** ✅ PASS

**关键指标:**

| 方法 | Utility | Failure | High-Risk Failure |
|------|---------|---------|-------------------|
| M1 | 0.8350752467 | 0.1500000000 | 0.0000000000 |
| M2 | 0.8646829742 | 0.3000000000 | 0.0000000000 |
| M3 | 0.8653979258 | 0.3000000000 | 0.0000000000 |

**M3 vs M2:**
- Utility 差: 0.0007149517
- Failure 差: 0.0000000000

### Run 5

- **成功:** ✅
- **时间戳:** 2026-08-19T01:51:13.336981+00:00
- **Selections Hash:** `9bfb7351216ba2c7`
- **M3 Gate:** ❌ FAIL

**关键指标:**

| 方法 | Utility | Failure | High-Risk Failure |
|------|---------|---------|-------------------|
| M1 | 0.8350752467 | 0.1500000000 | 0.0000000000 |
| M2 | 0.8646829742 | 0.3000000000 | 0.0000000000 |
| M3 | 0.8644851708 | 0.3000000000 | 0.0000000000 |

**M3 vs M2:**
- Utility 差: -0.0001978033
- Failure 差: 0.0000000000

## 一致性检查

### 成功条件

**要求 5/5 完全一致:**
- selection_hashes_consistent: ❌
- all_consistent: ❌

**最终判定:** ❌ REPRODUCIBILITY_FAILURE

### 不一致详情

**首次不一致阶段:** `FINAL_SELECTIONS`

**原因:** Selection hashes 不一致

### 下一步行动

1. 定位导致不一致的随机源
2. 检查 Router 训练的随机性控制
3. 检查 tie-breaking 规则
4. 检查 OOF fold 分割的确定性
5. 禁止运行 test，禁止进入 Phase 3

## M3 Gate 稳定性分析

**M3 vs M2 Utility 差异:**

- 各次运行差异: ['-0.0001978033', '-0.0001978033', '0.0007574992', '0.0007149517', '-0.0001978033']
- 最大值: 0.0007574992
- 最小值: -0.0001978033
- 范围: 0.0009553025

**稳定性评估:**

❌ **不稳定** - M3 vs M2 utility 差异范围较大 (9.55e-04)，表明存在未控制的随机性。

## 关键统计

**平均性能 (5次运行):**

| 方法 | 平均 Utility | 平均 Failure |
|------|-------------|-------------|
| M1 | 0.8350752467 | 0.1500000000 |
| M2 | 0.8646829742 | 0.3000000000 |
| M3 | 0.8648587823 | 0.3000000000 |

**M3 Gate 统计:**
- 通过率: 40.0%
- 各次状态: ['FAIL', 'FAIL', 'PASS', 'PASS', 'FAIL']
- 平均 Utility 差: 0.0001758082

## 下一步建议

**如果 REPRODUCIBILITY_PASS:**
- 可复现性已修复，可以进入 Phase 3
- 基于 M1 为安全锚点，探索 Safety-Preserving Dynamic Fusion
- M1 安全优势已通过真实 failure 数据验证

**如果 REPRODUCIBILITY_FAILURE:**
- 必须先解决可复现性问题，不能进入 Phase 3
- 重点检查不一致的阶段: `FINAL_SELECTIONS`
- 严禁通过调整参数、放宽 epsilon 来"解决"可复现性

**当前 M3 Gate 状态 (基于稳定结果):**

- ⚠️ M3 Gate 不稳定，无法确定最终状态
- 各次通过率: 40.0%
- 必须先解决可复现性


## 技术审计清单

**✅ 已完成:**
- 全局随机性设置 (seed=42)
- PyTorch deterministic 模式
- CUDA workspace 配置
- 线程数量固定
- Python hash seed 固定

**🔍 需要进一步检查 (如果 REPRODUCIBILITY_FAILURE):**
- KNN neighbor 顺序 tie-breaking
- MLP 权重初始化、batch 顺序、optimizer 随机性
- GraphRouter 初始化、edge/node 顺序、negative sampling
- 5-fold OOF fold 分割确定性
- Meta Predictor random_state 设置
- 所有 argmax/argsort/rank 的 tie-breaking 规则

**❌ 禁止的操作:**
- 修改 M1/M2/M3 算法逻辑
- 调整 gate threshold
- Round utility 值
- 放宽 epsilon 容差
- 修改 gate 判定条件

---

**Phase 2.4 Reproducibility Hardening 完成**

**输出文件:**
- Reproducibility 报告: /root/phase2_4_reproducibility_output/FINROME_V4_PHASE2_4_REPRODUCIBILITY.md
- JSON 数据: finrome_v4_phase2_4_reproducibility.json
- 阶段 hash 数据: finrome_v4_phase2_4_stage_hashes.json
