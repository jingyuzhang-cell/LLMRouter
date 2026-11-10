# P2-C 26 任务机制分解表（零调用，源自冻结数据；统计单位=任务，重复见明细）

事实迁移合计（两次重复、全部任务）：ABSENT->LOC_WRONG=3，ABSENT->TP=24，ABSENT->UNSUPPORTED=2，ABSENT->VALUE_WRONG=8，LOC_WRONG->ABSENT=2，LOC_WRONG->TP=52，LOC_WRONG->UNSUPPORTED=4，LOC_WRONG->VALUE_WRONG=1，TP->lost=13，UNKNOWN_OK->UNKNOWN_ASSERTED=1，UNSUPPORTED->ABSENT=6，UNSUPPORTED->LOC_WRONG=1，VALUE_WRONG->LOC_WRONG=2，VALUE_WRONG->TP=3

| 任务 | 计分槽 | G6−G2 | G6−G4 | 机制归类 | 找回/纠偏 | 损失 | 阶段漂移 | G6臂 调用/tokens/¥ |
|---|---:|---:|---:|---|---:|---:|---:|---|
| BQ_600074 | 17 | +0.118 | +0.059 | 证据/数值纠偏型 | 7 | 0 | 0 | 2/11439/0.01 |
| DG_002715 | 19 | +0.000 | +0.000 | 无恢复机会（共享失效/无目标） | 0 | 0 | 0 | 0/0/0.00 |
| DY_002086 | 20 | +0.250 | +0.250 | 证据/数值纠偏型 | 10 | 1 | 1 | 2/17716/0.03 |
| FG_600399 | 25 | +0.000 | +0.000 | 无恢复机会（共享失效/无目标） | 0 | 0 | 0 | 0/0/0.00 |
| FH_002743 | 14 | +0.036 | +0.000 | 证据/数值纠偏型 | 2 | 1 | 0 | 4/26926/0.05 |
| FR_600781 | 20 | +0.225 | +0.025 | 证据/数值纠偏型 | 9 | 0 | 0 | 2/14482/0.02 |
| GD_839680 | 16 | +0.125 | +0.125 | 证据/数值纠偏型 | 5 | 0 | 0 | 2/20304/0.04 |
| HW_600360 | 19 | +0.500 | +0.210 | 证据/数值纠偏型 | 19 | 0 | 0 | 4/40451/0.07 |
| HX_300427 | 19 | +0.026 | -0.026 | 信息找回型（含锚定损失） | 2 | 1 | 1 | 2/18088/0.03 |
| HY_002700 | 16 | +0.125 | +0.125 | 证据/数值纠偏型 | 1 | 0 | 0 | 2/16923/0.03 |
| HZE_000693 | 17 | +0.029 | +0.118 | 证据/数值纠偏型 | 1 | 0 | 0 | 3/25656/0.05 |
| HZ_002122 | 17 | +0.059 | +0.059 | 信息找回型 | 2 | 0 | 0 | 2/22218/0.04 |
| JB_600609 | 18 | +0.000 | +0.000 | 净损失型 | 0 | 1 | 1 | 1/5425/0.01 |
| JD_000922 | 17 | +0.059 | +0.000 | 证据/数值纠偏型 | 4 | 0 | 0 | 3/18889/0.03 |
| JG_300093 | 16 | +0.031 | +0.062 | 证据/数值纠偏型 | 2 | 1 | 1 | 2/19027/0.03 |
| JZ_002470 | 19 | +0.053 | +0.026 | 信息找回型（含锚定损失） | 2 | 1 | 1 | 3/26947/0.04 |
| KJ_600806 | 20 | +0.000 | +0.000 | 无恢复机会（共享失效/无目标） | 0 | 0 | 0 | 0/0/0.00 |
| KR_002072 | 20 | +0.000 | +0.000 | 无恢复机会（共享失效/无目标） | 0 | 0 | 0 | 0/0/0.00 |
| RSK_603803 | 14 | -0.179 | +0.036 | 证据错误锚定型 | 2 | 6 | 6 | 3/17612/0.03 |
| RY_002193 | 20 | +0.025 | +0.025 | 证据/数值纠偏型 | 1 | 0 | 0 | 1/5254/0.01 |
| SK_002278 | 13 | +0.000 | +0.000 | 动作无净变化 | 0 | 0 | 0 | 1/3362/0.00 |
| SW_000755 | 14 | +0.000 | +0.000 | 无恢复机会（共享失效/无目标） | 0 | 0 | 0 | 0/0/0.00 |
| TX_000070 | 16 | +0.094 | +0.094 | 证据/数值纠偏型 | 3 | 0 | 0 | 2/9046/0.01 |
| WC_300089 | 18 | +0.028 | +0.028 | 证据/数值纠偏型 | 3 | 0 | 0 | 2/12491/0.02 |
| WL_300367 | 15 | +0.033 | +0.233 | 信息找回型 | 2 | 1 | 0 | 3/24126/0.04 |
| YS_300376 | 18 | +0.028 | +0.000 | 证据/数值纠偏型 | 2 | 0 | 0 | 2/25866/0.05 |

