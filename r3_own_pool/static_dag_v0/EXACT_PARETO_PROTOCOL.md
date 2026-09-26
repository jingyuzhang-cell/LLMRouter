# Exact Pareto Analysis on a Restricted Workflow Configuration Space — FROZEN PROTOCOL

> 分岔判定实验:18 配置在 30% 故障下是否形成非平凡稳定 Pareto 结构?
> 是 → 继续 Search 路线(实验②);否 → Selection 论文到此结束。

## 冻结决策(运行前不可改)

**空间**:固定 Y=dag, e1=large, e2=large。变量 m_r ∈ {medium, large, coder},
m_v ∈ {medium, large, coder},Z ∈ {none, local-switch}。|Π_sub| = 3 × 3 × 2 = 18。
**这是受控子空间,不是全组合空间。**

**故障**:f=30%,种子 20260923/24/25(与主实验相同)。故障绑定 (task, node,
该配置的规划模型):同一 (task, node) 对在每个配置中都故障,但注册到各配置的
规划模型上;恢复时切换到不同模型则故障不复现(与主实验一致)。

**Z=none**:执行初始 DAG,检测到失败不采取动作,直接评分。

**Z=local-switch(冻结规则,与主实验 Dynamic-Real 完全一致)**:
- e1/e2 失败(facts 空/不可解析):首次全任务失败 → coder,后续 → medium(跨任务记忆,冻结任务序)
- r 失败(表达式不可执行):→ large
- v 失败(值不可解析或与 r 值不一致):→ large
- 每节点至多一次恢复;仅重执行失败节点及其后继闭包(e→{r,v}, r→{v}, v→{})
- 无预算门控(事后统计)

**Pareto 目标**:(Q, −C, −L) 三维。可靠性(存活/恢复率)单独报告,不入 Pareto。
"Pareto search is evaluated over quality, execution cost, and latency, while
reliability is assessed separately under repeated fault injection."

**判据(运行前冻结)**:
- 情况 A(|P*| ≤ 2):停止 Search,Selection 论文定稿
- 情况 B(|P*| ≥ 3,跨种子稳定):继续实验②(搜索效率)
- 情况 C(均值前沿丰富但种子间剧变):先做 Pareto stability 分析(P_PF(π)),不直接进 NSGA-II

**指标**:每配置 Q(mean±std over seeds), C, L;前沿成员;前沿 HV(2D Q/C 与 3D);
Pareto Recall;每配置的前沿进入频率 P_PF。

**执行**:利用 (model, prompt) 温度-0 缓存复用;新提示真实调用;全部 120 题保留分母。
