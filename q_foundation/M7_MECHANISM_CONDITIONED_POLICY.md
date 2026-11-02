# M7-2: 机制条件化联合决策层（Mechanism-Conditioned Joint Decision Layer）

**日期**: 2026-10-31 | **状态**: 零调用设计 + 可执行离线引擎 | **身份声明**: M6-5 的 V1.1 规则为 PRELIMINARY 候选，进入本层后仍保持 PRELIMINARY；离线回放表现不等于生产验证。

**目标（操作员定调）**：不是证明 SPLIT_VERIFY 优于 RETRY，而是——面对复杂任务，系统依据任务结构、模型能力、执行反馈与资源约束，动态决定多个异构大模型如何分工、协作、调整与停止，在质量、成本、时延间取得更优整体执行方案。本层是承载该目标的调度大脑；故障处理规则只是它的输入之一。

---

## 第一部分 M7-2A：状态与异常机制表示

### A.1 引擎状态空间（完全可序列化、不可变）

```
EngineState = (
  task_id, dag_version,
  nodes: {node_id → NodeState},
  edges: {(parent, child), ...},
  budget_remaining: tokens,
  deadline_remaining_s: float,
  resource_slots: {model → (total, in_use)},
  fault_register: [FaultRecord],          # 按时序追加，不可改写
  persistence_table,                      # M6-5 Phase A 学得（只读输入）
  profile_q,                              # M1 能力画像（只读输入）
  history: executed attempts ledger       # 事实账本（只读输入）
)

NodeState = (node_id, kind, parents, model, status, attempts,
             last_failure_type, last_failure_layer, quality_signal)
```

设计约束：
- **不可变（frozen）**：状态是值对象，决策是纯函数 `decide(state) → JointDecision`，同一状态必然同一决策（验收 #1）。
- **事实与推断分离**：`fault_register` 记录观测事实（failure_type、attempt、model、usage）；层别与持久性是**每次决策时从事实推断的视图**，不回写事实。
- **只读依赖**：持久性表、能力画像、历史账本均为外部只读输入，引擎不得修改（冻结资产保护）。

### A.2 异常机制识别（二维分类 + 置信度）

沿用 M6-2 Schema 的双维分类，加**证据置信度**：

| 观测签名 | 推断层别 (fault_layer) | 持久性判定 | 语料依据 | 置信度 |
|---|---|---|---|---|
| contract @ 节点有≥2个异类kind双亲 | merge_interface | persistent | H1/R9B：16 次同类故障，同配置重试恢复 0 次 | HIGH（n=16） |
| contract @ 其他节点 | node_logic | persistent | R6：4 次，同配置恢复 1/4 | LOW（n=4，含反例 n4） |
| parse | node_logic | transient | R9B+DYNPI：10 次，同配置恢复 8/10 | MED（n=10） |
| transport | runtime/transport | transient | R6+DYNPI：29 次，恢复 22/29 | HIGH（n=29） |
| **无签名 / 未见过的签名** | **unknown** | **unknown** | — | **不强制分类（验收 #5）** |

关键规则：
1. **持久性是概率不是标签**：同配置恢复率点估计 + 样本量同时进入决策（如 contract@非合并节点：恢复率 0.25，n=4 —— 不允许按 0 处理，也不允许按 transient 处理）。
2. **R6 反例的永久地位**：contract 第 2 次同配置重试成功过（n4，91-token 节点）。任何"persistent → 立即放弃"的规则被禁止；必须走 R_1′ 阶梯（先允许恰好一次同配置重试）。
3. **attempt 证据更新**：每次同配置重试失败，该节点持久性后验上移；换模型或拆分后的恢复**不**作为持久性反证（M6-5 Phase A 语义）。
4. **未知签名 → 未知状态**：进入保守通道（见 C.6），禁止套用 persistent 规则、禁止触发 Z/π。

---

## 第二部分 M7-2B：联合动作空间

### B.1 维度动作