## 逐重复明细（异常、动作、结果、事实迁移）

**BQ_600074**（N=17，G6−G2=+0.118，证据/数值纠偏型）
- r1: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏4 值错0 引错4 TP9｜Q2=0.529→Q6=0.529｜ABSENT->TP: F6,F7
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=2/0/0（目标2）｜G2缺陷: 遗漏6 值错0 引错6 TP5｜Q2=0.235→Q6=0.471｜ABSENT->UNSUPPORTED: F15｜LOC_WRONG->TP: F1,F2,F3,F5,F6｜LOC_WRONG->UNSUPPORTED: F16

**DG_002715**（N=19，G6−G2=+0.000，无恢复机会（共享失效/无目标））
- r1: shared_fail｜动作=no_action
- r2: no_target｜动作=no_action

**DY_002086**（N=20，G6−G2=+0.250，证据/数值纠偏型）
- r1: shared_fail｜动作=no_action
- r2: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/2/0（目标2）｜G2缺陷: 遗漏1 值错1 引错11 TP7｜Q2=0.300→Q6=0.800｜LOC_WRONG->TP: F1,F2,F3,F4,F5,F6,F7,F8,F9,F10｜TP->lost: F14｜阶段漂移(D1↔D2): F14

**FG_600399**（N=25，G6−G2=+0.000，无恢复机会（共享失效/无目标））
- r1: shared_fail｜动作=no_action
- r2: shared_fail｜动作=no_action

**FH_002743**（N=14，G6−G2=+0.036，证据/数值纠偏型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=1/1/0（目标2）｜G2缺陷: 遗漏2 值错3 引错6 TP3｜Q2=0.143→Q6=0.214｜ABSENT->LOC_WRONG: F9｜TP->lost: F8｜VALUE_WRONG->LOC_WRONG: F6｜VALUE_WRONG->TP: F7,F14
- r2: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=1/5/0（目标6）｜G2缺陷: 遗漏2 值错0 引错7 TP5｜Q2=0.214→Q6=0.214｜ABSENT->VALUE_WRONG: F9｜UNSUPPORTED->ABSENT: F11

**FR_600781**（N=20，G6−G2=+0.225，证据/数值纠偏型）
- r1: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏2 值错1 引错10 TP7｜Q2=0.350→Q6=0.750｜ABSENT->TP: F16｜LOC_WRONG->TP: F1,F4,F5,F6,F7,F8,F11
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏2 值错1 引错2 TP15｜Q2=0.750→Q6=0.800｜ABSENT->TP: F16

**GD_839680**（N=16，G6−G2=+0.125，证据/数值纠偏型）
- r1: recovery_truncated｜动作=upstream_J2R+SINK
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏1 值错1 引错9 TP5｜Q2=0.188→Q6=0.438｜LOC_WRONG->TP: F1,F2,F3,F4,F7｜LOC_WRONG->UNSUPPORTED: F14

