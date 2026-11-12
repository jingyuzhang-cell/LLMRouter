# DAMJS V0.2.1：四项修正（零调用 · 2026-11-05）

> V0.2 保留并存。本文只修正操作员指出的四项，不改变实验协议。

## 修正 1：智能体身份与模型解耦

### V0.2 的错误

`a = (role, model, capability_profile)` 使模型成为智能体的身份成分——一旦 `π` 换模型，智能体身份就变了，与"π 是智能体内切换"矛盾。

### V0.2.1 定义

```
智能体：
  a = (role, state, memory, policy, capability, resources)
      role       ∈ {extractor, timer, reasoner, verifier, reporter, formatter}
      state      ∈ {idle, busy, blocked, degraded}
      memory     已产出节点的上下文（供迁移交接）
      policy     该智能体的内部执行策略（含当前模型选择）
      capability {node_kind → (Q̂, Ĉ, L̂, n, CI)}   # 历史校准，与模型无关
      resources  {capacity, calls_left, yuan_left}

智能体内当前模型：
  m_a(t) ∈ M_a ⊆ M        # 可变；换模型不改变 a 的身份

动作四维：
  Z   修改 DAG 结构
  R   节点重执行（同一智能体）
  Π   智能体内部换模型：m_a(t) → m_a(t+1)
  X'  节点跨智能体迁移：x_{i,a} = 1 → x_{i,a'} = 1
```

### X' 的可执行约束（V0.2 缺失）

```
M1 角色兼容：role(a') 必须覆盖 kind(node_i)
      兼容表（预注册）：
        extracts/timeline → {extractor, timer}
        reasoning        → {reasoner}
        verification     → {verifier}
        report           → {reporter}
        FMT              → {formatter}
      不兼容 → X' 不可选

M2 容量：workload(a') < capacity(a')

M3 交接成本（必须计入 Ĉ 与 L̂）：
      Ĉ_handoff(a→a') = 上下文摘要生成 1 次调用（≈¥0.003）
      L̂_handoff(a→a') = 依赖该节点已完成父节点输出的重新注入
                        ≈ Σ wall(父节点) 的重新读取（无调用，但串行等待）
      若节点有 k 个已完成父节点：L̂_handoff ≈ k × 0.5s（本地注入）

M4 迁移不破坏 DAG：迁移后仍须满足全部父节点已完成；父输出通过 memory 交接
```

### 诚实声明（不变）

**Stage D 的 192 次执行中不存在智能体层**（单一 executor + 固定模型池），因此：

- `X'` 的收益 **H-f 完全无数据**
- **54 次 Pilot 不承担验证 H-f 的任务**（操作员已确认拆分）
- 要让 X' 有真实操作空间，实验必须**先配置多个兼容角色的智能体实例**

## 修正 2：区分终端质量、质量增益、当前质量

### V0.2 的错误

`Q̂(format+Z)=+5.29` 是**历史 TP 增益**，却与 `Q̂ − σ ≥ Q_min = 12`（终端 TP）直接比较——口径混淆。

### V0.2.1 三量分离

```
当前质量（金盲估计）：
  Q̂_current(s_t) = 已完成节点中，SINK 尚未执行时，
                    Q̂_current 由证据覆盖率估计：
                    Q̂_current = 已验证可交付事实槽位数（金盲：verify 放行数去重）

动作增益（历史统计）：
  ΔQ̂(s_t, a) = (μ_a, σ_a, n_a, CI_a)   来自 (family, action_type) 历史

预测终端质量：
  Q̂_final(s_t, a) = Q̂_current(s_t) + ΔQ̂(s_t, a)

质量门禁（保守）：
  Q̂_final − σ_ΔQ ≥ Q_min                 Q_min = 12
```

**关键：`Q̂_current` 必须金盲**——只能用 verify 放行数/覆盖度估计，不得读取 Gold。

### 实际 bootstrap CI（10000 次重采样，种子 20261105）

