# DAMJS：Deadline-Aware Multi-Agent Joint Scheduler 设计（零调用 · 2026-11-05）

## 〇、三项统计勘误与先行更正

| # | 项 | 更正 |
|---|---|---|
| 1 | 负收益占比 | −16 占四个负值绝对值之和 16/(16+3+1+1) = **76.2%**（此前 84% 错误） |
| 2 | S5\|r7 | **单一案例，不能称"已证明采样方差"，也不能称 3.1% 为不可消除下限**——只能称"未解释的残余负差（n=1）" |
| 3 | 配对检验口径 | 按**实际 300s deadline** 重算（此前 180s 为假想阈值） |

### 按真实 300s 口径的配对联合成功率

| 臂 | 联合成功 | 95% Wilson CI |
|---|---|---|
| Proposed | **30/32 = 93.8%** | (79.9%, 98.3%) |
| Static | 18/32 = 56.2% | (39.3%, 71.8%) |

**配对：Proposed 更好 12 对、Static 更好 0 对、双方均达标 18 对、双方均失败 2 对。单侧精确符号检验 p = 0.00024（双侧 0.00049）。**

## 一、阻断性问题解决（三项）

### Q1：1088s 与 300s 的矛盾——**deadline 不是硬超时，是评分阈值**

**取证**（`Proposed-Dynamic__S2__r1.json`）：
- `deadline_s=300`，`makespan_s=1088`，`status=INCOMPLETE_DEADLINE`
- 执行器决策记录：`t_rem = 138 → −213 → −346 → −778` —— **明知超出仍继续派发节点**
- 源码逻辑：`if t_rem < 60 and arm != "Static": acts = []` —— 超期后**只停止恢复动作，不中止执行**
- 该案例：E1 162s、**E2 351.4s（单节点异常慢，正常 p50=2.9s）**、E3 133s，随后 J1/J2/SINK/FMT 全部 Failed

**全量核验**：7/192 执行超出 300s（356/353/1088/673/300/306/796s）；5/192 存在 `t_rem<0` 后继续执行的决策。

**结论**：`deadline_s` 当前是**分类标记**而非强制约束。**这是 DAMJS 的阻断性缺陷**——真正的 deadline-aware 调度器必须把 deadline 作为可执行的终止条件。

### Q2：R3 的作用域——**必须是（节点 × 动作类型）级，且证据弱于此前表述**

**关键反证**（此前"轮次≥2→崩溃"是臂混杂）：

| 臂·节点 | 重复次数 | n | TP 均值 | TP 分布 |
|---|---|---|---|---|
| π-only·J1 | **3** | 8 | **12.75** | 12,12,13×6 —— **重复 swap 无害** |
| Simple·J1 | 2–3 | 9 | 11.11 | 4,8,10,12,13×4,14 |
| Fixed·J1 | 2–4 | 12 | 9.83 | 0,3,3,6,7,13,14×4,16（**双峰**） |
| R-only·FMT | 3 | 8 | 8.00 | 全 8（**重复无效动作**） |
| π-only·FMT | 3 | 8 | 8.50 | 8×7,12 |

**真实规律**：
- **重复"无效动作"有害**（FMT 上重复 retry/swap → TP 恒 8，因为格式故障只能靠 format_repair）
- **重复"有效动作"基本无害**（π-only 的 J1 swap ×3 → TP 12.75）
- Fixed 内部 2+ 轮双峰（0–16，n=4）提示存在阈值效应，但**样本太小不足以定规则**

**R3 修正为**：限制 **同一节点 × 同一动作类型** 的重复次数 ≤1；**不同节点的独立异常各自允许一次恢复**（23/192 案例存在 ≥2 个不同故障节点，分别恢复是合理的）。

### Q3：看门狗阈值——用节点级分布标定

| 节点 | n | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| E1 | 193 | 2.7 | 3.4 | 3.6 | **162.0** | 766.5 |
| E2 | 205 | 2.9 | 3.2 | 3.4 | 10.3 | 351.4 |
| E3 | 192 | 2.8 | 3.3 | 4.4 | **133.1** | 655.5 |
| E4 | 192 | 2.1 | 2.5 | 2.7 | 19.1 | 148.1 |
| **J1** | 263 | **52.0** | 94.9 | 102.6 | 114.5 | 116.4 |
| J2 | 200 | 5.5 | 6.1 | 7.0 | 30.6 | 85.9 |
| SINK | 187 | 6.5 | 7.1 | 7.3 | 29.2 | 165.6 |