**HW_600360**（N=19，G6−G2=+0.500，证据/数值纠偏型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/8/0（目标8）｜G2缺陷: 遗漏1 值错0 引错9 TP9｜Q2=0.263→Q6=0.842｜ABSENT->TP: F18｜LOC_WRONG->TP: F1,F2,F3,F4,F5,F6,F7,F8｜UNKNOWN_OK->UNKNOWN_ASSERTED: F13
- r2: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/1/0（目标1）｜G2缺陷: 遗漏2 值错0 引错10 TP7｜Q2=0.263→Q6=0.684｜ABSENT->TP: F17,F18｜LOC_WRONG->TP: F1,F2,F3,F4,F5,F6,F7,F8｜LOC_WRONG->UNSUPPORTED: F9

**HX_300427**（N=19，G6−G2=+0.026，信息找回型（含锚定损失））
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=1/8/0（目标9）｜G2缺陷: 遗漏3 值错0 引错2 TP14｜Q2=0.684→Q6=0.737｜ABSENT->TP: F14,F16｜ABSENT->UNSUPPORTED: F15｜LOC_WRONG->ABSENT: F19｜TP->lost: F1｜阶段漂移(D1↔D2): F1
- r2: shared_fail｜动作=no_action

**HY_002700**（N=16，G6−G2=+0.125，证据/数值纠偏型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/5/0（目标5）｜G2缺陷: 遗漏2 值错0 引错6 TP8｜Q2=0.250→Q6=0.500｜ABSENT->TP: F14｜LOC_WRONG->VALUE_WRONG: F2
- r2: no_target｜动作=no_action

**HZE_000693**（N=17，G6−G2=+0.029，证据/数值纠偏型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/1/0（目标1）｜G2缺陷: 遗漏4 值错1 引错10 TP2｜Q2=0.118→Q6=0.118｜ABSENT->VALUE_WRONG: F16｜UNSUPPORTED->LOC_WRONG: F8
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=2/0/0（目标2）｜G2缺陷: 遗漏6 值错2 引错4 TP5｜Q2=0.294→Q6=0.353｜ABSENT->TP: F19｜ABSENT->VALUE_WRONG: F16｜VALUE_WRONG->LOC_WRONG: F2

**HZ_002122**（N=17，G6−G2=+0.059，信息找回型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/6/0（目标6）｜G2缺陷: 遗漏3 值错2 引错1 TP11｜Q2=0.529→Q6=0.647｜ABSENT->TP: F11,F12｜ABSENT->VALUE_WRONG: F14｜UNSUPPORTED->ABSENT: F17
- r2: shared_fail｜动作=no_action

**JB_600609**（N=18，G6−G2=+0.000，净损失型）
- r1: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏3 值错1 引错0 TP14｜Q2=0.667→Q6=0.667｜TP->lost: F11｜阶段漂移(D1↔D2): F11
- r2: no_target｜动作=no_action

**JD_000922**（N=17，G6−G2=+0.059，证据/数值纠偏型）
- r1: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏4 值错0 引错11 TP2｜Q2=0.118→Q6=0.118｜LOC_WRONG->TP: F10
- r2: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=1/5/0（目标6）｜G2缺陷: 遗漏4 值错0 引错11 TP2｜Q2=0.118→Q6=0.235｜ABSENT->TP: F11,F12｜ABSENT->VALUE_WRONG: F14,F15｜LOC_WRONG->TP: F10

**JG_300093**（N=16，G6−G2=+0.031，证据/数值纠偏型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=1/6/0（目标7）｜G2缺陷: 遗漏2 值错1 引错10 TP3｜Q2=0.188→Q6=0.250｜LOC_WRONG->TP: F11,F12｜TP->lost: F4｜UNSUPPORTED->ABSENT: F18｜阶段漂移(D1↔D2): F4
- r2: shared_fail｜动作=no_action