| family | action | n | mean ΔTP | sd | CI95 | RELIABLE |
|---|---|---|---|---|---|---|
| **format** | **Z_format** | **9** | **+5.67** | 0.50 | **[+5.33, +6.00]** | **✓** |
| **structure** | **Z_structure** | **7** | **+1.29** | 0.95 | **[+0.71, +2.00]** | **✓** |
| **none** | **NONE** | **17** | **+0.18** | 0.73 | [−0.18, +0.53] | **✓** |
| structure | Z_full | 7 | **−1.86** | 5.81 | [−6.14, +1.71] | ✗（均值负！） |
| structure | Z_format | 4 | +6.00 | 6.93 | [0.00, +12.00] | ✗ |
| format | Z_full | 3 | +2.33 | 6.35 | [−5.00, +6.00] | ✗ |
| format,structure | Z_full | 2 | −6.00 | 2.83 | [−8.00, −4.00] | ✗ |
| model_suspect | 任意 | ≤2 | — | — | — | ✗ |

**门禁：RELIABLE ⟺ n ≥ 5 ∧ CI 宽度 ≤ 3.0 TP。**

**本轮只有 3 个估计通过门禁**（V0.2 提前标记 format/structure 为 RELIABLE 属过早，现已按实算 CI 修正）。

### 新的关键发现

`structure + Z_structure` = **+1.29**（可靠）vs `structure + Z_full` = **−1.86**（n=7 但均值负）——**同样是 Z 类动作，全动作组合在结构故障上反而有害**。这是"动作范围"而非"动作类型"的证据，强化了 C3 中"避免不必要动作"的必要性。

## 修正 3：Q/C/L 三轴统一保守门禁

```
质量：  Q̂_final − σ_ΔQ        ≥ Q_min = 12
成本：  Ĉ(a) + σ_C(a)          ≤ B_rem
时延：  L̂(a) + σ_L(a) + T_reserve ≤ D_rem        T_reserve = 15s

其中 Ĉ(a) = 动作调用成本（含 M3 交接）+ σ 来自同 (family,action) 历史
     L̂(a) = Σ 受影响节点 wall（用 per-node p95）+ σ + 交接时延
```

**三轴风险控制逻辑一致（全部用上界）。**

## 修正 4：Pareto 候选的完整执行语义

每个候选动作必须定义完整执行计划（可复现、可审计）：

| 动作 | 执行计划（冻结语义） |
|---|---|
| `NONE` | 不做任何调用；节点保持现状 |
| `Z{format_repair}` | 重置 FMT 状态 → 重跑 FMT（1 次调用） |
| `Z{structure_repair(n)}` | 替换 node 的 system spec → 重跑该 node（1 次） |
| `R{n}` | 重跑该 node（同 model，1 次） |
| `Π{a→m'}` | 换 a 的模型 → 重跑 a 当前持有的异常节点（1 次） |
| `X'{n→a'}` | 生成上下文摘要（1 次）→ a' 重跑该 node（1 次）= **2 次调用** |
| 联合 | 按 Z→Π→R 顺序串行；累计调用数计入 |

**每个候选的 `(调用数, 影响节点集, 预计 L̂)` 必须可由计划直接算出**——保证 Pareto 输入可审计。

## 五、不变项

- 实验协议主体（三臂 × 三档 × 两场景 × 3 重复 = 54）不变
- 预算（400 调用 / 1.4M tokens / ¥2.5）不变
- 四层看门狗（`W_eff = min(W_node, D_rem − T_reserve)`）不变
- 效用函数权重（1.0 / 0.3 / 0.5）不变
- **H-f（X' 收益）不由本轮 Pilot 验证**

## 六、下一步（零调用工程）

1. `damsj_engine.py`：调度器核心（状态/A 层/看门狗/Q/C/L 门禁/Pareto/效用）
2. `damsj_executor.py`：包装冻结的 `stage_d_executor.py`（不修改原件），加 L3/L4
3. `test_damsj_engine.py`：七条不变式零调用测试
4. 验收后重新申请 54 次实验授权

**本轮零调用。**