| 维度 | 动作 | 合法性条件（全部满足才可入候选） |
|---|---|---|
| Z | `IDENTITY` | 恒合法 |
| Z | `SPLIT_VERIFY` | ① 故障层别=merge_interface ② 双亲 kind 异构 ③ 存在合法拆分映射（每血统一棵子验证器）④ 拆分子节点合同相互独立（各消费单血统输入）⑤ 故障不在上游节点逻辑层（M3 边界：逻辑级故障会被拆分继承）⑥ 拆分保持无环 ⑦ ΔĈ_Z 估计可得 |
| R | `RETRY_SAME` | 节点未 done（验收 #3）；次数≤机制上限；预算与时延余量覆盖保留成本 |
| R | `EARLY_EXIT` | 恒合法；放弃节点必须留痕（failed-final + 原因） |
| π | `KEEP` | 恒合法（正确不作为） |
| π | `SWITCH_STRONG` | ① 原模型弱（能力差距≥阈值 0.15）② 签名为系统性（contract/parse）③ 目标节点未执行 ④ 换模后预算/时延可行 |
| π | `SWITCH_CHEAP` | **无正收益证据——不进入候选**（只记录于规则表为未验证） |

### B.2 联合动作与组合约束

最终动作是三元组 **a_t = (Z_t, R_t, π_t)**，不是三个独立引擎的叠加：

| 状态（操作员表） | 候选联合动作 | 依据 |
|---|---|---|
| 瞬态故障、能力充足 | (IDENTITY, RETRY_SAME, KEEP) | R6/DYNPI 22/29 恢复 |
| 合并合同故障、异类双亲 | (SPLIT_VERIFY, RETRY_ON_CHILDREN, KEEP/π̂) | H1 G5、R9B B：6/6 恢复 |
| 能力不足、无结构异常 | (IDENTITY, RETRY_LADDER, SWITCH_STRONG) | DYNPI T1-r2（n=1, LOW） |
| 合并故障 + 能力不足 | (SPLIT_VERIFY, RETRY_ON_CHILDREN, SWITCH_STRONG) | 组合合法但**无独立证据**——预测不得按可加处理 |
| 故障不明确 | (IDENTITY, ONE_CONSERVATIVE_RETRY, KEEP) 或 STOP | 未知不强制分类 |

组合约束（合法性剪枝）：
- **Z 改变 R 的作用对象**：SPLIT 后 R 只作用于拆分子节点，原节点不再重试（H1 G5 语义）。
- **Z 先于 π 评估**：拆分创建的新节点无故障历史、无能力记录缺口，π 的评估基于子节点新 kind/新输入。
- **联合≠单项之和**（核心）：Z 的恢复概率以联合形式计量（拆分+子节点执行的整体），不分解为 ΔU(Z)+ΔU(R)。Z×π 交互项记 `NO_EVIDENCE`，预测中显式置零并标注，不得隐式假设。

---

## 第三部分 M7-2C：收益预测与 Pareto 决策

### C.1 预测量（每候选联合动作四元组 + 分项记录）

```
预测 = ( ΔQ̂ , ΔR̂[恢复概率], ΔĈ[增量token], ΔL̂[增量makespan] )
记录 = { 分项: {Z: Δ̂_Z, R: Δ̂_R, π: Δ̂_π}, 交互: {Z×R: joint_modeled, Z×π: NO_EVIDENCE→0, R×π: NO_EVIDENCE→0} }
```

验收 #7：单项与交互**分别记录**，交互项缺证据时显式标 NO_EVIDENCE，禁止可加性假设。

### C.2 校准值（全部来自既有语料，附样本量与证据级）