**J1 是长尾主因**（GLM 思考模型，p50 已 52s）；E 类正常 <5s 但 p99 可飙至 162s（网络/重试）。

**看门狗策略（数据驱动）**：
- **单节点硬上限**：`W_node = max(3 × p95(node), 120s)` → E 类 120s、J1 **308s**、J2 120s、SINK 120s
- **进度心跳**：单节点超过 `2 × p95` 记录警告；超过 `W_node` 中止该调用，按执行失败处理
- **全局**：`elapsed > deadline` → 立即中止全部派发，进入降级输出（**这是当前缺失的**）

## 二、DAMJS 形式化定义

### 2.1 状态空间

```
s_t = (G_t, F_t, H_t, B_t, D_t, M_t, P_t)

G_t  当前 DAG 与节点状态：{node → (Ready/Running/Completed/Failed), edges, critical_path}
F_t  金盲异常信号：{node → (family ∈ {none, structure, format, model_suspect, caliber}, observed_at)}
H_t  干预历史：{(node, action_type) → count}，全局 {rounds, swaps, elapsed}
B_t  剩余预算：(calls_left, yuan_left, tokens_left)
D_t  剩余时间：deadline − elapsed；以及剩余关键路径估计 L̂_remaining
M_t  能力画像：{model × node_kind → (q̂, ĉ, l̂)}（来自历史或校准）
P_t  进度：{node → last_heartbeat, expected_wall}
```

### 2.2 联合动作空间

```
A(s_t) = {(Z_t, R_t, π_t)} ∪ {NONE}

Z_t ⊆ {structure_repair(n), format_repair, split_node(n), merge_nodes(n), rerun_degraded(n)}
R_t ⊆ Nodes(G_t)   # 需重执行的节点集合
π_t : Nodes(G_t) → Models   # 模型重分配（可空）
```

### 2.3 约束

```
C1 预算：C(a) + B_spent ≤ B_max
C2 截止期：elapsed + L̂(a) ≤ deadline        ← 当前执行器缺失
C3 重复：(n, action_type) 已在 H_t 中出现 → 该动作不可选
C4 风险：π 切换次数 ≤1（全局）；含 swap 的联合动作需 q̂ 增益 > θ_π
C5 质量下限：Q̂(a) ≥ Q_min
```

### 2.4 目标

```
maximize  (Q̂(a), −Ĉ(a), −L̂(a))   subject to C1–C5
先过滤不可行，再取 Pareto 非支配集；若空集 → NONE
```

## 三、决策算法（五阶段）

```
━━ Stage 0  看门狗（新增，当前缺失）━━
if elapsed > deadline: 中止派发 → 降级输出(UNKNOWN) → 记录 INCOMPLETE_DEADLINE
if now − heartbeat(n) > W_node(kind(n)): 中止该调用 → 标记 exec failure → 进入 Stage 1

━━ Stage 1  异常识别与是否干预 ━━
F_t = classify(node_output, node_meta)   # 金盲：D1 模型可疑 / D2 结构 / D3 格式 / none
if F_t == none and 无失败: return NONE
if D_remaining < L̂_remaining: return NONE        # 截止期不可行
if 该 (node,family) 已恢复过: return NONE         # C3

━━ Stage 2  联合动作生成 ━━
候选 = []
if family == format:        候选 += [Z{format_repair}]
if family == structure:     候选 += [Z{structure_repair(n)}, R{n}]
if family == model_suspect: 候选 += [R{n}]         # π 谨慎，需 q̂ 证据
if 节点能力画像显示替代模型显著更优: 候选 += [π{n→m}]
候选 += [NONE]

━━ Stage 3  Q/C/L 可行性过滤 + Pareto ━━
for a in 候选:
    Q̂,Ĉ,L̂ = predict(a, s_t)
    if 违反 C1–C5: 丢弃
Pareto = 非支配子集
return argmax_{a∈Pareto} score(Q̂, Ĉ, L̂; λ)   # λ 由部署方给定，或返回 Pareto 集

━━ Stage 4  执行与更新 ━━
执行 a → 更新 G_t, H_t, B_t, M_t → 下一轮
```

### 预测模型（Ĉ/L̂/Q̂ 的估计，当前可用的只有历史统计）

