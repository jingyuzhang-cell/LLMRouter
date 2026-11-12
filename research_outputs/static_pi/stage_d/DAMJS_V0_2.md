# DAMJS V0.2：五项修订（零调用 · 2026-11-05）

> V0.1 保留并存。本文只修订操作员指出的五个设计问题，不改变实验协议主体。

## 修订 1：显式的多智能体层（此前缺失，最重要）

### 此前的问题

V0.1 的 `π_t: Nodes → Models` 只是模型路由。**Stage D 的 192 次执行实际上也没有"智能体"层**——执行器是单一 executor + 固定模型池。因此：

**诚实声明：智能体分配层是本设计的新增结构，Stage D 数据无法验证它。必须由新实验检验。**

### V0.2 定义

```
智能体 a ∈ 𝒜，定义为一个三元组：
  a = (role, model, capability_profile)

  role ∈ {extractor, timer, reasoner, verifier, reporter, formatter}
  model ∈ {glm53, glm53flash, deepseek}          # 智能体内部的执行模型
  capability_profile = {node_kind → (q̂, ĉ, l̂, n)}   # 历史校准

智能体状态：
  A_t(a) = (status ∈ {idle, busy, blocked}, workload = #assigned_running,
            availability = 1 if API healthy, capability_profile, recent_failures)

节点—智能体分配变量：
  x_{i,a} ∈ {0,1},  Σ_a x_{i,a} = 1  ∀i        # 每个节点恰属一个智能体
  Σ_i x_{i,a} · 1[running] ≤ capacity(a)        # 容量约束

模型重分配 π 变为智能体内部策略：
  π_t: {a → model'}，仅在 a 的 role 允许的模型集合内切换
```

### 状态空间（V0.2）

```
s_t = (G_t, F_t, H_t, B_t, D_t, A_t, X_t, P_t)
                          ↑新增   ↑新增
A_t  智能体状态（见上）
X_t  当前分配矩阵 {x_{i,a}}
P_t  进度心跳 {node → (last_beat, expected_wall)}
```

### 动作空间（V0.2）

```
a_t = (Z_t, R_t, Π_t, X_t')
       结构调整  重执行集  智能体模型切换  节点重分配

X_t' 是新增维度：把节点从过载/失败的智能体迁移到能力更匹配的智能体。
```

**这使论文的调度对象从"节点→模型"升级为"节点→智能体（含角色）+ 智能体内模型"，与"多智能体协同调度"的题目对齐。**

### 与 Stage D 的衔接

Stage D 的 S1/S2 场景中 "model_suspect（J2 用 glm53flash 能力不足）" **正是智能体能力不匹配的实例**——但当时只有模型切换选项，没有智能体重分配。V0.2 的 `X_t'` 动作能在保持 role 不变的前提下把节点迁到另一智能体（可能同模型但不同角色配置）。

**注意**：没有数据能证明 `X_t'` 有效。它是待验证的假设，不是已验证规则。

## 修订 2：Q̂ 预测器必须带不确定性门禁

### V0.1 的问题

`Q̂(format+Z) = +5.29` 是组内均值，没有方差和样本量。用它做 Pareto 输入会过度自信。

### V0.2 定义

```
Q̂(a) = (μ_a, σ_a, n_a, CI_a)

其中：
  μ_a  = 该 (family, action) 历史 TP 增益均值
  σ_a  = 标准差
  n_a  = 样本数
  CI_a = 95% bootstrap CI（固定种子 10000 次）

可靠性门禁：
  RELIABLE(a) ⟺ n_a ≥ 5 ∧ CI_a 宽度 ≤ 3.0 TP
  不可靠 → 该动作不得因 Q̂ 优势被选中；仅可作为"探索"或与 NONE 并列

当前数据下的可靠性判定：
  格式+Z:      n=7  → ✓ RELIABLE（CI 需计算）
  结构+Z:      n=10 → ✓ RELIABLE（但 CI 可能宽）
  model_suspect: n=2 → ✗ UNRELIABLE（禁止建立确定性策略）
  none+任何动作: n=9 → ✓（但预期增益≈0）
```

