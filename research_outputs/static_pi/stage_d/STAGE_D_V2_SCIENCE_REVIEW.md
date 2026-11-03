# Stage D V2.0 科学设计审查报告（零调用）

**日期**：2026-11-02　**性质**：只读审查 + 独立版本代码准备；**零模型调用、零费用**
**审查对象**：`PHASE_P_CLOSEOUT.md`、`PHASE_P_AUDIT_AND_PHASE_PI_READINESS.md`、
`STAGE_D_FINAL_PREREGISTRATION_V2_0_DRAFT.md`、`STAGE_D_V2_PROFILING_PILOT_DESIGN.md`、
`stage_d_executor.py`（冻结 `b0d7a589`）、`exact_perm_dp.py`、冻结清单与历史账本。

---

## 0. 最终判定：**BLOCKED（识别缺陷）**

> **当前实验设计不能识别 Joint 相对 R-only 与 π-only 的独立增量收益。**

不是因为预算、不是因为传输层（已解决），而是因为**臂的定义不构成可识别设计**：
`Proposed-Dynamic`（被当作 Joint）实际是**按异常信号选单一动作的分派器**，
且 `R` 根本不是决策变量。详见 §1。

必须补充的最小对照见 §3；在臂重定义之前启动 Pilot 只会得到不可解释的差值。

---

## 1. 核心识别缺陷（证据在代码里）

### 1.1 `Proposed-Dynamic` 不是联合决策

`d2_executor.py` 的 `Exec.policy`（冻结版）：

```python
elif arm == "Proposed-Dynamic":
    fam = next(iter(sig.values()))
    if fam == "structure":      acts = [("structure_repair", node)] if node in REPAIR_LIB else []
    elif fam == "format":       acts = [("format_repair", "FMT")]
    elif fam == "model_suspect":acts = [("swap", node)] if ds_ok else [("retry", node)]
    elif fam == "caliber_suspect": acts = [("structure_repair", node)] if node in REPAIR_LIB else []
```

它**每次只产生一个动作**，由异常类别查表决定。这不是 `a=(Z,R,π)` 的联合决策，
而是"异常类型 → 单一补救"的分派。**把它称为 Joint 是命名错误。**

### 1.2 `Z` 在大多数节点上不可用

```python
REPAIR_LIB = ['J1']      # 实测：只有 J1
```

于是在 `structure` / `caliber_suspect` 信号下，非 J1 节点得到 `acts = []` ——
**检测到异常但什么都不做**。
而 `R-only` 的对应分支是：

```python
acts = [("structure_repair", node)] if node in REPAIR_LIB else [("rerun_asis", node)]
```

→ 非 J1 节点会 **rerun**。
**结果：在 E1/E2 的 structure 异常上，Joint 比 R-only 做得更少。**
Joint−R-only 的负值可能完全来自这个覆盖差异，而不是"联合决策更差"。

### 1.3 `R` 不是决策变量

`apply_action` 中，任何 rerun 类动作都会：

```python
self.versions[node] += 1
self.state[node] = "Ready"
def inval(n):
    for d in self.spec[n]["downs"]:
        if self.state.get(d) in ("Completed","Ready"): self.state[d] = "Ready"
        inval(d)
inval(node)
```

即**固定闭包重执行**（失败节点 + 全部后代）。没有任何臂可以"选择重执行哪些节点"。
研究主线里 `R` 的定义（"根据依赖与缓存合法性选择重执行节点集合"）**在当前执行器中不存在**。

### 1.4 `π` 只换失败节点，不换"剩余节点"

```python
if kind == "swap": st["model"] = "deepseek"
```

只改当前节点。研究主线里 `π` 是"为**剩余节点**重新分配模型"——同样未被实现。

### 1.5 结论：三个估计量都不可识别

| 目标估计量 | 当前可测的对比 | 混淆来源 |
|---|---|---|
| **H1** `Joint − R-only`（π 的独立增量） | Proposed − R-only | ① 非 J1 structure 信号下 Z 覆盖不同（空动作 vs rerun）② 只在 model_suspect 上才引入 π ③ format 分支只存在于 Proposed |
| **H2** `Joint − π-only`（R 的独立增量） | Proposed − π-only | π-only 恒换模；Proposed 视信号换模或修复，Z 覆盖也不同 |
| **H3** 综合收益 | 各臂 vs Static | 与 H1/H2 同样受 D1.2 覆盖差异污染 |