| 预测参数 | 点估计 | 来源 | n | 证据级 |
|---|---|---|---|---|
| P(COMPLETE \| SPLIT on merge-persistent) | 1.00 | H1 G5/G6 + R9B B×4 | 6 | A（PRELIMINARY，LOW_N） |
| P(恢复 \| 同配置重试, persistent, 已1败) | 0.03 | H1/R9B 16 次 0 恢复 + R6 n4 1 恢复 | 17 | A |
| P(恢复 \| 同配置重试, transient, 已1败) | 0.76 | R6+DYNPI 22/29 | 29 | A |
| 拆分新增结构成本 | ≈2,800 tok | H1 G5 实测（chk_a+chk_b 边际） | 2 | A（LOW_N） |
| 持久故障无效重试成本 | ≈2,200 tok/次 | H1 chk 平均失败尝试 | 12 | A |
| 换模 ΔQ̂ | gap × 0.76 | DYNPI T1-r2（0.167/0.22） | **1** | A（**LOW，未复现**） |
| 换模 ΔĈ / ΔL̂ | −300 tok / −2.0 s 每节点 | Stage-B 先验（glm53 1100 vs flash 1400） | 画像 | B |

**ΔC_Z 成本判断**（解释 H1 与 R9B 符号相反）：
```
ΔĈ_Z = C(新增拆分节点) − C(避免的无效执行)
      ≈ 2,800 − k × 2,200   （k = 无 Z 路径预计浪费的同配置重试次数）
H1 型（无 Z 臂会重试到耗尽, k≈3）：ΔĈ_Z ≈ −3,800（净节省）
R9B 型（无 Z 臂快速退出, k≈0）：ΔĈ_Z ≈ +2,800（恢复的净价格）
```
k 由无 Z 路径的重试策略与持久性表联合预测——**成本符号是条件属性**（M7-1 事实 3）。

### C.3 约束与 Pareto 筛选（M7-2C 核心）

```
过滤：合法性 ∩ 预算(保留成本 ≤ budget_remaining) ∩ 时延 ∩ 资源槽
选择：按机制(regime)条件化——
  dominance 机制    → 唯一占优候选，直接选定
  priced_recovery  → 恢复价格 vs B：预算覆盖即选恢复，否则保守（价格=3.4K~6.9K 实测区间）
  quality_tradeoff → 约束式 max ΔQ̂ s.t. 可行；并列时取更廉
  Pareto 不可比    → 返回前沿集合 + 机制标签，**不强行制造唯一最优**（验收 #8）；
                     仅在操作员偏好 (B, D) 显式给定时报"该偏好下的推荐"
  unknown 故障     → 保守通道（C.6）
```

词典序为默认（可行性 → ΔQ̂ → ΔĈ → ΔL̂），权重式仅作对照不部署——M7-1 事实 4：权重不稳定恰出现在权衡 cell。

### C.6 保守通道（未知故障）

无签名/未见签名 → 层别 unknown：允许**恰好一次**同配置重试（不扩大故障），禁止 Z、禁止 π；重试再败且仍无法分类 → 停止该节点并留痕（`stopped_unclassified`）。INCOMPLETE 的 ΔQ̂ = null（验收 #6，绝不赋 0）。

---

## 第四部分 M7-2D/E：引擎与验收（详见另两份交付物）

- 引擎：[m7_decision_engine.py](m7_decision_engine.py)——纯函数、不可变状态、全量决策留痕（预测/合法性/机制/前沿）。
- 验收：[M7_OFFLINE_ACCEPTANCE_TESTS.md](M7_OFFLINE_ACCEPTANCE_TESTS.md)——操作员九条验收全部转为可执行断言 + 历史回放对照。

## 第五部分 边界与不做什么

1. V1.1/R_1′/PI_2′ 均为 PRELIMINARY 候选；离线验收通过 ≠ 生产验证；升级需前瞻批次（MVR_V1 级，HOLD 不变）。
2. 不修改冻结 Schema、六臂算法、历史实验记录（全部只读）。
3. SWITCH_CHEAP、ALT_EVIDENCE_PATH、ADD_VERIFY_NODE：无证据，不进入候选动作。
4. 本层不预设"Z 好还是 R 好"——它输出的是条件、预测与机制，决定权在约束与证据。