**Stage 3 的 Pareto 输入改为 `(Q̂ ± σ, Ĉ ± σ, L̂ ± σ)`，并使用保守估计（μ − σ）做可行性过滤。**

## 修订 3：统一恢复历史与动作约束（消除逻辑冲突）

### V0.1 的冲突

Stage 1 写 `(node, family) 已恢复过 → NONE`；R3 写 `(node, action_type)` 重复限制。两者不等价。

### V0.2 统一表示

```
H_t[(node, action_type)] = {count, outcomes[], last_t}

约束（按优先级）：

C3-a  同一 (node, action_type) 且该动作类型历史增益 ≤0 → 禁止再次执行
      （理由：FMT 上重复 retry/swap 恒为 TP=8；证据 n=16）

C3-b  同一 (node, action_type) 重复次数 ≥2 且最近一次未改善 → 禁止
      （较弱约束，待实验）

C3-c  不同节点：各自独立维护历史（23/192 案例存在 ≥2 故障节点）

C3-d  同一节点的新异常（family 变化）：允许重新诊断
      （S3|r3 的 format+structure 双族是允许的）
```

### swap 约束降级

V0.1 的"全局 swap ≤1"**缺少依据**——π-only 在 J1 重复 swap 3 次仍达 TP 12.75（n=8）。

```
V0.2：swap 次数不作为硬约束，改为风险特征：
  若 plan 含 ≥2 次 swap → 标记 RISK，需在 Pareto 中显式权衡；
  仅当 HIST[(node,'swap')].mean_gain ≤ 0 时禁止（C3-a 覆盖）
```

## 修订 4：Pareto 选择的冻结效用函数

### V0.1 的问题

`argmax Score(a)` 未定义，导致 Pareto 集内选择不可复现。

### V0.2 冻结规则（三阶段，不可事后调整）

```
步骤 1  质量门禁：Q̂(a) − σ_Q(a) ≥ Q_min        # 保守估计，Q_min = 12 TP
步骤 2  资源门禁：Ĉ(a) ≤ B_rem ∧ elapsed + L̂(a) + σ_L(a) ≤ D_rem
步骤 3  效用选择（权重预注册，固定）：

  U(a) = w_Q · (Q̂(a) − Q_min) − w_C · (Ĉ(a)/B_rem) − w_L · (L̂(a)/D_rem)

  预注册权重：w_Q = 1.0, w_C = 0.3, w_L = 0.5
  （理由：质量为主目标；时延权重高于成本，因时延方差大且直接触发截止期失败；
    该权重为设计选择，非数据推导，须在论文中声明）

  若 Pareto 集非空：a* = argmax U
  若 Pareto 集为空：a* = NONE
```

**权重敏感性作为实验的次要分析**（w 的 ±50% 扰动是否改变选择）——但主结果用冻结权重。

## 修订 5：看门狗的四层分离与有效阈值

### V0.1 的问题

`W_J1 = max(3×102.6, 120) = 308s` > 最紧截止期 240s → **J1 看门狗永远不会先于全局截止期触发**。

### V0.2 四层机制（必须区分）

```
L1 心跳告警（不改行为）
   若 now − last_beat(node) > 2 × p95(kind(node)) → 记录 WARN，继续等待

L2 单节点调用超时（中止该调用）
   W_node(kind) = max(3 × p95(kind), 120s)
   触发 → 中止该调用 → 标记 exec failure → 进入 Stage 1

L3 全局截止期强制中止（阻断项，当前执行器缺失）
   W_deadline = D_remaining − T_reserve        # T_reserve = 15s（降级输出所需）
   若 elapsed ≥ deadline − T_reserve → 停止全部派发

L4 超时后降级输出
   已完成节点的结果 + 未完成槽位标 UNKNOWN → 生成合法报告
   状态 = INCOMPLETE_DEADLINE_DEGRADED（区别于当前的 INCOMPLETE_DEADLINE 无输出）

有效阈值：
   W_eff(node) = min(W_node(kind(node)), W_deadline)
   → 在 110s 截止期下，所有节点 W_eff ≤ 95s（而非 J1 的 308s）
```