**因此：任何"Joint 更好/更差"的结论都不可归因。**

---

## 2. Static-DS 对照的充分性

**结论：必要但不充分。**

| 能回答 | 不能回答 |
|---|---|
| 统一配置 GLM vs DS 在 Q/C/L/按期率上的差异（配置主效应） | Joint 相对 R-only、π-only 的**独立增量** |
| 截止期约束下哪种配置更容易按期（Phase P 提示 DS 快 2–8×） | 动态策略本身的收益 |
| 为"配置 × 策略"交互提供第二水平 | 任何关于 R 或 Z 的问题 |

**必须同时保留 Static-DS**：否则无法把"Joint 的收益"与"整体换配置的收益"分开——
这正是 Phase P 之后最需要排除的解释。

---

## 3. Phase Pi 最小充分实验矩阵

### 3.1 可识别的设计：2×2 因子（Z × π），R 固定

既然 `R` 在当前机制里恒为闭包，把它当因子会让"Joint"与两个对照共享同一个 R——
**这正是识别所需**：R 固定后，Joint−R-only 就只差 π。

| 臂 | Z（结构修复） | π（换模） | R（闭包重执行） | 作用 |
|---|---|---|---|---|
| **Static-GLM** | — | — | — | 统一配置基线（质量优先） |
| **Static-DS** | — | — | — | 统一配置基线（时延优先） |
| **Retry-only** | ✗ | ✗ | ✓（故障节点） | **控制"只要重跑就有收益"** |
| **Z-only** | ✓ | ✗ | ✓ | H1 的对照（= 研究主线里的 R-only） |
| **π-only** | ✗ | ✓ | ✓ | H2 的对照 |
| **Joint（Z+π）** | ✓ | ✓ | ✓ | 处理臂 |

组合动作已被 `Fixed-Composite` 证明可行（`structure_repair + format_repair + swap` 同节点）。

### 3.2 估计量（预注册口径）

设配对单元为 (状态, 重复)，S3/S4 各 3 重复 → 每对比较 6 个配对差。

```
Δ_π    = Joint − Z-only        # π 的独立增量（H1）
Δ_Z    = Joint − π-only        # Z 的独立增量（H2）
Δ_retry= Retry-only − Static   # "重跑"本身的价值
交互   = (Joint − Z-only) − (π-only − Retry-only)   # Z×π 交互
配置   = Static-DS − Static-GLM
```

**H1 成立 ⇔ Δ_π > 0 且在 6 个配对中 ≥5 个为正**（精确符号翻转，p=1/64 最小可达 0.0156，
5/6 时 p=7/64≈0.109；**6 重复不足以做确认性检验**——Pilot 只估效应与方差，见 §6）。

### 3.3 若操作员坚持 R 作为决策变量

则需 2×2×2 = 8 臂 + 2 个静态基线 = 10 臂，**并需实现 R 的层级**
（如"仅故障节点""故障节点+直接下游""完全闭包"）。
这是**新的机制实现**，不属于 Pilot 范围；建议在确认性实验前单独立项。

**本报告建议：Pilot 用 §3.1 的 6 臂**，理由：它可识别 H1/H2，规模最小（6×2×3=36），
且不需要新机制。

---

## 4. V2.0 传输层：已实现并离线测试通过

新增独立文件（**未修改** `transport.py` 或任何冻结文件）：

- `stage_d_v2_transport.py`：GLM `thinking: enabled + low`；DeepSeek `thinking: disabled`
  （仅当 prompt 含 "json" 时附 `response_format`，避免 DeepSeek 400）；
  每笔记账含 `thinking_mode`、`reasoning_effort`（补 Phase P 的 D-P4 缺口）；
  `accounting_yuan` 用历史同口径 `in×0.8e-6 + out×2.8e-6`。
- `test_stage_d_v2_transport.py`：**4/4 PASS**

