# Stage-C-R1 冻结一致性核对报告（最终授权前唯一交付）

**日期**: 2026-10-30
**性质**: 零模型调用。依据操作员裁决："22/22 工程门禁原则通过，但真实调用暂不授权……本轮仅执行零模型调用的冻结一致性核对，不新增开发工作。"
**结论**: 一致性核对 **9/9 PASS**（`stage_c_r1_runs/STAGE_C_R1_CONSISTENCY.json`）。冲突根源已定位为**两代并行冻结产物**；当前生产代（22/22）与被取代代（13/13）的每一处字段差异均有操作员裁决出处。**未发送任何模型请求，HOLD 维持。**

---

## 0. 必须先报告的工作区事件

核对开始时发现 `stage_c_r1_runs/` 目录被**另一个并行会话清空**（09:45），且我此前按操作员指令删除的演示引擎 `stage_c_r1_engine.py` 被该会话以 ".pyc 重建" 名义重新写回（09:32，文件头自注 RECONSTRUCTED）。处置：
- 生产代码完整性经 SHA256 校验无损：runner `eaffda4e…`、决策器 `cd68ec44…`、冻结脚本 `5348d7ff…` 与最终冻结记录完全一致；
- 冻结产物与验收日志由确定性脚本**零调用完整再生**（22/22 与 8/8 复现，实质等价——输入未变）；
- 演示引擎文件**未再删除**（避免破坏并行会话工作），在代际designation中标记为 SUPERSEDED。
- 另修复我方一处自身缺陷：`stage_c_r1_auth_recommendation.json` 的 `tasks` 字段此前为非法 JSON 表达式，已改为合法字符串。

## 1. 两代冻结的字段级差异与授权出处

旧代 = `STAGE_C_R1_FINAL_CHECK.json`（13/13，演示引擎世代）；新代 = `stage_c_r1_runs/STAGE_C_R1_FINAL_FREEZE.json`（22/22，生产世代）。

| 字段 | 旧代（13/13） | 新代（22/22，授权版） | 变更出处 |
|---|---|---|---|
| 执行引擎 | 演示 `stage_c_r1_engine.py`（.pyc 重建） | 生产 `stage_c_r1.py` + `six_arm_scheduler.py`（真实 Meter 同缝） | 您的 Stage-C-R1 GO 指令："必须直接检查并修改服务器实际项目代码，不得使用独立演示程序替代生产执行器" |
| 事件 | SC-E1..E4 | SC-E1、SC-E3 | 您本轮第二节："SC-E1、SC-E3 × … × 两次重复"；"我支持从原来的72-run缩减为48-run" |
| 异常 | transport、evidence_fail | S1 transport 瞬断（left=1）+ S2 contract 持续 | 您本轮第二节对两机制的命名；evidence_fail 的降级完成语义已在无效 144-run 批次中表征，未纳入本矩阵 |
| 重复 | 每组合 1 次 | 2 次 | 同上裁决："两次重复" |
| Z 范围 | NOT_TESTED | **TESTED_UNDER_S2_CONTRACT**（SPLIT_VERIFY） | 您本轮第四节第 4 条的修正指令 |
| 模型别名 | "flash"（Meter 非法） | glm53flash | Meter 合同（DD-V7.4 缺陷1） |
| 分模型配额 | glm53 400/420K、flash 200/180K | glm53 160/266K、flash 30/50K | 本轮按共享前缀扫描（144 次/227K）重核 |

**判定**：新代定义的每一处变化都可追溯到您的明确裁决；旧代 13/13 是演示引擎世代的并行产物，其矩阵（4×2×6×1）从未获操作员授权，且模型别名非法、引擎已按您的指令废弃。**以新代为准，旧代标记 SUPERSEDED（保留磁盘，不改历史）。**

## 2. 最终 48-run 清单（逐条）

完整 48 条（含指纹）在 `STAGE_C_R1_CONSISTENCY.json` 的 `manifest` 字段。结构化摘要：

