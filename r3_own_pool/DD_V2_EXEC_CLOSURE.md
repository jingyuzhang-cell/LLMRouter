# DD-V2 三缺口修复 + 真实执行闭环（b6c7966 裁决交付）

零调用、零 GPU；DD-V1 未动；P3-60 未动。测试 13/13 + 五臂假传输闭环。

## 修 1：eff_score 真正参与选优（DONE）

`v2_score_and_pick` 重写尾部：**硬门 = DAG 合法性（M3 枚举结构保证）+ 物理预算**（dcost ≤ b_remain，不可放宽）；其余候选按 **风险调整 eff_score** 统一竞争——静态 SS 回退与 NONE/LOCAL/FULL/FULL_DYNAMIC 同池比较，不再自动胜出。选中动态方案时记录 `selected_over_fallback_margin`（对 SS 回退的分数优势）；SS 胜出时 `fallback=True`。模式：`joint_selection`（硬可行胜）/ `joint_selection_soft`（软约束胜出且优于回退）/ `static_fallback` / `degraded`（仅物理预算硬门触发）。

## 修 2：质量估计（DONE）

- **r 节点证据补齐**：`load_quality_evidence()` 新增 r 的可求值率（对自身 episode 的 e1/e2 上下文求值）——r|medium n=23 q̂=0.74[.58,.90]、r|large n=37 q̂=0.81[.69,.92]。
- **parse 率 ≠ 终端正确率（显式声明）**：`node_quality` 返回 `kind` 字段标记 proxy；e2|large 诚实报低（q̂=0.33[.07,.59]——真实 parse 率 0.25 的 Wilson 中点）。
- **恢复质量估计器**：`recovery_quality(failed_node, action_family)` 从独立开发轨迹（非 P3-60）按 (动作族, 失败节点) 统计**终端 v2.1 结果**；无证据 → [0,1] 宽区间 + `supported=False`。
- 区间（q_lo/q_hi/unsupported）随每决策行持久化。

## 修 3：V2 接入真实执行器（DONE）

`decide_arm_v2`：与 `arm_entry.decide_arm` 同返回契约——**已通过微试的 run_cell/execute 链路无需任何修改即可驱动 V2 臂**（引擎/预算/故障注入/共享快照/状态反馈/终端评分/双时间口径全部复用）。DD-V1 的 `arm_entry`/`policy` 字节未动。

## 五臂假传输闭环（结果）

| 臂 | 决策模式 | 逻辑调用 | 物理 | 服务启停 |
|---|---|---|---|---|
| SS | static_recipe ×3 | 24 | 21 | 10 |
| DD-V1 | policy ×3 | 9 | 9 | 1 |
| DD-Cal | joint_selection_soft ×3 | 15 | 12 | 2 |
| DD-Cal+FB | joint_selection_soft ×3 | 15 | 12 | 2 |
| DD-V2 | joint_selection_soft ×3 | 15 | 12 | 2 |

五臂全部通过假传输完整执行（模式区分、调用差异、服务停止）。

## 五项验收条件

| # | 条件 | 结果 |
|---|---|---|
| 1 | 至少一个合法开发场景由联合收益选中**动态恢复** | **PASS**：r-故障场景 `joint_selection` 选中 LOCAL(π(r)=**large**, v=coder)——非回退、非 NONE；`Acc1_dynamic_wins` |
| 2 | 不同 π/Z 转化为不同物理动作 | **PASS**：选中 π(r)=large 后实际执行 r|**large**（非计划 medium）；`Acc2_actions_differ` |
| 3 | 物理预算 + DAG 合法性 | **PASS**：硬门=dcost≤b_remain；合法性由 M3 枚举结构性保证；`Acc3` |
| 4 | 静态回退/NONE/EARLY_STOP 按设计触发 | **PASS**：e2-故障场景诚实选 NONE（joint_selection_soft，e2|large 证据 q̂=0.33 → 接受失败优于盲目重试）；`Acc4` |
| 5 | Q/C/T/R 独立复算 + 失败即停 | **PASS**（结构）：每行携带全部复算字段（q/q_lo/q_hi/p_on/mu_own/dcost/score/eff_score/execute）；入口失败链经 T12 验证；`Acc5` |

## 真消融梯（机制真实，非标签）

| 梯级 | 先知 | 耦合 | 可行 | 模式 | 选中 |
|---|---|---|---|---|---|
| A V1 | stub | V1 争用 | **21** | joint(V1) | LOCAL(r=large,v=**large**) |
| B V1 | FIT 实测 | V1 争用 | **0** | **degraded** | — |
| C V2 | stub | 解耦 | 2 | joint_selection | LOCAL(r=large,v=coder) |
| D V2 | FIT 实测 | 解耦 | 2 | joint_selection | LOCAL(r=large,v=coder) |

**梯级 B 揭示新事实**：即便换实测时延先知，**V1 的争用基线本身**（每共同任务 v 均值 + 完整切换许可 ≈ 62s）仍杀死一切——解耦（C/D）才是可行性的决定性修复；stub 先知（A）是微试假象的来源（假 q(e2)=0.99 让 21 个通过）。

## 开发数据支持情况

- 时延：可靠性 FIT 10 格（n=24–36/格，独立于 P3-60）✓
- 节点 parse 率：Formal 轨迹去重（e n=8、r n=23–37、v n=64–65）✓（n=8 的 e 格区间宽，已如实携带）
- 恢复终端质量：**开发轨迹证据尚未构建**（`recovery_quality` 目前对全条件返回宽区间）——留待小规模真实开发实验积累

## GO/NO-GO 准入表（小规模真实开发微试）

| 项 | 状态 |
|---|---|
| eff_score 驱动联合选择（含 SS 回退同池竞争） | **GO** |
| r 节点质量证据 + 诚实的 parse-vs-terminal 声明 | **GO** |
| V2 真实执行入口（复用已验证链路，DD-V1 未动） | **GO** |
| 动态方案被真实选中并转化为不同物理动作 | **GO**（r-故障开发场景） |
| 五臂假传输闭环 | **GO** |
| 恢复终端质量的开发证据 | **部分**（宽区间占位，需真实开发数据） |

**建议：GO for 3–5 任务真实开发微试**（≤100 请求/50K tokens/3,600s），目的=在真实模型上验证：联合选择在真实信念下选中动态方案、动作差异物理发生、恢复质量证据开始积累。60 任务确认性实验不在本次申请内。
