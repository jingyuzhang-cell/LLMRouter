# 论文最终重组包(2026-09-24,纯写作,零新调用)

> 依据用户最终方向:"多智能体协同调度 + 多目标优化"叙事统一;Selection 不是 Search;
> Oracle Gap 用 potential 不用 achieved;DV/FR 定位为 Candidate Pool Expansion Analysis。

## 一、标题方向

**Failure-Aware Multi-Agent Workflow Scheduling with Pareto-aware Multi-objective Optimization**

## 二、三条贡献(最终版)

1. **多智能体 workflow 协同执行框架**:面向复杂任务的 failure-aware 动态执行,以部署
   可得信号触发失败节点及受影响后继的局部恢复,保留未受影响分支。
2. **Pareto-aware 多目标策略选择机制**:在质量、成本、可靠性之间按 (故障风险, 预算)
   状态从校准 Pareto 前沿选择执行策略;决策时零额外模型调用;逐状态不劣于任何固定
   策略,距状态条件 oracle 上界 0.0005。
3. **workflow 级协同调度的适用条件与优化边界**:通过多粒度路由比较、故障归因分析、
   候选池扩展(DV/FR)和逐任务互补性诊断,揭示选择价值随故障率增长但现有候选的平均
   性能无法完全覆盖该潜在收益,为自动化 workflow 搜索提供实证基础。

## 三、Oracle Gap 解释修正

❌ ~~扩展候选池证明了更好的优化潜力~~

✅ 扩展候选池增加了任务级策略互补性(3→5 策略 oracle gap 从 +13.3 升至 +16.4pp@30%
故障),但现有策略的平均性能仍无法完全覆盖该潜在收益,说明自动化 workflow 搜索
仍存在进一步优化空间。

英文(论文用):
> Expanding the candidate pool from three to five strategies increases task-level
> complementarity (per-task oracle gap rises from +13.3 to +16.4pp at 30% faults),
> while the mean performance of existing candidates does not fully capture this
> potential gain — indicating remaining headroom for automated workflow search.

## 四、DV/FR 定位与措辞修正

定位:**Candidate Pool Expansion Analysis**(验证候选空间的紧凑性),不是新方法比较。

DV:
❌ ~~Verifier fails~~
✅ The verifier-augmented workflow does not provide additional Pareto gains under
the evaluated fault model.

解释:当前 Dynamic 的模型切换已覆盖主要可恢复故障场景,verifier 检测到的额外错误
不被 large 升级修复——与 clean 下 DV=Dynamic 的负结果一致(故障侧复制)。

FR:
❌ ~~Full Replay is worse~~
✅ Full replay introduces additional execution cost without improving recovery
effectiveness compared with localized recovery.

解释:突出局部恢复的核心价值——依赖感知的范围缩小消除了不必要的重计算,而质量
不受损失。

## 五、第 3 章最终结构

### 3.X Pareto-aware Multi-Agent Workflow Scheduling

(不是 Combinatorial Optimization Algorithm——Selection(Π),不是 Search(Π))

**3.X.1 Workflow Decision Space**
π=(X,Y,Z): X = agent/model assignment; Y = workflow topology; Z = recovery policy。
信息约束:恢复决策仅用部署可得信号。

**3.X.2 Multi-objective Formulation**
max Q(π), max R(π), min C(π), min L(π)。R 以指标集合 {ρ_keep, ρ_rec} 描述,不合
成单一标量;约束 C(π)≤B、DAG 依赖顺序、部署信息约束。

**3.X.3 Pareto-aware Strategy Selection**
候选 workflow → 评价 → Pareto filtering → state-aware selection。
流程图:校准前沿维护(离线)→ 到达时查前沿 → 选择 π* → 执行 → 输出轨迹。

## 六、第 4 章最终结构

| 节 | 标题 | 回答 | 关键内容 |
|---|---|---|---|
| 4.1 | Experimental Setup | 在什么条件下比较 | 面板、基线、故障模型、指标 |
| 4.2 | Execution Strategy Space Characterization | 为什么存在协同调度问题 | 能力异质性、Query/Node Router、分解基准 |
| 4.3 | Failure-aware Collaborative Execution | 为什么需要动态执行 | |
| 4.3.1 | Robustness under Fault Conditions | | 三种子主表+图4-1 |
| 4.3.2 | Recovery Efficiency | | RD vs FR、归因消融、预算违规 |
| 4.3.3 | Failure Attribution | | 检测F1、Verifier、Recovery Attribution、Static失败机制 |
| 4.4 | Pareto-aware Multi-objective Scheduling | 为什么需要多目标选择 | |
| 4.4.1 | Pareto Frontier and Trade-off Analysis | | Pareto+HV+Budget(表4-6/4-8,图4-2) |
| 4.4.2 | Multi-objective Selection Comparison | | Random/Acc-only/Cost-only/Weighted/Ours(表R1/R2) |
| 4.4.3 | Candidate Pool Expansion Analysis | | DV/FR(POOL_ANALYSIS) |
| 4.4.4 | Strategy Transition Boundary | | 三层模拟+互补性+oracle gap+adaptive |
| 4.5 | Cross-domain Analysis | 边界 | Math500/MBPP/外部方法 |

## 七、第 5 章展望句式(递进到第二篇)

> The current work performs Pareto-aware selection over an executed candidate pool.
> Future work will investigate automated Pareto workflow search — including
> surrogate-assisted evaluation to address the expensive, partially observable
> objective landscape identified in Section 3.X.3, and LLM-driven candidate
> generation with diversity-aware population management (e.g., MEoH-style
> dominance-dissimilarity mechanisms adapted to workflow configuration distance).