- **每条 run 字段**：run_id / event_id / anomaly_type / arm / repeat_id / Z-R-π 候选权限 / 是否执行 SPLIT_VERIFY / 完整运行指纹（status、z、n_calls、tokens、makespan、deadline_met）。
- **Z/R/π 权限**（冻结自决策器代码）：Static（Z=KEEP、R=无恢复、π=冻结π₀）；Simple-Dynamic（KEEP、单故障节点、仅升级该节点）；R-only（KEEP、合法族argmax、π₀）；π-only（KEEP、单节点、贪心重优）；Joint(R,π)（KEEP、族argmax、三模式π）；**Joint(Z,R,π)（合法Z仅SPLIT_VERIFY且需contract失效+双异类健康父；MERGE/ADJUST_DEP/SUBSTITUTE_EV 在现有DAG全部非法）**。
- **SPLIT_VERIFY 实际执行**：恰好 4/48——S2 × Joint(Z,R,π) × {SC-E1, SC-E3} × {r1, r2}。
- **指纹分布**：S1 五自适应臂 COMPLETE / Static INCOMPLETE_NO_RECOVERY；S2 仅 JointZ COMPLETE，其余 INCOMPLETE_RECOVERY_EXHAUSTED。

## 3. Z 研究范围修正（按您的第 4/5 条）

- 本批次 Z 状态修正为：**TESTED_UNDER_S2_CONTRACT**。机制：持续合同违约下，宽域 verification 节点经 SPLIT_VERIFY 分裂为双血统窄域核验（合法性=合同类型+双异类健康父；同类双亲负例已测）。
- **Z 增量分析主集 = SC-E3 的 S2 cell**（按您的指定）；SC-E1 的 S2 SPLIT 同样通过合法性谓词（e1_fin reasoning + e1_tl timeline 双异类父），但仅作**机制复现**，不计入 Z 增量结论。
- 若您最终选择回退 R×π 版本：保持 Z=NOT_TESTED 的路径是**删除 S2 场景**（矩阵变为 2×1×6×2=24 runs）或禁止 JointZ 的 SPLIT 权限——二者均需您明示；当前配置保留 S2（您的倾向性意见：保留更接近核心研究目标）。
- 实验定位（按您的措辞重申）：本批次验证**两类受控异常下的动态调度及有限的 Z、R、π 联合机制**，不是三维联合优化优于所有强基线的一般性证明。受控注入 ≠ 真实供应商故障率。

## 4. 共享前缀的测量口径（双口径，不混用）

| 口径 | 定义 | 本轮数值 |
|---|---|---|
| 共享前缀 | 每 cell 一次真实执行（π₀ 无恢复直至故障触发） | 26.0s / cell；44 次调用 / 78.1K Token |
| **恢复后缀 Makespan** | 各臂从 fork 点起的实际执行（独立实测） | 均值 20.9–22.6s（Static=0） |
| **重构端到端 Makespan** | 前缀时钟 + 后缀（前缀只执行一次，六臂复用缓存） | 均值 50.9–52.6s |

**口径声明**：重构端到端不是六次独立完整运行的实测墙钟——它是配对设计的重构总量。真实实验报告中两个口径并列呈现，公式冻结于 CONSISTENCY JSON `accounting.formula`。

## 5. 预算核对

分解与冻结总量**精确对账**：前缀 44 + 后缀 100 = **144 次调用**；78,101 + 149,144 = **227,245 Token**（估算口径：实测 0.6295 字符/输入Token + 按 kind 输出上限）。硬顶 550 次 / 600K / ¥0 不变；分模型配额 glm53 ≤160 次/266K、glm53flash ≤30 次/50K。失败与重试全部计费；受控注入不推断真实故障率。

## 6. 唯一七字段授权配置（内部一致，待授权）

```json
{"batch_name": "stage_c_r1_v1", "max_calls": 550, "max_tokens": 600000,
 "max_cash": 0, "allowed_models": ["glm53", "glm53flash"],
 "tasks": "SC-E1,SC-E3 x S1_transport(left=1) x S2_contract(persistent) x 6 arms x 2 reps = 48 runs",
 "issued_by": "PENDING",
 "per_model_quota": {"glm53": {"calls": 160, "tokens": 266000},
                     "glm53flash": {"calls": 30, "tokens": 50000}},
 "z_scope": "TESTED_UNDER_S2_CONTRACT (SPLIT_VERIFY; SC-E3 primary, SC-E1 replication only)",
 "experiment_scope": "受控双异常下的动态调度与有限 Z、R、π 联合机制验证",
 "superseded": "STAGE_C_R1_FINAL_CHECK.json (13/13, demo-engine generation)"}
```

**全部完成，停止。保持 HOLD，不开新轮次，等待您的执行授权决定。**
