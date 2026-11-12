# P2-C 26 任务机制分解表 V2.1（M3 一致口径；V2 验收后修订）

修订（操作员验收意见 2026-11-10）：①"损失"列更名为"TP→lost"（仅计原有正确事实的丢失；ABSENT→LOC_WRONG 等其他不利迁移保留在逐事实明细）；②"证据/数值纠偏型"更名为"证据支持链纠偏型"（最终口径正向迁移 72 次 = 引文定位纠正 45 + 信息找回 27，无 VALUE_WRONG→TP）；③阶段漂移合计为 10（RSK 6 + HW 2 + HX 1 + JG 1），与 TP→lost 的 10 次一一对应（8 次 TP→LOC_WRONG + 2 次 TP→ABSENT）。
口径：事实迁移与 Q 均为 M3 后最终终端评分口径；312 个（区组×臂）Q 与 P2C_RESULTS 逐一对账一致（0 失配）。
迁移合计（最终口径）：LOC_WRONG→TP 45｜ABSENT→TP 27｜正向合计 72｜TP→LOC_WRONG 8｜TP→ABSENT 2｜TP→lost 合计 10（全部涉及阶段—文书支持错配）。
对照（M3 前原始响应口径）：LOC_WRONG→TP 52｜ABSENT→TP 24｜VALUE_WRONG→TP 3｜TP→lost 13。
统计单位=26 个独立任务；迁移次数为事实级事件计数，不作独立样本使用。单任务效应及分类合计采用未舍入原始值计算；表内任务级数值保留三位小数，展示值求和可能有微小舍入差异。

| 任务 | 槽 | G6−G2 | G6−G4 | 机制归类 | 正向迁移 | TP→lost | 阶段漂移 |
|---|---:|---:|---:|---|---:|---:|---:|
| BQ_600074 | 17 | +0.118 | +0.059 | 证据支持链纠偏型 | 4 | 0 | 0 |
| DG_002715 | 19 | +0.000 | +0.000 | 无恢复目标型（一次重复共享失效） | 0 | 0 | 0 |
| DY_002086 | 20 | +0.250 | +0.250 | 证据支持链纠偏型 | 10 | 0 | 0 |
| FG_600399 | 25 | +0.000 | +0.000 | 共享上游失效型 | 0 | 0 | 0 |
| FH_002743 | 14 | +0.036 | +0.000 | 证据支持链纠偏型 | 1 | 0 | 0 |
| FR_600781 | 20 | +0.225 | +0.025 | 证据支持链纠偏型 | 9 | 0 | 0 |
| GD_839680 | 16 | +0.125 | +0.125 | 证据支持链纠偏型 | 4 | 0 | 0 |
| HW_600360 | 19 | +0.500 | +0.210 | 证据支持链纠偏型 | 21 | 2 | 2 |
| HX_300427 | 19 | +0.026 | -0.026 | 信息找回型（含锚定损失） | 2 | 1 | 1 |
| HY_002700 | 16 | +0.125 | +0.125 | 信息找回型 | 4 | 0 | 0 |
| HZE_000693 | 17 | +0.029 | +0.118 | 证据支持链纠偏型 | 1 | 0 | 0 |
| HZ_002122 | 17 | +0.059 | +0.059 | 信息找回型 | 2 | 0 | 0 |
| JB_600609 | 18 | +0.000 | +0.000 | 动作无净变化型 | 0 | 0 | 0 |
| JD_000922 | 17 | +0.059 | +0.000 | 信息找回型 | 2 | 0 | 0 |
| JG_300093 | 16 | +0.031 | +0.062 | 证据支持链纠偏型 | 2 | 1 | 1 |
| JZ_002470 | 19 | +0.053 | +0.026 | 信息找回型 | 2 | 0 | 0 |
| KJ_600806 | 20 | +0.000 | +0.000 | 共享上游失效型 | 0 | 0 | 0 |
| KR_002072 | 20 | +0.000 | +0.000 | 无恢复目标型（一次重复共享失效） | 0 | 0 | 0 |
| RSK_603803 | 14 | -0.179 | +0.036 | 证据错误锚定型 | 1 | 6 | 6 |
| RY_002193 | 20 | +0.025 | +0.025 | 证据支持链纠偏型 | 1 | 0 | 0 |
| SK_002278 | 13 | +0.000 | +0.000 | 动作无净变化型 | 0 | 0 | 0 |
| SW_000755 | 14 | +0.000 | +0.000 | 无恢复目标型 | 0 | 0 | 0 |
| TX_000070 | 16 | +0.094 | +0.094 | 证据支持链纠偏型 | 3 | 0 | 0 |
| WC_300089 | 18 | +0.028 | +0.028 | 证据支持链纠偏型 | 1 | 0 | 0 |
| WL_300367 | 15 | +0.033 | +0.233 | 证据支持链纠偏型 | 1 | 0 | 0 |
| YS_300376 | 18 | +0.028 | +0.000 | 证据支持链纠偏型 | 1 | 0 | 0 |

