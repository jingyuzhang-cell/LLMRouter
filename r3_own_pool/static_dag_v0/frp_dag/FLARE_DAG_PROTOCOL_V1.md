# FLARE-DAG 冻结协议 v1.0

状态：FROZEN_BEFORE_ANY_NEW_CALLS。本协议在看到任何新数据之前锁定全部设计决策。

## 1 算法定义

见 `FLARE_DAG_ALGORITHM.md`（已冻结，commit ad90884 基础上修订命名）。核心链条：

$$
f_i \;\rightarrow\; \hat q(m \mid z_i, f_i) \;\rightarrow\; A(v_i)=\{v_i\}\cup\mathrm{Desc}(v_i) \;\rightarrow\; (B_C^{\mathrm{rem}}, B_L^{\mathrm{rem}}) \;\rightarrow\; \text{local Pareto re-scheduling}
$$

## 2 候选组合集（看到结果前锁定）

DAG 结构：e1(large) ∥ e2(large) → r(?) → v(?)。

e1/e2 固定为 large（能力画像显示 large 在抽取上占优 0.60 vs 0.37/0.38，Pareto 搜索不会选其他）。

**r × v 候选组合（6 个，冻结）**：

| # | r 模型 | v 模型 | 编号 | 已有覆盖 | 需补调用 |
|---|---|---|---|---|---|
| 1 | medium | coder | (M,C) | 120/120 ✅ | 0 |
| 2 | large | coder | (L,C) | 0/120 | ~120 v(coder) 以 r(large) 为输入 |
| 3 | medium | large | (M,L) | 0/120 | ~120 v(large) 以 r(medium) 为输入 |
| 4 | large | large | (L,L) | ~90/120 (消融) | ~30 |
| 5 | coder | coder | (C,C) | 0/120 | ~120 v(coder) 以 r(coder) 为输入 |
| 6 | coder | large | (C,L) | 0/120 | ~120 v(large) 以 r(coder) 为输入 |

**注**：候选集不要求全部补齐。第一阶段优先补 #2 和 #3（最小闭环），确认 Pareto 空间存在后再决定是否扩展。

**Pareto 前沿的非支配点数由数据决定，不预设目标。**

## 3 Q/C/L 估计方法（冻结）

### 3.1 静态估计（初始 Pareto 调度用）

对每个 (node, model) 对：
- $\hat q_i(m)$ = 该节点在冻结数据中的端到端链成功率（v 值接近 gold）
- $\hat C_i(m)$ = 该 (node, model) 的平均 tokens
- $\hat L_i(m)$ = 该 (node, model) 的平均服务时延

### 3.2 条件能力更新（反馈到来后）

$$
\hat q_i^{\text{new}}(m) = \begin{cases}
\hat q_i^{\text{old}}(m) \times \beta_{\text{fail}} & \text{if } f_t = \text{failure at node } i \text{ with model } m \\
\min(1, \hat q_i^{\text{old}}(m) \times \beta_{\text{succ}}) & \text{if } f_t = \text{success}
\end{cases}
$$

冻结参数：$\beta_{\text{fail}} = 0.3$，$\beta_{\text{succ}} = 1.5$。

**接口风险**（第一阶段简化）：
$$
r_{ij}(m_i, m_j) = 1 - \frac{Q(e_i \to e_j \text{ with } m_i, m_j)}{Q(e_j \text{ alone with } m_j)}
$$
如果数据不足以估计，置 $r_{ij} = 0$（退化为无接口风险）。

### 3.3 时延（DAG 关键路径）

$$
L(\pi) = \max(L_{e_1}, L_{e_2}) + L_r + L_v
$$

## 4 重优化触发条件（冻结）

$$
\text{Reoptimize} \iff \exists \pi' \in \text{candidates}: \; Q(\pi' \mid f_t) > Q(\pi^{\text{current}}) + \delta \;\text{and}\; C(\pi') \le B_C^{\text{rem}} \;\text{and}\; L(\pi') \le B_L^{\text{rem}}
$$

