# FINAL_AUDITED_RESULTS

> 2026-09-27增量核查：HEAD已更新至47d30c0，但该提交只处理Frozen Single费用，未解除gold触发、Exact评分键及缓存路径阻断；其统一clean均值计费也与逐任务协议不符。最新五项材料见[第四章写作前审计包](chapter4_audit_20260927/第四章写作前审计包.md)。此前最小真实补调用已获用户授权，但必须先提交完整manifest并经检查，当前没有启动真实调用。Frozen目录内另一份同名文件的“全部通过”结论不作为本审计的有效性认证。

唯一审计裁决入口。日期2026-09-26，基础仓库提交`61f3655`，修复尚在当前工作区。历史总账为追溯记录；与本文件冲突时，不再作为最终引用许可。

**总体状态：BLOCKED_FOR_MANUSCRIPT_REWRITE。代码修复和部分重分析已完成，但未取得全部修复路径的真实输出，不能宣称全部hard blockers通过。第四章正文尚未改写。**

本轮只使用已有数据、离线算术和合成回归测试，未启动模型、未新增任务/算法/benchmark，未覆盖历史JSON。合成测试数字不能用于论文。读取的新分析值属于既有执行的重分析，不是独立确认。

## 1. 阻断项裁决

| 项目 | 本轮处理 | 结果资格 |
|---|---|---|
| Scheduler逐状态安全 | 撤回该主张，替换为逐状态差与regret | 旧轨迹上的算术通过；底层策略结果仍待修复重评 |
| Frozen intervention harm | seed23实际20/79=25.3% | 旧记录计数通过；不能误写28/79 |
| Frozen oracle种子混用 | 单seed与同seed对比；另列三seed并集统计 | 上界诊断；不作为部署实绩 |
| Exact键/初始故障/费用/跨配置污染 | 修复评分键、初始e注入、重复基础费用、清除故障与恢复命名空间 | 54组合仅1组合完整缓存重放；旧“空间坍缩”撤回 |
| 运行时gold触发 | 修复开发、Frozen、Exact、DV/FR及历史RD/FG分支 | gold改变不再改变测试执行轨迹；真实新路径输出不全 |
| Frozen缓存与计费 | 缓存按model+prompt不可变快照匹配；Single采用开发协议两次clean调用等价计费 | 原Frozen质量/资源不能直接宣称重新认证；新费用口径显式标注 |
| Workflow Scheduler56% | 找到入口门控TAT子集同值；仍缺生成脚本、fold、逐题预测、成本归属 | 从正式scheduler性能候选中排除，不伪称已确认无泄漏 |
| SD定义 | 本审计统一样本SD(ddof=1)，保留旧population表为历史 | 仅变描述统计，质量均值与逐任务结果不改 |

## 2. 实现修复及测试范围

- `audited_cache.py`用同目录request/response配对建立model+prompt哈希缓存；排除BUGGY目录、注入记录和失败响应；缓存值为快照，执行key不再作为可复用身份。避免旧key命中绕过当前提示与故障隔离。
- `exact_pareto.py`使用`ep`命名空间的新节点输出评分与检测；初始e经过故障覆盖；不再把未执行的基础r/v收费；每配置清除fault注册；恢复key包含配置与seed。下游刷新仍保留原冻结medium/coder规则，未增添算法。
- `frozen200_run.py`移除gold早退；Single持续故障不再以零成本计入新修复执行，而按开发面板已定义的“两次clean调用等价”计费。这是协议对齐的记账重分析，不伪装成两次新实测调用。
- `benchmark_run.py`、`multi_seed_run.py`、`fault_pool_extension.py`、`multidag_fullgraph.py`及`multidag_ablation.py`的Real验证触发不再依据gold早退。SM/Ideal对照的理想检测语义保留。
- `corrected_replay.py`修复RD/FG的gold触发，并使用整图V轮发生前的r/e状态进行决策，避免恢复后状态反过来决定是否恢复；输出另存审计目录。
- 已完成9项回归测试，涵盖新配置输出、gold独立性、e故障注入、跨配置清理、缓存快照、Single计费及冻结输出防覆盖。测试通过不等于实验结论自动通过。

