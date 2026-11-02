# DYNAMIC_PI_FINAL_EXPERIMENT_PLAN — Dynamic-π 最小真实收益实验（整包方案 v1.0，零调用）

**日期**: 2026-10-30 | **状态**: 前置条件核对完成 → **HOLD（1 项阻塞，见 §11）**
**研究问题（唯一）**: DAG 节点异常后，依据执行反馈为**未执行节点**重新分配模型（Dynamic-π），
相较保持原分配（Static-π），能否取得更好的终端 Q/C/L？R、Z 固定为共同语义，不纳入本轮贡献。

---

## 1. 合格新任务与证据身份（未曝光核查，全账本扫描）

全部 12 个冻结任务的真实调用曝光史（扫描所有 bench 台账 purpose）：
**已曝光**：T-P1, T-R1, T-R2, T-D1, T-M1, SC-E1, SC-E3；**未曝光**：T-P3, T-D2, SC-E2, SC-E4。
其中 T-P3/T-D2 的 silver **为空（0 事实）** → 唯一合格的确认集任务：

| 任务 | 事件 | 证据文档（stage_c_evidence/text/，SHA 冻结于 BENCH_FREEZE_MANIFEST） | 参考事实 |
|---|---|---|---|
| **SC-E2** | 康美药业 600518 | km_notice_2019.txt, km_penalty_2020.txt | silver 6 条（S1–S6）+ 下游 E2-DD-1 |
| **SC-E4** | 乐视网 300104 | ls_delist_2020.txt, ls_terminate_2020.txt | silver 7 条（S2–S7）+ 下游 E4-DD-1 |

两任务文档互不相交、事件独立；均未进入任何真实调用账本。**任务独立性：满足。**

## 2. 六项参考的独立裁决状态核对

**裁决走廊（本实验）**：SC-E2-S1、SC-E2-S2、SC-E2-S3、SC-E4-S2、SC-E4-S3、SC-E4-S4（六项主 slate）。
当前状态（如实）：

| 事实 | 现状 |
|---|---|
| 六项主 slate | 机器构建 **SILVER**，**无独立裁决**（生成候选者=本系统，按规则不得自宣布 Gold） |
| E2-DD-1（"0天"） | SILVER 且**结构可疑**（无 source_dates；notice 2019→penalty 2020 间隔为 0 天不合理）——列入待裁决 |
| E4-DD-1（"22天"） | SILVER，待裁决 |
| E3-DD-1 | **DISPUTED**（与本实验无关，仅状态在案） |

→ **未满足**：六项参考的独立审阅者裁决不存在。这是唯一阻塞项（§11）。
裁决前 Q_terminal 一律按 SILVER 标签报告，裁决后事实才可计入确定性对错。

## 3. 实际使用模型与版本

- glm53 = GLM-5.3；glm53flash = GLM-5.3-Flash（pilot_common.MODELS，端点
  open.bigmodel.cn/api/anthropic/v1/messages，密钥运行时读取，不落盘）。
- 候选池恰为两模型（与冻结 PROFILE 的能力格表一致）。

## 4. 节点级真实模型能力画像（冻结表，Stage-B 124 次真实调用标定，six_arm_scheduler.py cd68ec44 原文）

| kind | glm53 Q | flash Q | TOKENS_PRIOR | LATENCY_PRIOR |
|---|---|---|---|---|
| index / extracts | 0.85 | 0.62 | glm53 1100 / flash 1400 | glm53 8.0s / flash 10.0s |
| timeline | 0.75 | 0.60 | 同上 | 同上 |
| reasoning（v3 镜像） | 0.80 | 0.58 | 同上 | 同上 |
| verification | 0.83 | 0.80 | 同上 | 同上 |
| report | 0.85 | 0.60 | 同上 | 同上 |

（SYSTEMATIC_FAILURES={'contract','parse','evidence'}，SUCCESS_DECAY=0.5，LAMBDA_TOK=1e-5——
均为冻结常数，不改。）

## 5. 两臂策略冻结（零新工程，全部复用已冻结代码）

| 臂 | 冻结实现 | R（共同） | π |
|---|---|---|---|
| A = Static-π | `decide_R_only`（six_arm_scheduler） | 最小闭包恢复 | **保持原分配** |
| B = Dynamic-π | `decide_pi_only`（同文件） | 同语义简单重试 | **按预算反馈为 pending/ready 节点重分配模型**（阈值 10K/3K，可保持原分配） |

Z：两臂均无。执行链 = R9B 在案批次同款（delta 合同 chain `34e563a8` + stage_c_r1 `eaffda4e` +
delta MeterR9Adapter + 共享前缀 fork 去重 + QuotaMeter 重放修复）。
**诚实声明**：Dynamic-π 以冻结 pi-only 策略操作化——其反馈信号为剩余预算（真实执行反馈的最小
版本）；DD-V5.1 的证据门控联合策略（joint_scheduler_v5）因"R、Z 固定 + 不新增工程模块"而排除在
本轮之外。此为本设计的适用边界，写入结论限定。

## 6. 同状态配对执行协议（R9B 已验证的 fork 语义）

每 cell：共享付费前缀（Static-Parallel 跑至 verification 节点 S2 持久合同故障触发）→ 快照 fork
→ A/B 两臂从**同一故障后状态**执行（前缀经 Meter 去重免费重放，臂间仅 π 维度不同）→
分歧标注 NON_ISOLATED。异常注入、证据、候选池、资源槽、截止期、评分全同。

## 7. 重复次数与实验矩阵

**2 任务（SC-E2, SC-E4）× 2 臂 × 3 重复 = 12 runs（6 个配对 cell）**。
固定样本量，不看中途结果，不追加。

