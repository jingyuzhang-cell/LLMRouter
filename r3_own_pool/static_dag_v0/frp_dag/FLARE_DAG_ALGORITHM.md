# FLARE-DAG 算法正式定义

**FLARE-DAG**: Feedback-aware Local Adaptive Re-optimization for Heterogeneous DAG Execution

## 1 问题定义

给定有向无环图 $G = (V, E)$，模型池 $\mathcal{M} = \{m_1, \dots, m_k\}$，预算 $B_C, B_L$。

**决策变量**：调度方案 $\pi = \{(m_i, a_i)\}_{i=1}^{|V|}$，其中 $m_i \in \mathcal{M}$ 为节点 $v_i$ 分配的模型，$a_i \in \{\text{execute}, \text{retry}, \text{switch}, \text{verify}, \text{terminate}\}$ 为动作。

**目标函数**（三目标）：

$$
\max_{\pi} \; Q(\pi \mid f_t), \qquad \min_{\pi} \; C(\pi), \qquad \min_{\pi} \; L(\pi)
$$

其中：

**质量目标**（含条件能力与接口风险）：
$$
Q(\pi \mid f_t) = \prod_{i \in V} \hat q_i^{(t)}(m_i \mid z_i, f_t) \cdot \exp\!\left(-\lambda \sum_{(i,j) \in E} r_{ij}(m_i, m_j)\right)
$$

- $\hat q_i^{(t)}(m \mid z_i, f_t)$：节点 $v_i$ 使用模型 $m$ 在当前上游输入 $z_i$ 和反馈 $f_t$ 条件下的成功概率。
- $r_{ij}(m_i, m_j)$：上游模型 $m_i$ 输出进入下游模型 $m_j$ 后产生接口损失的风险（条件能力 ≠ 传播能力的量化）。

**成本目标**：$C(\pi) = \sum_{i \in V} C_i(m_i, a_i)$（tokens 或货币成本）。

**时延目标**（DAG 关键路径）：
$$
L(\pi) = \max_{p \in \mathcal{P}(G)} \sum_{i \in p} L_i(m_i)
$$
其中 $\mathcal{P}(G)$ 为 $G$ 中所有源到汇路径。对并行分支取 max 而非求和。

**约束**：$C(\pi) \le B_C$，$L(\pi) \le B_L$，DAG 前序约束。

## 2 算法结构（四组件）

```
Feedback f_t
    ↓
① Conditional Capability Update
   q̂_i(m) → q̂_i(m | z_i, f_t)
    ↓
② Affected Descendant Extraction
   G → G_t⁺ = {v_t} ∪ Desc(v_t)
    ↓
③ Residual Budget Update
   B_C → B_C^rem = B_C − C_t^used
   B_L → B_L^rem = B_L − L_t^used
    ↓
④ Selective Local Pareto Re-optimization
   (trigger: E[ΔU] > overhead + τ)
   → 新局部 Pareto 集 P_t^local
```

## 3 Algorithm 1（伪代码）

