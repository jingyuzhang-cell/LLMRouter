# 在线调度闭环：代码覆盖审计（2026-10-08，零调用）

按用户管线阶段逐项核对仓库实际组件。结论先行：**闭环五段中，"执行 + 故障检测 + 局部恢复 + 逐调用计时/记账"已实测接通（fault30 执行器）；"Outer 调度"与"Inner 在线搜索"只有离线/零调用原型，从未在真实任务上联动；"未见任务池"与"端到端 wall-clock"缺失。** 系统闭环层次 1（可运行）尚不能在线成立，层次 2/3 未验证。

## 逐段接线矩阵

| 管线阶段 | 已具备（实测） | 原型（未接入真实流程） | 缺失 |
|---|---|---|---|
| ① Outer Scheduler（Single/Collab/Reuse 决策） | — | frozen200_selective_gate.py：**零调用门控**，读取 FROZEN200_RESULTS.json 的 f30 臂标签训练——依赖已退役的 fault 数字，且非在线；budget_conditioned_routing：预算条件路由（历史面板） | 执行前基于任务特征+预算+历史的在线决策器；Reuse 分支实证（未入 Cube，须标"未启用"） |
| ② Inner SA-PGFS（选合法 G） | 配置合法性/枚举与评分口径（fault30_protocol.CONFIGS + cube 评分） | sa_pgfs_v1 离线搜索 + 仿真（space/sim_search）；B1 消融的状态特征 GP | 在线"预测→选 G→执行→吸收观测"循环；对新任务不得查真实 Q，探索调用须计费——未实现 |
| ③ 真实执行 DAG | **fault30_run v2 执行器**：逐节点模型调用、批式阶段调度、GPU 门禁、append-only REQUESTS/RESPONSES 台账 | — | 并发执行（当前串行）；真实端到端 wall-clock（现为逐调用 latency_s 之和/关键路径合成，非实测并发耗时） |
| ④ 反馈检测与调度更新 | **检测规则已实测**：e 空 facts / r 不可解析 / v 失配（ungated，fault30 五步审计通过）；**局部恢复已实测**：memory-rule 重路由 + 后代闭包 + 升级（LOCAL_REROUTE 真实调用） | — | "检测→改未执行节点/换图"的**跨层**动态调度（当前恢复固定于 Z 规则内，不改 Y/X）；Outer 层在线策略切换无代码 |
| ⑤ 日志与评价 | 逐调用 usage/latency/injected 标记、逐任务 ok/used/lat/keys、检查点、sha 冻结 | — | 调度器自身开销（Outer/Inner 决策耗时与 token）未计量；统一新任务评分脚本（可复用 cube 评分器） |

## 关键判定

1. **不能复用为在线证据的**：selective_gate（读退役标签、零调用）、sa_pgfs_v1 全部仿真/离线搜索、cube replay（冻结表 lookup）。
2. **可直接复用的**：fault30 执行器（③④的骨干）、配置合法性与评分器、缓存/门禁/台账基建、故障注入器（配对种子）。
3. **必须新建的**：Outer 决策函数（输入=任务特征/预算/历史，输出=Single/Collab，禁读 gold 与注入标签）；Inner 在线循环（预测选 G + 探索计费）；未见任务池（frozen200 已全程参与开发；池来源 pool 的排除规则显示尚有未用任务可抽，需新冻结 held-out 集）；端到端 wall-clock 计时器；Full-vs-no-Feedback 消融开关。
4. **Reuse 分支**：未入 Reference Cube、无在线验证——正式论文在线实验标"未启用"。

## 最小试运行方案（阶段 2 草案，未冻结）

- 任务：从 pool 按冻结规则抽 **8 个未见任务**（排除 main120+frozen200 used_uids，sha 排序冻结），clean + fault30（1 个固定种子）两状态。
- 四策略 + 消融：Always-Single / Static-Collab(固定 DYN__HET__NONE) / Feedback-Rule(=DYN__HET__LOCAL_REROUTE 规则) / Full(Outer+Inner，含 no-Feedback 对照)。
- 计量：任务成功率 Q、总 token C、**真实端到端 wall-clock L**（进程计时，含调度开销）、检测/恢复/无效干预计数、调度器自身开销；任务级配对记录。
- 红线：调度器输入禁 gold/注入标签；探索调用全额计费；缓存/并发/重试规则先冻结。

## 层次判定（当前）

- 层次 1 闭环可运行：**未达成**（①②未接线；先做阶段 1 零调用联调）
- 层次 2 反馈有效：静态恢复规则的价值已有 cube 证据；**在线跨层反馈未验证**
- 层次 3 系统级优化：未验证；若 Full 全选 Single，按用户口径作如实负面结果处理