**JZ_002470**（N=19，G6−G2=+0.053，信息找回型（含锚定损失））
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/5/0（目标5）｜G2缺陷: 遗漏3 值错1 引错7 TP8｜Q2=0.368→Q6=0.421｜ABSENT->TP: F15｜ABSENT->VALUE_WRONG: F16｜TP->lost: F7｜阶段漂移(D1↔D2): F7
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏3 值错1 引错7 TP8｜Q2=0.368→Q6=0.421｜ABSENT->TP: F15｜LOC_WRONG->UNSUPPORTED: F19

**KJ_600806**（N=20，G6−G2=+0.000，无恢复机会（共享失效/无目标））
- r1: shared_fail｜动作=no_action
- r2: shared_fail｜动作=no_action

**KR_002072**（N=20，G6−G2=+0.000，无恢复机会（共享失效/无目标））
- r1: shared_fail｜动作=no_action
- r2: no_target｜动作=no_action

**RSK_603803**（N=14，G6−G2=-0.179，证据错误锚定型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=1/4/0（目标5）｜G2缺陷: 遗漏1 值错1 引错4 TP8｜Q2=0.429→Q6=0.071｜ABSENT->LOC_WRONG: F9｜LOC_WRONG->TP: F7｜TP->lost: F1,F2,F3,F4,F5｜UNSUPPORTED->ABSENT: F13｜阶段漂移(D1↔D2): F1,F2,F3,F4,F5
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=2/0/0（目标2）｜G2缺陷: 遗漏3 值错1 引错8 TP2｜Q2=0.143→Q6=0.143｜ABSENT->TP: F9｜TP->lost: F7｜阶段漂移(D1↔D2): F7

**RY_002193**（N=20，G6−G2=+0.025，证据/数值纠偏型）
- r1: shared_fail｜动作=no_action
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏3 值错0 引错8 TP9｜Q2=0.300→Q6=0.350｜ABSENT->LOC_WRONG: F19｜ABSENT->TP: F15

**SK_002278**（N=13，G6−G2=+0.000，动作无净变化）
- r1: shared_fail｜动作=no_action
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏3 值错2 引错4 TP4｜Q2=0.231→Q6=0.231

**SW_000755**（N=14，G6−G2=+0.000，无恢复机会（共享失效/无目标））
- r1: no_target｜动作=no_action
- r2: no_target｜动作=no_action

**TX_000070**（N=16，G6−G2=+0.094，证据/数值纠偏型）
- r1: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏1 值错1 引错9 TP5｜Q2=0.312→Q6=0.375｜ABSENT->TP: F13
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏1 值错1 引错12 TP2｜Q2=0.125→Q6=0.250｜ABSENT->TP: F13｜LOC_WRONG->TP: F8

**WC_300089**（N=18，G6−G2=+0.028，证据/数值纠偏型）
- r1: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏2 值错1 引错10 TP5｜Q2=0.278→Q6=0.278｜LOC_WRONG->TP: F11,F12
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏2 值错0 引错9 TP7｜Q2=0.389→Q6=0.444｜ABSENT->TP: F13

**WL_300367**（N=15，G6−G2=+0.033，信息找回型）
- r1: recovered｜动作=upstream_J2R+SINK｜异常 S1/S2/S3=0/8/0（目标8）｜G2缺陷: 遗漏2 值错0 引错10 TP3｜Q2=0.133→Q6=0.200｜ABSENT->TP: F10,F11｜TP->lost: F9｜UNSUPPORTED->ABSENT: F14
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏2 值错1 引错4 TP8｜Q2=0.533→Q6=0.533

**YS_300376**（N=18，G6−G2=+0.028，证据/数值纠偏型）
- r1: recovery_truncated｜动作=upstream_J2R+SINK
- r2: recovered｜动作=terminal_SINK_only｜异常 S1/S2/S3=1/0/0（目标1）｜G2缺陷: 遗漏2 值错1 引错10 TP5｜Q2=0.167→Q6=0.222｜ABSENT->VALUE_WRONG: F13｜LOC_WRONG->ABSENT: F15｜LOC_WRONG->TP: F6｜UNSUPPORTED->ABSENT: F16｜VALUE_WRONG->TP: F8