## 分类合计（未舍入）

- 证据支持链纠偏型：n=13，Σ(G6−G2)=+1.5216
- 信息找回型：n=4，Σ(G6−G2)=+0.2952
- 信息找回型（含锚定损失）：n=1，Σ(G6−G2)=+0.0263
- 无恢复目标型（一次重复共享失效）：n=2，Σ(G6−G2)=+0.0000
- 共享上游失效型：n=2，Σ(G6−G2)=+0.0000
- 动作无净变化型：n=2，Σ(G6−G2)=+0.0000
- 无恢复目标型：n=1，Σ(G6−G2)=+0.0000
- 证据错误锚定型：n=1，Σ(G6−G2)=-0.1786
- 合计：26 任务，Σ=+1.6645（=26×H2 均值 0.0640）

## 逐重复明细（结果｜动作｜事实迁移｜阶段漂移）

**BQ_600074**（N=17，G6−G2=+0.118，证据支持链纠偏型）
- r1: recovered｜terminal_SINK_only
- r2: recovered｜terminal_SINK_only｜LOC_WRONG->TP: F1,F2,F3,F5

**DG_002715**（N=19，G6−G2=+0.000，无恢复目标型（一次重复共享失效））
- r1: shared_fail｜no_action
- r2: no_target｜no_action

**DY_002086**（N=20，G6−G2=+0.250，证据支持链纠偏型）
- r1: shared_fail｜—
- r2: recovered｜upstream_J2R+SINK｜LOC_WRONG->TP: F1,F2,F3,F4,F5,F6,F7,F8,F9,F10

**FG_600399**（N=25，G6−G2=+0.000，共享上游失效型）
- r1: shared_fail｜no_action
- r2: shared_fail｜—

**FH_002743**（N=14，G6−G2=+0.036，证据支持链纠偏型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F14
- r2: recovered｜upstream_J2R+SINK

**FR_600781**（N=20，G6−G2=+0.225，证据支持链纠偏型）
- r1: recovered｜terminal_SINK_only｜ABSENT->TP: F16｜LOC_WRONG->TP: F1,F4,F5,F6,F7,F8,F11
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F16

**GD_839680**（N=16，G6−G2=+0.125，证据支持链纠偏型）
- r1: recovery_truncated｜upstream_J2R+SINK
- r2: recovered｜terminal_SINK_only｜LOC_WRONG->TP: F1,F2,F3,F4

**HW_600360**（N=19，G6−G2=+0.500，证据支持链纠偏型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F12,F15,F18｜LOC_WRONG->TP: F1,F2,F3,F4,F5,F6,F7,F8
- r2: recovered｜upstream_J2R+SINK｜ABSENT->TP: F17,F18｜LOC_WRONG->TP: F1,F2,F3,F4,F5,F6,F7,F8｜TP->ABSENT: F12,F15｜阶段漂移: F12,F15