**当前数据下的四层阈值表**：

| 层 | 公式 | 110s 档 | 150s 档 | 240s 档 |
|---|---|---|---|---|
| L2 E 类 | max(3×3.6, 120)=120s | min(120,95)=**95s** | 120s | 120s |
| L2 J1 | max(3×102.6,120)=308s | **95s** | min(308,135)=135s | 225s |
| L2 J2 | max(3×7.0,120)=120s | 95s | 120s | 120s |
| L2 SINK | max(3×7.3,120)=120s | 95s | 120s | 120s |
| L3 全局 | deadline−15 | **95s** | 135s | 225s |

## 五、V0.2 完整算法骨架

```
━━ L0 看门狗（四层） ━━
if elapsed ≥ deadline − T_reserve: 强制中止 → L4 降级输出
if now − last_beat(n) > 2·p95(kind(n)): WARN
if call_wall(n) > W_eff(n) = min(W_node, W_deadline): 中止调用 → exec failure

━━ L1 异常识别与是否干预 ━━
F_t = classify(output, meta)                       # 金盲
if F_t == none ∧ 无失败: return NONE
if D_remaining < L̂_remaining + T_reserve: return NONE
if C3-a/C3-b 判定禁止: return NONE

━━ L2 联合动作生成（含智能体层） ━━
候选 = []
if F_t == format:        候选 += [Z{format_repair}]
if F_t == structure:     候选 += [Z{structure_repair(n)}, R{n}, X{n→a'}]
if F_t == model_suspect: 候选 += [R{n}, X{n→a'}]        # π 因 UNRELIABLE 降级
if RELIABLE((family,π)): 候选 += [Π{a→model'}]
候选 += [NONE]

━━ L3 Q/C/L 预测与可行性 ━━
for a in 候选:
    (Q̂±σ, Ĉ±σ, L̂±σ) = predict(a, s_t)
    门禁 1: Q̂−σ_Q ≥ Q_min
    门禁 2: Ĉ ≤ B_rem ∧ elapsed + L̂+σ_L ≤ D_rem
    不可行 → 丢弃
Pareto = NonDominated(可行集)
a* = argmax U(a) if Pareto else NONE        # U 权重冻结

━━ L4 执行、更新、降级 ━━
执行 a* → 更新 G_t, H_t, A_t, X_t, B_t
若触发 L3/L4 超时 → 输出降级报告（已完成节点 + UNKNOWN 槽位）
```

## 六、论文核心问题的表述（按操作员建议）

**不写成**："提出一种基于故障类型和截止期的动态恢复算法"

**写成**：

> 在具有依赖关系的多智能体 DAG 执行过程中，如何根据执行反馈、剩余资源和截止期约束，联合优化智能体任务分配、节点恢复与执行策略，使系统在不同资源紧度下获得更好的质量—成本—时延权衡？

DAMJS 是该问题的候选解法，不是问题本身。

## 七、待验证假设（V0.2 新增）

| 编号 | 假设 | 数据现状 |
|---|---|---|
| H-f | 智能体重分配（X 动作）能修复 model_suspect 型故障 | **无数据**（Stage D 无智能体层） |
| H-g | Q̂ 的可靠性门禁（n≥5, CI宽≤3）能避免过度自信选择 | 无数据（新机制） |
| H-h | 冻结效用函数 U 的权重扰动不改变主结论 | 无数据 |
| H-i | 四层看门狗能在真实 240s 截止期下减少超期损失 | **无数据**（deadline 从未 binding） |

## 八、下一步（待授权）

1. **执行器改造**（工程阻断项）：实现 L3/L4 全局强制中止与降级输出；节点级 L2 超时
2. **零调用代码测试**：模拟时钟验证五条不变式（到期不派发、超时可中止、禁重复动作、不超预算、降级报告合法）
3. **54 次探索性实验**（另行授权）
4. **正式确认性实验**（按探索效应量重算功效）

**本轮零调用。**