复现测试：`python -m unittest r3_own_pool.static_dag_v0.test_audited_execution -v`。

## 3. 修复路径的真实输出覆盖

只读缓存重放命令：`python -m r3_own_pool.static_dag_v0.audit_cache_only_replay`。

来源3534个已执行model/prompt对。遇到缺失输出立即停止该组合，不填充错误、不跳过任务、不报告部分分母Q。完整清单见[覆盖记录](chapter4_audit_20260926/CACHE_REPLAY_COVERAGE.json)。

| 家族 | 组合数 | 完整重放 | 缺已有输出 |
|---|---:|---:|---:|
| Exact18配置×3seed | 54 | 1 | 53 |
| Frozen clean+3seed ×3臂 | 12 | 5 | 7 |

唯一完整Exact组合为medium_coder_none/20260923，Q=32/120=.266667，与旧记录该组合.3500不同。它是修复后缓存重分析的读出，不足以构建18配置新前沿；其余53组合没有完整新Q。

Frozen完整的5项是Single clean及3个fault seed，以及Static clean。Dynamic clean与3个fault seed、Static3个fault seed均存在缺失提示输出。因此不能生成一张声称“已修复确认”的Frozen三臂主表，也不能用旧结果替代缺失路径。

缓存first-match沿用已记录输出并固定来源顺序；它不消除模型会话非确定性，也不是新会话复现。

## 4. Local Recovery / Full Replay重分析

此前31%/48%/35%节省来自带gold早退的重分析，现在**不再作为最终数字**。修复V阶段触发后，从同一120题已有日志得到：

| 臂 | Q | mean tokens | adaptation calls | mean service latency(s) |
|---|---:|---:|---:|---:|
| RD local | 0.366667 | 2351.083 | 320 | 6.749260 |
| FG full | 0.333333 | 3506.758 | 644 | 10.945334 |

RD相对FG减少tokens 32.96%、适配调用50.31%、服务时延38.34%。注意适配调用不是总模型调用。

质量差为+3.33pp；RD对FG Help/Harm=4/0，双侧精确McNemar p=0.125000。未复用旧bootstrap CI，也未把不显著解释为等价/非劣。

这是**V阶段既有轨迹重分析**，上游执行记录保持历史状态，不是fresh confirmation。输出见[CORRECTED_ARMS](chapter4_audit_20260926/recovery_reanalysis/CORRECTED_ARMS.json)。原Static/Ideal/SM均值仍为.3917/.4250/.4167；不能据此将Ideal和部署规则混称。

主故障实验的clean Dynamic来自旧RD结果，因此该修复还影响其clean参照、质量保持率和下游候选选择。当前不可只替换恢复表而保持故障主表、HV和Scheduler全部结论不变。

## 5. Scheduler state-wise comparison / regret

以下仅为**历史轨迹**算术审计，不是修复后调度器验证。定义每状态的经验regret为该状态跨seed均值最好的固定候选Q(B)减去selector跨seed均值。

- 32-state selector平均Q(B)=.423350694（显示为.4234），与Single相同。
- 在30%故障/B3000，selector=.363888889，固定Dynamic=.375，regret=0.011111111，即1.1111pp。
- 32-state平均regret=0.000347222，即0.0347pp。其余31状态该定义下为0。
- 此定义与“先对每个留出seed取oracle再平均”不同；原state-oracle=.4239与selector之差不能替代上述regret。
- 不能将grid均值与Single持平写为逐状态不劣所有固定策略。Cost/Accuracy/所测Weighted Sum与selector持平；no_failure与full持平，不能说故障输入的独立增益得到证实。

## 6. Frozen旧记录计数与oracle裁决