| 测试 | 结果 |
|---|---|
| 请求体形状（GLM 有 effort 无 response_format；DS 反之） | PASS |
| 账本必含 thinking_mode / reasoning_effort / accounting_yuan | PASS |
| 成本算术（1M in=¥0.8，1M out=¥2.8） | PASS |
| 调用上限硬停 | PASS |

**仍待验证（需真实调用，故本轮不做）**：GLM `low` 的实际输出合同、
DS 在 4 类节点提示词下的合同一致性、竞速败者后台结算。

### 4.1 S5 竞速语义（冻结执行器已修复，V2.0 沿用）

`b0d7a589` 已实现：胜者立即 `_after_j2` 继续 SINK；败者交给 `_settle_loser` 后台线程结算，
迟到成本/槽占用全额入账；`finish` 阶段 join。**V2.0 只替换 transport，不动该逻辑。**

---

## 5. Pilot 预算（36 或 42 执行）

**基础数据**（实测，非拍脑袋）：
- Phase P 有效调用 33 次：token **P50=2,578 / P90=4,818 / P95=4,875 / max=5,087**
- 每执行基线 7 个模型节点（E1–E4, J1, J2, SINK；FMT 确定性不计）
- 每执行调用上限 14（含重试），历史真实 S4 R-only 实测 14 调用 / 36,008 token

| 项 | 36 执行（6 臂） | 42 执行（7 臂） |
|---|---|---|
| 调用数 | 252 – 504 | 294 – 588 |
| Token（下界：7×P50） | **0.65M** | 0.76M |
| Token（上界：14×P95） | **2.46M** | 2.87M |
| 占 GLM 包（余 ~49.6M） | ≤5% | ≤6% |
| DeepSeek 现金（若 20% 调用换模，~1.8 元/M） | ≈¥0.6–0.9 | ≈¥0.7–1.0 |

**明确声明**：以上为**估算区间**。P50/P90/P95 需 Pilot 自身测量；
不得把单次 S4 的 36K 当作全部执行的确定成本。

---

## 6. 功效与多重比较

- **Pilot 不做确认性推断**：每对比较仅 6 个配对，精确符号翻转的最小可达 p=1/64；
  5/6 一致时 p≈0.109。**Pilot 只估计效应量、方差、零差比例与可靠性。**
- **确认性实验**沿用 S3+S4 各 8 重复 = **16 对**，`exact_perm_dp.py` 精确计算（非 Monte Carlo）。
  多重比较：H1、H2 为两个主检验 → Holm 校正（阈 0.025 / 0.05）；H3 为描述性综合，不入主检验。
- **必须报告的**：Q（TP/23）、核算成本、Makespan、按期率、最差任务、失败恢复率、
  配对差与 CI、零差比例。**不得只报综合效用分。**

---

## 7. 最终回答与准入判定

**当前实验设计能否识别 Joint 相对 R-only 与 π-only 的独立增量收益？**

> **不能。** 最小补充对照（按优先级）：
> 1. **把 Proposed-Dynamic 重定义为 Z+π 组合动作**（而非单动作分派）；
> 2. **新增 Retry-only 臂**作为"重跑本身"的控制；
> 3. **在非 J1 节点补齐 Z 的覆盖**（当前 `REPAIR_LIB=['J1']` 导致 Joint 在多数 structure 异常上不作为）；
> 4. 保留 **Static-DS** 以分离配置效应；
> 5. 若 `R` 必须作为决策变量 → 需 2×2×2 设计与 R 层级实现，**建议另立项**。

### 准入判定

| 项 | 状态 |
|---|---|
| 传输层 V2.0 | **READY**（离线 4/4 PASS，独立版本） |
| S5 竞速语义 | **READY**（冻结版已修复，沿用） |
| 预算可估 | **READY**（0.65–2.46M token，GLM 包 ≤5%） |
| 科学识别 | **BLOCKED**（§1 的臂定义缺陷） |
| 冻结矩阵 | **未改**（V1.3.2 原样；V2.0 待重定义臂后另立） |
| 真实调用 | **0** |

**综合：HOLD/BLOCKED** —— 传输与预算是就绪的，但**臂必须在启动前重定义为 §3.1 的 2×2 因子**。
在臂重定义完成、且操作员批准前，不启动 Pilot。
