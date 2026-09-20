# 论文证据映射

审计日期：2026-09-20。项目根目录 `/root/r3_own_pool`；下表路径相对该目录。最新版本优先指已审计数据与相应实现，不以修改时间单独判断。原始实验文件保持不变。

证据层级：**开发**为开发样本分析；**条件化**（conditional）为标准输入或理想判定条件；**回放**（replay）为既有输出上的策略模拟；**真实调用**（live）指实际生成与传播，仍需另查调度是否读金标准；**确认**（confirmation）说明模型冻结后的评价，不自动表示样本从未分析。

本稿新增 `derive_evidence.py` 仅对既有记录作统计，不产生模型调用。其结果 `DERIVED_EVIDENCE.json` 保存输入 SHA-256、聚类区间和逐类计数。种子 20260920、10,000 次重采样，采用任务聚类的节点加权 ratio-of-sums 统计；不可与旧稿任务等权 CI 无标注混用。

| 编号、论文结论 | 实验及来源文件 | 样本量 | 本稿采用数字 | 层级 | 限制及处理 |
| --- | --- | --- | --- | --- | --- |
| E01 节点能力异构、冻结节点选择优于查询选择 | `static_dag_v0/fresh_static_confirmation/SCORED_MATRIX_EXEC.npz`、`NODES.json`、`PREDICTIONS.json`、`DEV_FROZEN.json`、`EXPOSURE_AUDIT.json`；本目录 `DERIVED_EVIDENCE.json:routing` | 100 任务、493 主节点、4 探索节点 | AlwaysLarge .4685598；Query .4665314；Node .535497；类型先验 .535497；重新最大化 Oracle .6064909；Node−Query +.0689655，CI [.034413,.106122] | 条件化＋冻结确认 | train 中经工作区记录审计抽取，非官方 test；新版执行器事后重评分。矩阵保存的旧 Oracle 选择重评分为 .6044625，不能当新版严格上界；不能由节点分数推完整 DAG 成功率 |
| E02 类型粒度贡献主要增益 | `static_dag_v0/node_router_ablation/RESULTS.json`、`node_router_ablation.py`；`tool_aware_v1/node_benchmark/NODE_GAP_AUDIT.json`；本目录新版复核 | 开发 201 任务/372 节点；确认 100/493 | 原开发 Query .3951613、Type .4543011、Node .4704301；新版确认 Node−Type=0，CI [−.012097,.012121] | 开发交叉验证＋条件化确认 | 消融开发使用质量排序，不能直接替换原 Q/C/L 主实验开发表；JSON conclusion 的“dev −1.1pp”与数值矛盾，弃用文字字段。旧 fresh +.2pp 已被新版评分修正 |
| E03 学习式节点表示无稳定跨域优势 | `static_dag_v0/tatqa_benchmark/V2_ANALYSIS.json` | 40 任务、200 节点 | Query .61、Type .63、v2 .61、Oracle .75；v2−Type CI [−5.5,1.5]pp | 条件化、开发/跨域分析 | 不能称所有设置均独立确认，差异不显著 |
| E04 分解收益依领域变化 | `static_dag_v0/scale_up/DECOMP_UTILITY.json`、`scale_up_analyze.py`、`scale_up_collect.py` | 配对 TAT-QA160、MH50；总210 | TQ .525→.43125，−.09375 CI[−.175,−.013]；MH .08→.22，+.14 CI[.02,.26]；pooled −.038095 CI[−.105,.033] | 混合历史真实调用/条件化 | 全量 chain200/100不是配对160/50；TQ存在 gold fallback，MH包含条件化节点结果。表中配对 DAG 均值由 mono+paired_diff 恢复，不用全量均值 |
| E05 复杂度分层的探索趋势 | `static_dag_v0/complexity_stratification.json`；本目录 `DERIVED_EVIDENCE.json:complexity` | 260 记录：196/40/24 | 低复杂75→62；中复杂19→23；高复杂2→7 | 探索性、输入条件混合 | 无 UID、未定位独立生成脚本；与E04样本不一致。仅保留记录描述，不能宣称严格匹配、因果或单调显著关系；金标准复杂度不是部署特征 |
| E06 证据覆盖与成功相关 | `static_dag_v0/recovery_matrix_v2/split_quality/SPLIT_QUALITY.json` | 100，正确9 | Coverage r=.377；Dependency .290；Executability .281；Atomicity .078 | 离线诊断/条件化 | 相关不是因果；Coverage很大程度为证据完整性，不等于分解质量 |
| E07 状态反馈与恢复组合有回放收益 | `static_dag_v0/feedback_state_aware_v1/RESULTS_EXEC.json` | 493 主节点 | Static/V0 .535497，V1 .582150；调用倍率1.460446；原聚类CI [.026,.068] | 条件化＋回放 | 理想反馈、增加回退机会，非记忆独立因果消融；tokens字段有估算/口径限制，未当完整E2E资源表 |
| E08 原失败池混入原答案正确样本 | `static_dag_v0/recovery_matrix_v2/full_4983983/ORIG_CORRECTNESS.json`、`SEQUENTIAL_RECOVERY.json` | 148→116节点，96任务 | 排除32：E16、R13、S3；保留45/48/23 | 离线失败判据审计 | “缺陷节点”不等于“最终任务失败”；116为原池重新限定，不是重新采样 |
| E09 重试成功不支持确定性同提示重试 | `static_dag_v0/recovery_matrix_v2/full_4983983/RETRY_AUDIT.json`、`ORIG_CORRECTNESS.json` | MH79、TQ69 | 表观成功34，其中32原答案已正确；MH提示相同0/79；TQ提示相同69/69、输出完全相同66/69 | 原调用语义审计 | 剩余2真实恢复提示改变；不能宣称temperature0同提示重试有1.72%恢复率 |
| E10 历史分解上界受标准事实影响 | `static_dag_v0/recovery_matrix_v2/full_4983983/HISTORICAL_REAUDIT.json` | 分解40 | gold facts成功13/40，实际事实可确认仍成立1；另12为错误值4/索引2/无真实抽取记录6；后6不能重评 | 条件化→实际事实重评分 | 未定位旧“19/60”对应独立冻结记录；不沿用31.7%端到端恢复；此重评分不等于重新在线生成 |
| E11 动态回放未提高质量 | `static_dag_v0/static_vs_dynamic/RESULTS.json` | 100任务 | Static .41、Dynamic .40；dQ CI[−.03,0]；tokens7020.5/7034.6 | 回放 | 差异不显著；实际Static开销乘1.2作为预算，非先验预算 |
| E12 动态第一版真实调用结果有限 | `static_dag_v0/live_static_dynamic/LIVE_ANALYSIS.json`、`LIVE_POLICY.json`、`RAW_TAIL.json`、`live_static_dynamic.py` | 48任务 | 25→26正确；Help2/Harm1；CI[−.0417,.1042]；C1402.2/1403.8；L2.95/2.89 | 真实调用＋理想失败检测；已分析面板 | `close(val,t['answer'])`参与恢复触发；不是无金标准在线闭环；共同失败21，不是旧稿22 |
| E13 选择性动态降低观察到的破坏 | `static_dag_v0/dynamic_v2_test/TEST_ANALYSIS.json`、`POLICY_FROZEN.json`、`dynamic_v2_test.py`、`dynamic_v2_policy.py`；本目录复核 | 同48任务 | Static25、v2 26；Help1/Harm0；C1400.6；L3.091407；重调度25；CI[0,.0625]；token超支0 | 真实分歧调用/共享前缀＋理想检测；已分析确认 | 更新失败计数也读取gold；不是untouched test；重调度字段含局部回退，不等于全局后继调整；预算实际Static×1.2；不声称时延下降 |
| E14 受控故障提供有限互补线索 | `static_dag_v0/controlled_fault_propagation/RAW_RESULTS.json`、`CFP_POLICY.json`、`controlled_fault_analyze.py`；本目录复核 | 候选33；实际118配对，C0/T1/T2/T3=30/28/30/30 | 正确数16/15、2/2、1/1、13/15；Help/Harm=0/1、1/1、0/0、2/0 | 开发、真实调用、理想检测 | 原恢复统计误用动态success计算静态，且分母不一；本稿弃用原恢复率及CI；C0等同29/30；T3同时改变抽取和推理，非单因素；T1不保证删必要操作数 |
| E15 固定恢复集合覆盖有限 | `static_dag_v0/recovery_matrix_v2/full_4983983/FULL_RESULTS.json`、`ORIG_CORRECTNESS.json`、`SEQUENTIAL_RECOVERY.json`；本目录复核 | 116节点/96任务 | 单动作成功2/2/5/2；tokens276.0/275.7/2939.1/3030.3；服务秒.322/.366/3.488/3.900；并集8/116 | 真实动作记录＋离线序列回放 | 顺序停止读gold；当前输出集合上界；corrected_matrix_ci成本0为占位，本稿从原始行复算；成功事件极少，不推出稳定类型映射 |
| E16 历史图减少特定追问执行 | `static_dag_v0/graph_forest_v1/RESULTS.json`及同目录记录 | 20追问 | reused40、新调用40、基线80；call−50%、token−91.4075%；exec19、respond19、verifier_accept0 | 真实追问调用＋历史结果复用 | 逻辑基线不同于全物理计费；19/20不是成功率；无大规模pruning质量证据 |
| E17 剩余预算限制可利用恢复 | `static_dag_v0/budget_surface/BUDGET_SURFACE.json`、`budget_surface.py` | 116节点；11×7=77格 | (500,1).0259；(1000,2).0345；(2000,3).0431；(3000,3).0517；无限.069 | 离线预算回放、已知实际消耗与gold停止 | 零违反是筛选构造，不是在线保证；均匀网格平均非部署分布；aggregate并非标准Pareto hypervolume |
| E18 门控范围影响模拟策略 | `static_dag_v0/type_aware_gate_ablation/RESULTS_EXEC.json` | 493主节点 | global .535497、typeaware .547667；reroute231/186，verifier calls439/302 | 测得混淆率驱动的模拟回放 | 不是当前逐输出真实验证；oracle_bound仍旧版.578093，弃用；早期.5254不是新版主表 |
| E19 局部重规划未增加覆盖 | `static_dag_v0/recovery_matrix_v2/dev_replan_pilot/DEV_ANALYSIS.json` | 开发40节点 | 重规划成功1；四动作并集.10，加入后.10；replan5930.6tokens/5.505s | 开发动作实测＋离线评分 | NO-GO；不能作独立确认或正贡献，也不代表任何拓扑改写必然无效 |
| E20 历史综合实验只保留追溯 | `static_dag_v0/e2e_formal/RESULTS.json`、`live_e2e/RESULTS.json`、`recovery_matrix_v2/HISTORICAL_REAUDIT.json` | Formal100；旧Live50 | Formal22/27/56%；旧Live24/28/34%；strict rescue5/38 | 旧回放；混合输入/历史真实调用 | 协议与后期动态不同；gold fallback等问题未由失败重审计自动消除；不作为v2最终主结论 |

## 新版数字修订记录

1. 主节点确认使用扩展评分，旧 .5132/.5558 不继续作为新版节点主表；旧正式回放仍可保留其自身历史结果，不能给旧实验直接替换分数。
2. 真正新版 Node Oracle 为 .6064909。保留旧选择后重评分的 .6044625 是旧选择器重评分，不是新版最大值。本稿没有更改实验文件，只更正论文解释。
3. 新版 Node−Type=0，不沿用旧评分 +.2pp 或旧区间。开发 +1.61pp 与JSON文字结论冲突，采用数值字段。
4. v2服务时长3.0914秒由其detail求均值；不能抄v1的2.89秒。v2配对区间重新计算，不能抄v1区间。
5. 受控故障原恢复率及CI弃用，原始配对最终正确数可核对，不更改冻结实验脚本。
6. 原恢复矩阵成本占位零弃用，采用FULL_RESULTS原始记录的真实动作消耗。
7. 恢复率用Help/原失败数，净收益用(Help−Harm)/原失败数。两者均可报告，但不能混称。
