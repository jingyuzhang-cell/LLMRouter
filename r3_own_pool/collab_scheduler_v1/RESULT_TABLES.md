# 结果表（v2，fault30 完成后更新 2026-09-28）

数据源：CUBE_CLEAN_ANALYSIS.json / FAULT30_ANALYSIS.json / REPLAY_{CLEAN,FAULT}.json / results_sim_v1_regenerated

## T1 主表：15 配置 × 两状态（fault 为 3 种子均值±std，n=600）

| config | Q_clean | C_clean | L_clean | Q_fault | Q_fault_std | C_fault | L_fault | ΔQ(clean→fault) |
|---|---|---|---|---|---|---|---|---|
| DYNAMICDAG__BALANCED__LOCAL_REROUTE | 0.295 | 1506.7 | 3.596 | 0.2817 | 0.0201 | 2260.8 | 5.035 | -0.0133 |
| DYNAMICDAG__BALANCED__NONE | 0.295 | 1506.7 | 3.596 | 0.25 | 0.0108 | 1490.7 | 3.595 | -0.045 |
| DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE | 0.33 | 1484.0 | 3.174 | 0.3433 | 0.0047 | 2089.3 | 4.454 | 0.0133 |
| DYNAMICDAG__HETEROGENEOUS__NONE | 0.33 | 1484.0 | 3.174 | 0.2767 | 0.0085 | 1467.3 | 3.191 | -0.0533 |
| DYNAMICDAG__QUALITY__LOCAL_REROUTE | 0.31 | 1513.8 | 3.866 | 0.29 | 0.0178 | 2111.9 | 5.42 | -0.02 |
| DYNAMICDAG__QUALITY__NONE | 0.31 | 1513.8 | 3.866 | 0.2667 | 0.0047 | 1498.6 | 3.913 | -0.0433 |
| PARALLELER__BALANCED__NONE | 0.295 | 1244.6 | 3.32 | 0.255 | 0.0108 | 1236.9 | 3.32 | -0.04 |
| PARALLELER__HETEROGENEOUS__NONE | 0.305 | 1219.5 | 2.876 | 0.2767 | 0.0085 | 1211.2 | 2.879 | -0.0283 |
| PARALLELER__QUALITY__NONE | 0.315 | 1219.9 | 2.942 | 0.28 | 0.0108 | 1210.9 | 2.922 | -0.035 |
| SERV__BALANCED__NONE | 0.325 | 1269.7 | 3.324 | 0.2633 | 0.0155 | 1242.9 | 3.313 | -0.0617 |
| SERV__HETEROGENEOUS__NONE | 0.365 | 1194.2 | 2.678 | 0.2883 | 0.0103 | 1170.5 | 2.699 | -0.0767 |
| SERV__QUALITY__NONE | 0.335 | 1208.4 | 3.04 | 0.2683 | 0.0165 | 1194.3 | 3.3 | -0.0667 |
| SER__BALANCED__NONE | 0.295 | 1029.6 | 3.044 | 0.2417 | 0.0165 | 1016.9 | 3.042 | -0.0533 |
| SER__HETEROGENEOUS__NONE | 0.37 | 963.5 | 2.375 | 0.3083 | 0.0184 | 952.0 | 2.376 | -0.0617 |
| SER__QUALITY__NONE | 0.34 | 963.3 | 2.408 | 0.2833 | 0.0125 | 951.5 | 2.405 | -0.0567 |
| SINGLE__QUALITY__RETRY（锚） | 0.550 | 612.8 | 0.460 | 0.3967 | .0176 | 802.0 | 0.59 | −0.153 |

## T2 前沿与 HV（修复后 hypervolume）

| 前沿 | 点集 | HV |
|---|---|---|
| 全局 P*_clean | {SINGLE} | 0.2884 |
| 全局 P*_fault | {SINGLE}（**未扩张**） | 0.2281 |
| DAG 子空间 clean | {SER__HET, SER__QUALITY} | 0.0519 |
| DAG 子空间 fault | {SER__HET, SER__QUALITY, **DYN__HET__LOCAL_REROUTE**} | 0.1007 |

## T3 Z 价值（Δ_Z = LOCAL_REROUTE − NONE，DYNAMICDAG）

| X | Δ_Z Q | Δ_Z C | Δ_Z L | recovery-induced trade-off |
|---|---|---|---|---|
| BALANCED | +0.0317 | +770.1 | +1.44 | True |
| HETEROGENEOUS | +0.0666 | +622.0 | +1.263 | True |
| QUALITY | +0.0233 | +613.3 | +1.507 | True |

配对检验与内部锚点见 FAULT30_ANALYSIS.json（provenance 全通过；QUALITY 家族锚点有 0.7% ok 单元/中位 3.6% cost 的双会话噪声，结论裕度远大于此）。

## T4 搜索策略（DAG 子空间 fault 前沿，实测 3 点，16 种子）

| strategy | final regret | recall | AUC-HV | N95%HV |
|---|---|---|---|---|
| random | 0.061±0.093 | 0.625 | 0.863 | never 8/16 |
| greedy_q | 0.065±0.097 | 0.625 | 0.862 | never 7/16 |
| ehvi | 0.004±0.002 | 0.750 | 0.919 | never 0/16 |
| cost_aware_ehvi | 0.004±0.002 | 0.750 | 0.921 | never 0/16 |

## 补充：sim_search 重生（修复后实现，替代 INVALIDATED 旧结果）

ehvi 1.013±0.020 / cost_aware 1.017±0.023 / greedy 0.677±0.336 / random 0.405±0.018（HV/HV*，8 种子）