## 8. 调用 / Token / 现金预算（按 R9B 在案实测每 cell ≈13 次推算）

- 预计：6 cell × ~13 次 ≈ **78 次调用 / ~115K token**。
- 硬上限申请值：**100 次调用 / 150,000 token；glm53 ≤80 次/120K；flash ≤20 次/30K**。
- **费率与现金**：实际通道为 bigmodel coding-plan 订阅端点，**边际现金 = ¥0**（本轮全程真实费率
  基础，与历轮一致）；磁盘上无名义单价表，如需名义价格口径的现金上限须由操作员提供费率表
  （非阻塞）。

## 9. 终端独立评分与统计分析（冻结）

- **Q_terminal**：终端事实/报告对 silver 的归一化覆盖（R4 评分器语义，不改评分器）；SILVER 标签
  如实；**未裁决/可疑参考（含 E2-DD-1）不计入确定性 Q**，单列报告。
- 报告生成率、UNKNOWN 标注率、失败率、按期完成率（deadline 1800s/cell 级）。
- 成本：每臂实际 token（结算值）与 makespan。
- **统计**：6 个配对 cell 的配对差（ΔQ、Δtoken、Δmakespan、按期率），符号检验 + 描述性区间；
  预登记双侧 α=0.10（n=6 的诚实功效边界）；无中期适应性。

## 10. 运行命令、预算守卫与停止规则

- 驱动：`integration/stage_c_dynpi_exec.py`（**唯一代码增量**：R9B exec 的配置变体——ARMS、
  批名、任务表三处，全部复用冻结链/调度器/评分；授权时 SHA 冻结）。
- 命令：`cd /root/cap_eval_bench_v1 && python3 integration/stage_c_dynpi_exec.py`
  （auth_gate.require('stage_c_dynpi_v1') + 冻结 SHA 门 + flock 独占 + BUDGET_STOP 落档）。
- 守卫：Meter 80→100 上限内联、QuotaMeter 分模型配额、SSL verify-settle-resume。
- **执行者**：本 ZCode 会话为唯一执行代理（R9B 治理教训）；并行代理只读。
- **停止规则**：①固定样本完成即停；②任一上限触顶→BUDGET_STOP 如实落档；③基础设施签名故障
  （截断/解析类成批失败）→ 立即中止保全证据，判失效重报；④缺失配对→成对剔除并在报告中标明。

---

## 11. 结论：**HOLD**

| # | 条件 | 状态 |
|---|---|---|
| 1 | 六项参考的**独立审阅者裁决**（不得由候选生成方自宣布） | ❌ **阻塞**——全部为机器 SILVER，无独立裁决；E2-DD-1 结构可疑待裁。需操作员指定独立审阅者完成（或由操作员本人裁决） |
| 2 | 名义费率表（如需现金计价上限） | ⚠️ 可选——订阅口径 ¥0 已足 |
| 3 | 其余八项（任务/模型/画像/臂/协议/矩阵/预算/评分统计/命令守卫） | ✅ 就绪 |

解除条件：操作员提供六项 slate（+建议连带 E2-DD-1/E4-DD-1）的独立裁决结果 → 本方案即时转 GO，
等待整批一次性授权语句（含批次名 stage_c_dynpi_v1、100 次/150K/GLM≤80 次 120K/Flash≤20 次 30K/¥0）。

**本方案完成后停止，不自动衍生任何新的准备项。**

---

## §12 发射前验证发现与设计修正案（2026-10-30 15:4x，零调用；待操作员一词确认）

**发现 1（致命）**：冻结设计的 S2 持久合同故障@verification 在 Z 固定出局条件下对两臂
**同为确定性死局**（合成验证 4/4 INCOMPLETE：注入与模型无关，R-only 重试同节点、pi-only
重分配模型均无法逃逸；R9B 中 B 臂的生路是 Z=SPLIT_VERIFY，本实验按裁定排除）。照原样发射
= 保证性零结果批次。

**修正案 A（故障重定义，其余全部不变）**：故障改为 **T1 瞬态 transport×1，注入于 π0 分配
flash 的 reasoning 节点**（SC-E2:e2_amount / SC-E4:e4_seq，INITIAL_PI 冻结映射）。
- A=Static-π：重试**保持原分配**（flash→flash）；
- B=Dynamic-π：故障反馈后**重分配**（flash→glm53）；
- 合成验证 4/4：两臂均 COMPLETE、模型序列分化精确如上——处理效应在机制层成立。

**发现 2（致命，接缝测试）**：单一 purpose 命名空间会使 B 的 glm53 重试**去重重放 A 的
flash 响应**（prompt 不含模型→sha 相同）——重分配"执行了"但内容仍是 flash 的，处理被抵消。
**修正案 B（驱动器层，冻结链不动）**：purpose 加模型后缀（QuotaMeter 层重写）；前缀 π0
同模型仍免费重放；故障节点重试因模型不同分开付费；下游因内容 sha 不同自然分开。
接缝复验 PASS：B 的 glm53 重试为真实独立调用；每 cell 付费 8–9 次（真实运行估 11–12），
6 cell ≈ 70 次 ≤ 100 上限。

**不变项**：批次名、任务（SC-E2/SC-E4）、两臂（R-only/pi-only）、3 rep=12 runs/6 配对 cell、
全部上限（100/150K/GLM≤80·120K/Flash≤20·30K/¥0）、配对 fork 协议、评分统计、停止规则、
"不追加额度、不看中途结果"。

**状态**：授权记录的 matrix 字段原载 S2 设计——按授权纪律，故障类型的实质变更须操作员确认
后方可发射（不自行改判）。**等待一词确认。**