```
Algorithm 1: FLARE-DAG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Input:  DAG G=(V,E), model pool M, budgets B_C, B_L,
        initial estimates q̂_i(m), C_i(m), L_i(m),
        interface risk r_ij(m_i, m_j)
Output: final execution plan π*, execution trace

━━━━━━━━━━━━━ Phase 1: Initial Pareto Scheduling ━━━━━━━━━━━━━

1:  P_0 ← ∅                                       // Pareto front
2:  beam ← {(0, 0, 0, ∅)}                         // (logQ, C, L, partial π)
3:  for each v_i in topological_order(G) do
4:      new_beam ← ∅
5:      for each (logQ, C, L, π) in beam do
6:          for each m ∈ M do
7:              q' ← logQ + log q̂_i(m)
8:              c' ← C + C_i(m)
9:              l' ← update_critical_path(L, v_i, L_i(m))
10:             π' ← π ∪ {(v_i, m)}
11:             new_beam ← new_beam ∪ {(q', c', l', π')}
12:     beam ← ε-dominance_filter(new_beam, ε, K)  // cap at K
13: P_0 ← beam
14: π_0 ← argmax_{π ∈ P_0} Q(π) s.t. C(π)≤B_C, L(π)≤B_L

━━━━━━━━━━━━━ Phase 2: Execution + Feedback Loop ━━━━━━━━━━━━━

15: C_used ← 0;  L_used ← 0;  π* ← π_0
16: for each v_t in topological_order(G) do
17:     m_t ← π*[v_t]
18:     execute v_t with model m_t
19:     observe feedback f_t (deployable signals only)
20:     C_used ← C_used + C_{v_t}(m_t)
21:     L_used ← update(L_used, v_t, L_{v_t}(m_t))
22:
23:     if v_t succeeded then
24:         continue                               // no re-optimization
25:     end if
26:
27:     ─── Component ①: Conditional Capability Update ───
28:     for each m ∈ M do
29:         q̂_{v_t}(m) ← g(q̂_{v_t}(m), f_t)
30:         // g: e.g., q̂ × 0.3 on parse_failure, q̂ × 1.5 on success
31:     end for
32:     // propagate to descendants' conditional estimates
33:     for each v_j ∈ Desc(v_t) do
34:         z_j ← observed upstream state
35:         for each m ∈ M do
36:             q̂_{v_j}(m) ← q̂_{v_j}(m | z_j, f_t)
37:         end for
38:     end for
39:
40:     ─── Component ②: Affected Descendant Extraction ───
41:     G_t⁺ ← {v_t} ∪ Desc(v_t)
42:     // sibling branches already succeeded are FROZEN
43:
44:     ─── Component ③: Residual Budget Update ───
45:     B_C^rem ← B_C − C_used
46:     B_L^rem ← B_L − L_used
47:
48:     ─── Component ④: Selective Local Pareto Re-optimization ───
49:     // Trigger: only re-optimize if expected gain justifies overhead
50:     E[ΔU] ← estimate_utilility_gain(q̂ updated, π*, G_t⁺)
51:     if E[ΔU] > overhead + τ then
52:         P_t^local ← Pareto_beam_search(
53:             subgraph = G_t⁺,
54:             estimates = q̂ updated,
55:             budget = (B_C^rem, B_L^rem),
55:             frozen_nodes = V \ G_t⁺
56:         )
57:         if P_t^local ≠ ∅ then
58:             π* ← merge(π*[V \ G_t⁺], argmax Q from P_t^local)
59:         else
60:             terminate                          // no feasible plan
61:         end if
62:     else
63:         continue with current π*               // skip re-optimization
64:     end if
65: end for

━━━━━━━━━━━━━ Output ━━━━━━━━━━━━━

66: return π*, execution trace, Pareto front evolution {P_0, P_{t_1}, P_{t_2}, ...}
```

## 4 与已有方法的差异

| 方法 | 它做什么 | FLARE-DAG 的差异 |
|---|---|---|
| MixLLM (NAACL 2025) | query→LLM 的 Q/C/L bandit 路由 | 不处理 DAG 内阶段依赖与后继传播 |
| DeMAC (EMNLP 2025) | Dynamic DAG + Manager-Player 反馈 | 非异构 LLM 节点级 Q/C/L Pareto 调度，无剩余预算 |
| LLM-as-Scheduler (ACL 2026) | 工作流级动态选择 | 非节点级分配，无后继局部重优化 |
| 经典 DAG MO-sched (NSGA-II etc.) | cost–makespan Pareto for cloud workflows | 不涉及 LLM 条件能力 q(m\|z,f)、接口风险 r_ij、运行反馈语义 |

**FLARE-DAG 的独特贡献不在于"Pareto 优化 DAG"本身，而在于：**

1. **条件能力更新**（$q \to q(m \mid z, f)$）：LLM 的能力不是固定的，取决于上游输入和运行反馈。
2. **后继局部性**（$G_t^+ = \{v_t\} \cup \text{Desc}(v_t)$）：失败后不重优化整图，只调整受影响区域。
3. **剩余预算约束**（$B^{rem} = B - \text{used}$）：重优化在真实剩余资源下进行。
4. **选择性触发**（$\mathbb{E}[\Delta U] > \text{overhead} + \tau$）：不是每次失败都重优化，只在值得时启动。

## 5 关键主张（论文中要证明的）

$$
HV_{\text{FLARE}} \approx HV_{\text{Global-Pareto}} > HV_{\text{Weighted-Sum}}
$$

但：

$$
T_{\text{opt}}^{\text{FLARE}} \ll T_{\text{opt}}^{\text{Global}}, \qquad
N_{\text{rescheduled}}^{\text{FLARE}} \ll N_{\text{rescheduled}}^{\text{Global}}
$$

即：FLARE-DAG 的局部重优化在 Hypervolume 上接近全局重优化，但在线重优化开销和重调度节点数远小于全局方法。