**HX_300427**（N=19，G6−G2=+0.026，信息找回型（含锚定损失））
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F14,F16｜TP->LOC_WRONG: F1｜阶段漂移: F1
- r2: shared_fail｜no_action

**HY_002700**（N=16，G6−G2=+0.125，信息找回型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F9,F10,F11,F14｜LOC_WRONG->VALUE_WRONG: F2｜UNKNOWN_ASSERTED->UNKNOWN_OK: F12
- r2: no_target｜no_action

**HZE_000693**（N=17，G6−G2=+0.029，证据支持链纠偏型）
- r1: recovered｜upstream_J2R+SINK
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F19｜VALUE_WRONG->LOC_WRONG: F2

**HZ_002122**（N=17，G6−G2=+0.059，信息找回型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F11,F12
- r2: shared_fail｜no_action

**JB_600609**（N=18，G6−G2=+0.000，动作无净变化型）
- r1: recovered｜terminal_SINK_only｜ABSENT->VALUE_WRONG: F11
- r2: no_target｜no_action

**JD_000922**（N=17，G6−G2=+0.059，信息找回型）
- r1: recovered｜terminal_SINK_only
- r2: recovered｜upstream_J2R+SINK｜ABSENT->TP: F11,F12

**JG_300093**（N=16，G6−G2=+0.031，证据支持链纠偏型）
- r1: recovered｜upstream_J2R+SINK｜LOC_WRONG->TP: F11,F12｜TP->LOC_WRONG: F4｜阶段漂移: F4
- r2: shared_fail｜no_action

**JZ_002470**（N=19，G6−G2=+0.053，信息找回型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F15
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F15

**KJ_600806**（N=20，G6−G2=+0.000，共享上游失效型）
- r1: shared_fail｜no_action
- r2: shared_fail｜no_action

**KR_002072**（N=20，G6−G2=+0.000，无恢复目标型（一次重复共享失效））
- r1: shared_fail｜no_action
- r2: no_target｜no_action

**RSK_603803**（N=14，G6−G2=-0.179，证据错误锚定型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->LOC_WRONG: F9｜TP->LOC_WRONG: F1,F2,F3,F4,F5｜阶段漂移: F1,F2,F3,F4,F5
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F9｜TP->LOC_WRONG: F7｜阶段漂移: F7

**RY_002193**（N=20，G6−G2=+0.025，证据支持链纠偏型）
- r1: shared_fail｜no_action
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F15

**SK_002278**（N=13，G6−G2=+0.000，动作无净变化型）
- r1: shared_fail｜no_action
- r2: recovered｜terminal_SINK_only

**SW_000755**（N=14，G6−G2=+0.000，无恢复目标型）
- r1: no_target｜no_action
- r2: no_target｜no_action

**TX_000070**（N=16，G6−G2=+0.094，证据支持链纠偏型）
- r1: recovered｜terminal_SINK_only｜ABSENT->TP: F13
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F13｜LOC_WRONG->TP: F8

**WC_300089**（N=18，G6−G2=+0.028，证据支持链纠偏型）
- r1: recovered｜terminal_SINK_only｜LOC_WRONG->ABSENT: F11,F12
- r2: recovered｜terminal_SINK_only｜ABSENT->TP: F13

**WL_300367**（N=15，G6−G2=+0.033，证据支持链纠偏型）
- r1: recovered｜upstream_J2R+SINK｜ABSENT->TP: F11
- r2: recovered｜terminal_SINK_only

**YS_300376**（N=18，G6−G2=+0.028，证据支持链纠偏型）
- r1: recovery_truncated｜upstream_J2R+SINK
- r2: recovered｜terminal_SINK_only｜LOC_WRONG->TP: F6｜VALUE_WRONG->ABSENT: F8