冻结参数：$\delta = 0.01$（最小有意义改善）。最多触发 2 次重优化。

## 5 分阶段实验设计

### Phase 1：静态 Pareto 空间验证（先做）

**问题**：当前模型池和 DAG 结构下，是否存在可利用的 Q/C/L 非支配差异？

**最小数据需求**：3 个完整链一致的组合——(M,C)、(L,C)、(M,L)——在 120 题上全部执行完毕。

**新增调用估计**：
- (L,C)：120 次 v(coder)，以 r(large) 表达式为输入
- (M,L)：120 次 v(large)，以 r(medium) 表达式为输入
- 合计 ~240 次（如控制在前 60 题，则 ~120 次）

**Phase 1 判定**：
- 如果 3 个组合全部被一个支配 → Pareto 空间不存在，FLARE-DAG 无优化空间，**停止**
- 如果存在 ≥2 个非支配方案 → 进入 Phase 2

### Phase 2：动态局部重优化（Phase 1 通过后）

**问题**：反馈驱动的后继局部 Pareto 重优化是否优于固定方案？

**基线**：
| 方法 | 说明 |
|---|---|
| Static Node Router | 固定 (M,C) + 局部回退 |
| Weighted Sum | αQ−βC−γL 网格搜索选方案 |
| Static Pareto | 初始 Pareto 最优方案，无反馈 |
| Dynamic (frozen) | 冻结的 Dynamic 臂（规则式适应） |
| FLARE-DAG | 完整算法：初始 Pareto + 条件更新 + 后继局部重优化 |

**评价指标**：
- 主指标：任务成功率 Q
- 成本：平均 tokens C
- 时延：平均关键路径 L
- 预算违规率
- Hypervolume（三目标，参考点 = 各轴最差值）
- FLARE-DAG 专有：重优化触发次数、重调度节点数、重优化搜索时间
- 配对统计：ΔQ + bootstrap 95% CI + exact McNemar

### Phase 3（如 Phase 2 通过）：held-out 面板验证

multidag_120 用于开发/机制验证。最终泛化证据需要新的 held-out 面板（不同任务来源，同 DAG 结构）。

## 6 开发/验证面板分离

| 面板 | 用途 | 状态 |
|---|---|---|
| multidag_120 | 开发/机制验证（Phase 1+2） | 已有，反复使用 |
| held-out 面板 | 最终泛化验证（Phase 3） | 未创建，需新任务集 |

**硬规则**：multidag_120 上的结果标注为 development/controlled panel evidence，不作为独立泛化证据。

## 7 文献差异化定位

| 已有方法 | 它做什么 | FLARE-DAG 差异 |
|---|---|---|
| MixLLM (NAACL 2025) | query→LLM Q/C/L bandit | 不处理 DAG 阶段依赖 |
| DeMAC (EMNLP 2025) | Dynamic DAG + Manager-Player | 非异构节点级 Pareto，无剩余预算 |
| LLM-as-Scheduler (ACL 2026) | 工作流级动态选择 | 非节点级，无后继局部重优化 |
| 经典 MO-DAG (NSGA-II etc.) | cost–makespan Pareto | 无 LLM 条件能力/接口风险/运行反馈 |

**注意**：需文献核验确认上述工作确实缺少 residual-budget 或 descendant-local 机制。

## 8 冻结声明

本协议在设计阶段锁定以下内容，看到数据后不做事后调整：
- 候选组合集（第 2 节）
- Q/C/L 估计方法与参数（第 3 节）
- 触发条件与参数（第 4 节）
- 分阶段判定规则（第 5 节）
- 基线集合（第 5 节 Phase 2）

唯二可调（在 Phase 1 结果之后、Phase 2 之前）：
- 补充候选组合数量（扩展 #5、#6）
- 接口风险 $r_{ij}$ 的具体形式（如数据不支持当前定义）
