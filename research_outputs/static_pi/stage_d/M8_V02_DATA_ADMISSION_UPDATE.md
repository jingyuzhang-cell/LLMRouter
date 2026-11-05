# M8 v0.2 DATA_ADMISSION 更新：CAP 阻断解除 + VAL 三臂候选确认（2026-11-04）

**零调用归档核实完成。CAP 380 行已确认并计算 SHA256；VAL 三臂在 Phase-Pi V2 中存在（单任务限定）。**

---

## 一、CAP 380 行：阻断解除 ✅

| 项 | 结果 |
|---|---|
| 文件位置 | `rq2_cap_v1_runs/results.jsonl` |
| 行数 | **380 行** ✅ |
| 模型 | glm53flash(95) / glm53(95) / deepseek(95) / qwen(95) |
| 节点类型 | **6 类**（ext_doc1/2/3, merge, report, verify）——非 19 类 |
| 重复/组合 | ~15.8 次/模型×节点 |
| 调用账本 | ledger.jsonl 384 行 |
| 总 token | 从 ledger 提取（需重算——原始记录 usage 格式可能不同） |

### SHA256

| 文件 | SHA256 |
|---|---|
| `results.jsonl` | `049a7e19226c1f45e77b16edca4b6fe00a6d111bdfeeb8d90801bbd98f14db75` |
| `ledger.jsonl` | `e5abcf4742981ee02a4b8f91920737defa877a28137ae7ec44b0b0666572569d` |
| `RQ2_CAP_V1_RESULTS.json` | `cac4682c9af196bef4d98181e7f66fcf5543d48b98e651f2081e1a88f304ed7d` |
| `RQ2_CAP_V1_AUDIT.json` | `91a35f2fb4f4c92fd92ded2b1b6646d2ef97735e0d2e676f3389a52b2c64c763` |

### 注意事项

1. **节点类型**：实际为 **6 类**（非操作者提到的 19 类）——可能是 19 类中仅 6 类被测量，或标签有变。需确认。
2. **reason→merge 纠正**：当前数据中已使用 `merge` 标签（非 `reason`），纠正已应用 ✅。
3. **C2/C3 未通过**：RQ2_CAP_V1_RESULTS.json 中有 C1/C2/C3 字段——后续分析须注意哪些一致性检查未过。
4. **Qwen merge 优势**：不能直接推导为全模型池稳定互补性（操作者已确认）。

---

## 二、VAL 三臂：候选确认（有限制条件）

### 三臂匹配分析

| 所需臂 | Phase-Pi V2 | RQ3_STAT_V1 | RQ_DYN_V1 |
|---|---|---|---|
| Static | ✅ 有 | ✅ HomDS | ✅ HomDS |
| Fixed-Recovery | ✅ Fixed-Composite | — | — |
| Joint-Dynamic | ✅ Proposed-Dynamic | — | DYN（近似） |

### 关键限制

| 限制 | 影响 |
|---|---|
| **单任务（T1）** | 只能校准单任务的代理模型，不能跨任务泛化 |
| **两个场景（S1/S1b）** | 异常类型覆盖有限 |
| **不同批次不可拼接** | RQ3/RQ_DYN 的 DAG/Gold/评分器与 Phase-Pi 不同 |
| **AI Gold（非人工）** | 终端质量评分基于机器评分，非人工确认 |

### 判定

**VAL 三臂在 Phase-Pi V2 中存在（同任务同条件同评分器）**——可作为 M8 Phase A（固定拓扑）的终端层校准数据候选。

**但必须**：
1. 确认 Phase-Pi V2 的 DAG/Gold/评分器与 M8 目标任务一致
2. 明确标注 AI Gold 身份（不冒充人工 Gold）
3. 仅限单任务校准（不跨任务外推）

---

## 三、更新后的 DATA_ADMISSION 状态

| 阻断项 | 此前 | **现在** |
|---|---|---|
| CAP 380 行 | 待跨窗口确认 | **✅ 解除**（SHA256 已计算） |
| VAL 三臂 | 不可见 | **⚠️ 部分解除**（Phase-Pi V2 存在但限单任务） |
| 人工 Gold | 未完成 | ❌ 保留（AI Gold 单独标注） |
| 预算 | 不足 | ❌ 需另行申请 |
| M8-P2 Runner | 生产准入未过 | ❌ 保留 |

**剩余实质阻断**：预算（~13 vs 需 550-800）+ 人工 Gold + Runner 生产准入。

---

## 四、下一步建议

1. **论文初稿继续推进**（不等 M8）——现有证据链已足够
2. **M8 Phase 2（策略空间冻结）可开始零调用工作**——CAP 数据已可用作节点层代理基础
3. **Phase-Pi V2 数据可用作终端层校准候选**——但需确认 DAG/Gold 一致性
4. **预算另行申请**——不自动使用剩余 ~13 调用