| 项 | 估计方法 | 数据可用性 |
|---|---|---|
| `Q̂(a)` | 按 (family, action) 历史 TP 增益查表：format+Z→+4.1~+5.3；structure+Z→+2.1；其他→≈0 | **有（本报告）** |
| `Ĉ(a)` | 动作调用数 × 单次均价（¥0.0234/执行，单节点 ~¥0.003） | 有 |
| `L̂(a)` | Σ 受影响节点的历史 wall（J1≈52s、E≈3s、SINK≈7s）+ 恢复开销 | 有（节点画像） |
| `L̂_remaining` | 未执行节点的 critical path 求和，用 per-node p50/p90 | 有 |

**诚实声明**：Q̂ 的查表值是**组内均值**，不是逐案例预测；S5|r7 显示同动作下 TP 可差 1（原因未明，n=1）。

## 四、机制假设（可检验命题）

| 编号 | 假设 | 预测 | 当前证据 |
|---|---|---|---|
| **H-a** | 干预收益取决于"动作类型是否匹配故障家族" | format→Z 增益 >0；format→R/π 增益 =0 | **强支持**（S4：R/π TP 恒 8，Z 达 12.4-13.4） |
| **H-b** | 干预代价随时延放大，存在截止期交叉点 | 紧张截止期 Static 更优；宽松时动态更优 | **部分**（300s 下 Proposed 93.8% vs 56.2%，p=0.00024；交叉点为外推） |
| **H-c** | 重复"无效动作"有害，重复"有效动作"无害 | R3 应收窄到 (node,action_type) | **支持**（π-only J1×3→12.75 vs R-only FMT×3→8.00） |
| **H-d** | 无异常时不干预优于任何干预 | none+action 增益 ≤0 | 支持（neither 组增益 ≈0，R-only −1.33） |
| **H-e** | 检测失败（无信号 + 运行超长）是最严重的负收益来源 | 单看门狗可消除 −16 型损失 | 部分（n=1 案例） |

## 五、实验协议（待授权）

### 三臂

| 臂 | 定义 |
|---|---|
| A · Static | 静态分配，无恢复 |
| B · Current-Proposed | 现有实现（sig 分类 + 单动作） |
| **C · DAMJS** | 五阶段算法（含看门狗、截止期可行性、Pareto） |

### 截止期（必须在执行器中真实强制）

**前置改造（阻断项）**：执行器需在 `elapsed > deadline` 时中止派发并输出降级结果。当前未实现。

| 档 | 目的 | 依据 |
|---|---|---|
| 110s | 紧张：验证"少干预/不干预" | Static 在 110s 下已达标 15/32 vs Proposed 11/32（外推） |
| 150s | 交叉点附近 | 外推交叉区 |
| 240s | 宽松：验证质量收益 | 接近实际 300s 但留压力 |

### 规模与统计

- 每臂每档 × 场景（S3 结构 + S4 格式）× 3 重复 = **3 臂 × 3 档 × 2 场景 × 3 = 54 执行**
- 试探性阶段（27 执行）仅作可行性检查，**不作确认性结论**
- 正式样本量：以 H-b 的效应量（Proposed 93.8% vs Static 56.2%，Δ=37.6pp）估算；若关注更小效应（如 DAMJS vs Proposed 的 5-10pp），需 100+ 配对
- 主检验：配对联合成功率精确符号检验（双侧）；次：ΔTP、负收益率、最差 ΔTP、C、L、看门狗触发率、Pareto HV

### 预算

| 项 | 值 |
|---|---|
| 执行数 | 54（试探） / 视功效扩展 |
| 每执行调用 | ~4-6（E×4 + J/SINK/FMT） + 恢复 |
| 预计调用 | **~300-350** |
| Token | **~1.0-1.2M** |
| 费用 | **~¥1.5-2.0** |
| 建议硬顶 | 400 调用 / 1.4M tokens / ¥2.5 |

## 六、不可声称的边界

1. **Q_final 仍 BLOCKED**——TP/23 是代理指标
2. **单任务体系**（*ST卓然退市事件），无跨域泛化
3. **deadline 交叉点为外推**，未在任何真实 binding 的截止期下执行过
4. **Q̂ 预测基于组内均值**，非逐案例可辨识
5. **看门狗阈值来自 192 执行的历史分布**，未包含未来分布漂移

## 七、交付

本设计 + `QCL_NEGATIVE_ATTRIBUTION.md` + `QCL_CONFOUND_AUDIT.md` + `QCL_DECISION_STATE.json`。