这是原工件的算术一致性检查，不解除第3节的执行阻断。

seed20260923：Single clean正确110；fault后79存活、31受损。Dynamic在这两组正确59和15，在90个clean错误任务中正确7。所以损害为20/79=25.316%，恢复为15/31=48.387%。这是策略间结果差，不能全部归因为某次恢复动作的因果损害。

| seed | Single fault Q | Dynamic fault Q | 成功并集oracle | oracle−Single | oracle−Dynamic |
|---|---:|---:|---:|---:|---:|
| 20260923 | .395 | .405 | .505 | .110 | .100 |
| 20260924 | .380 | .405 | .520 | .140 | .115 |
| 20260925 | .415 | .400 | .520 | .105 | .120 |
| 三seed均值 | .396667 | .403333 | .515000 | .118333 | .111667 |

三seedoracle样本SD=.008660。该统计是已有记录并集的重汇总，不是新增实验、在线性能或600个独立任务。50.5%可保留为seed23诊断，但+10.8/+10.2pp混种子的写法撤回。

Frozen对Static的Help/Harm为18/1、23/1、28/1（各seed均为f30）；开发11/0、14/0、17/0则是单seed三个故障率。两组不能混为“所有实验zero-harm”。

## 7. 统一描述统计口径

以下统一采用样本SD(ddof=1)，仅重算既有记录的描述统计。数据有效性状态仍按前文，不因此升级。

| 开发故障率 | Single mean±SD | Static mean±SD | Dynamic mean±SD |
|---|---:|---:|---:|
| 10% | 0.497222±0.017347 | 0.325000±0.008333 | 0.405556±0.004811 |
| 20% | 0.438889±0.017347 | 0.305556±0.012729 | 0.411111±0.004811 |
| 30% | 0.363889±0.031549 | 0.286111±0.017347 | 0.405556±0.012729 |

Frozen原记录f30为Single .396667±.017559、Static .293333±.027538、Dynamic .403333±.002887。clean未独立重复，不报告人为零SD。跨seed误差不替代任务配对检验。

## 8. 56%与OOF统计

56%在`horizontal_comparison.json`与`selective_dag_oof_confirmation.json`的TAT子集一致。b039801只记录汇总，未补齐执行前特征、OOF fold、拟合流程、逐题决策和成本重建链。因此该数字**不作为正式Workflow Scheduler结果**，也不宣布该结果一定存在泄漏。

OOF原Help/Harm20/10按标准双侧精确McNemar应为.098737，而文件记.1975。保持原工件，审计中记录不一致；两者均不显著。Random28%/31.3%、Weighted成本口径仍缺生成链，不能择优拼接。

## 9. 写作许可与下一步

目前可以完成数据更正说明与冻结旧主张，**不能将第四章整体标为审计通过并重写成定稿**。特别是旧Exact前沿坍缩、Frozen独立部署确认、Scheduler逐点安全、56%正式性能不再获准引用。

尚缺的是修复路径的真实输出和OOF原始再现材料，不是更多写作解释。本轮没有运行额外模型；若仍坚持零新调用，则这些结果只能隔离，不能补齐。若要保留其核心结论，需要按已授权范围，在完整manifest提交并经检查后，补齐修复路径的缺失调用并重新审计；不增添模型、算法或benchmark。

用户指定的写作原则已冻结：结果→机制→含义；必要限定只保留一次；4.2联合配置；4.3.2执行范围控制；4.4给定候选上的多目标选择；HV细节附录；4.5适用性；4.6未来搜索。本轮不提前应用到尚未通过审计的正文。

机器可读读出见[FINAL_AUDIT_READOUT.json](chapter4_audit_20260926/FINAL_AUDIT_READOUT.json)。历史审计入口见[审计与重构规划](chapter4_audit_20260926/第四章审计与重构规划.md)，其中已被本轮纠正的统计/资格以本文件为准。
