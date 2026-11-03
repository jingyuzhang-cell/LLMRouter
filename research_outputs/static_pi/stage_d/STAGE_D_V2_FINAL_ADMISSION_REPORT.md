# STAGE_D_V2 最终准入报告（A‴；PASS/FAIL/BLOCKED 逐项）

**日期**：2026-11-03。**候选**：`stage_d_v2_executor.py` sha `174c3ed06d3546c5…`（+ 配置 `914f3edd…`、测试 `942fe064…`、清单 `STAGE_D_V2_A3_FREEZE.json`）。
**本轮零 API、零 GPU、零 Key 读取/输出；未创建 `runs_final`；未设置任何真实 GO 门。**

---

## 逐项判定

### 1. 192-run 矩阵与六臂各 32 — **PASS**
`verify_matrix`：192 唯一、六臂各 32（`test_stage_d_v2.py::R04`；192 Mock 实测 per_arm 全 32）。

### 2. 模型池与合法 π 动作空间 — **PASS（证据驱动收窄）**
- 默认路由 AROUT（六臂统一）：E\*/J2/SINK=deepseek@4000、J1=glm53flash@8192；AMAX 已冻结。
- π 空间：`J1:GLM→DS` 已验证（P-J1DS/2：2.8s、判定 4/4 正确）；`J2/SINK:DS→GLM` 证据为负排除；`E:GLM→DS` 无意义（E 已 DS 默认）、`E:DS→GLM` 不可靠排除。**六臂对称**（R03 对称性测试：六臂同路由全过）。
- 执行器动作层 `policy()` 的 `swap` 语义在 A‴ 下由 S5′ 显式实现（`cond_swap_j1`）；通用异常路径的 swap 动作对象仍受 AROUT/AMAX 约束（DS→GLM 方向在 J2/SINK 不可达，模型池层面无该目标）。

### 3. 截止期最终冻结口径 — **PASS（冻结 300s）**
- 推导值 240s（A‴ 串行链 88–140s 模型值）；**实测 72.77s**。
- **冻结口径：全场景 300s**（保守上限，实测 4 倍裕度；S5′ 无 90s 特例；SLO 9.5s 作废，执行器 slo_s 置占位）。
- 240s 作为"推导参考值"记录，不作执行参数。

### 4. 硬预算 — **PASS（12M / ¥40 / 2,688）**
配置已冻结：tokens 12,000,000（A‴ 估算 ≈4.0M，3 倍裕度）、¥40（DS 实付估算 ≈¥12）、calls 2,688（估算 ≈1,460–1,730）。预留台账机制未动（P0-3 测试过）。

### 5. R1 真实保护集与首批 24 stop-gate — **PASS（设计；数据侧 BLOCKED 属预期）**
规格/基线/审计器零改动；首批 24（冻结顺序覆盖 S3/S4/S5 各一个完整六臂块=144/1,152 槽-run）→ `protection_set_audit.py runs_final` → FAIL(≥2) 全停。Mock 审计不作证据（fixture 限制已记录）。

### 6. exact paired permutation 统计方案 — **PASS（沿用，功效待回代）**
`exact_perm.py`（CORE-19 冻结）+ `exact_perm_dp.py`；主检验 S3+S4 合并 16 对精确符号翻转；设计先验功效 0.776 沿用为**设计假设**；**首批真实数据回代后复核**（不足即如实报告，不作确认性主张）。V3/旧双合同并列；合同分差不作能力宣称。

### 7. GLM 额度容量 — **BLOCKED（仅可由真实首批验证）**
订阅 key（Fhzp）已承受 5 次 GLM 调用（≈24k token）；192-run 需 ≈1,920 次 GLM-J1 调用 ≈1.2M token——**容量无法零调用核验**，首批 24（≈120 次 GLM 调用）为首个真实压力点；429/额度异常 → 按停止规则全停。

### 8. Stage2b 原始结果与哈希保全 — **PASS**
`v2_pilot/stage2b/STAGE2B_RESULT.json` + `nodes/`（7 节点全文）哈希入 `STAGE_D_V2_A3_FREEZE.json`；A1 执行器（`64dea819`）、全部历史 runs、CORE-19 零覆盖（回归 52+1 通过证明未动）。

### 9. 引用寻址（专项审计） — **PASS（审计完成）/ 决策 BLOCKED（待操作者）**
- 定性完成：丢失点=载荷键节点名；**内容正确仅标签错位**（quote 8/8 逐字命中映射源）；映射 E1→D1… 唯一无歧义。
- A1 辅助口径反事实：evidence 旧 0.4783 / V3 0.5217（官方仍 0）。
- **BLOCKED 决策点**：是否采纳 A1 并列辅助口径（建议：是）；是否另行授权 H1 提示词修订（属任务修改，建议本批不做）。

### 10. 回归与 Mock — **PASS**
- A1 执行器套件：**52 passed, 1 skipped**（证明冻结件未动）。
- V2 候选：**10/10**（路由 3、S5′ 5 场景、对称性 1、矩阵 1）。
- 192 Mock（`runs_v2_mock`）：**192/192 COMPLETE**、1,427 calls、¥2.358712 核算、六臂各 32、S5′ 默认全 `no_trigger`（触发路径由单测覆盖）；`settlement_pending` 清零；legacy race 字段为空（语义已替换）。

---

## 汇总

| 项 | 判定 |
|---|---|
| 矩阵/六臂 32 | PASS |
| 模型池与 π 空间（对称） | PASS（证据驱动收窄） |
| 截止期 300s 冻结 | PASS |
| 12M/¥40/2,688 | PASS |
| R1 + 首批 24 stop-gate | PASS（数据侧 BLOCKED 属预期） |
| exact permutation 统计 | PASS（功效待真实回代） |
| GLM 额度容量 | **BLOCKED**（首批 24 实测） |
| Stage2b 保全 | PASS |
| 引用寻址 | 审计 PASS / **决策 BLOCKED（A1 采纳？H1 是否授权？）** |
| 回归+192 Mock | PASS |

## 结论

**全部硬性软件准入条件 PASS。** 剩余两项 BLOCKED 均为**只能由真实执行或操作者决策解除**的事项：

1. **GLM 额度容量**——解除方式：首批 24 次真实执行（≈120 次 GLM 调用）作为压力验证，异常即停；
2. **引用寻址口径决策**——待操作者一句话：是否采纳 A1 为并列辅助口径（建议采纳）、H1 本批不启用（建议）。

**据此提交真实 192-run 的独立授权申请**：授权后序列为——1 次受控预检（沿用 A1 预检命令，验证当前 key/端点健康）→ 首批 24（`--real --limit 24`）→ R1 stop-gate + 截断/额度监控 → 通过后续跑剩余 168 → `build-analysis-input`（三口径：官方旧 / 官方 V3 / A1 辅助 evidence）→ 精确置换分析 + Pareto。

**本轮未启动任何真实实验；未创建 `runs_final`；未设置 GO 门环境变量。**
