# 第四章补充材料：执行策略与恢复诊断

本材料保存正文压缩后的既有数据及诊断。不同面板、oracle、故障种子和统计口径分别解释，不合并为新的实验。原路由表改用S4.1前缀；其他记录按其来源保留精度。不存在新增模型调用。

## S4.1 阶段分配、传播与路由诊断

以下保留原第四章中不受验证解析缺陷影响的节点／传播分析；跨节引用以重构后正文为准。它们属于不同阶段的开发或确认面板，不代替新的120题故障实验。



**阶段能力异质性。**在 100 任务、493 个主要节点的冻结确认面板上，三候选模型分别执行节点，以扩展执行器统一评分（表 S4.1-2）。推理与验证采用基准规定的条件输入，因此本节首先测量阶段能力，而不是完整链成功率。

表 S4.1-2 不同节点类型的条件化质量

| 类型 | 节点数 | medium | large | coder | 逐节点 Oracle |
| --- | --- | --- | --- | --- | --- |
| 抽取 | 193 | 0.3731 | 0.5959 | 0.3782 | 0.6943 |
| 推理 | 100 | 0.3100 | 0.2500 | 0.3100 | 0.4100 |
| 验证 | 200 | 0.5200 | 0.4550 | 0.5900 | 0.6200 |

large 在抽取上占优，medium 与 coder 的推理均值并列最高，coder 的验证质量最高。类型内 Oracle 相对最佳固定模型分别存在约 9.84、10.00 和 3.00 个百分点的差距。模型优势因阶段而异：同一模型池中不存在"所有阶段都最优"的单一模型，这为节点级选择提供了经验依据，也构成中心命题中"阶段能力匹配"条件的度量基础。Oracle 使用事后标签，不能直接证明这些机会可被输入特征预测——该问题由下文的冻结确认与残差路由诊断检验。

**节点级调度与查询级路由。** 将上述能力差异转化为分配问题：稳定收益来自阶段/类型粒度，还是来自强实例级学习器。节点路由相对查询路由的条件化节点质量提高 6.90 个百分点，并减少记录中的 token 与观测服务时延（表 S4.1-3）。

表 S4.1-3 冻结路由与类型先验比较

| 方法 | 平均节点质量 | 每任务 tokens | 每任务观测服务时延总和（秒） |
| --- | --- | --- | --- |
| Always Large | 0.4686 | 4,991.02 | 11.71 |
| 查询路由 | 0.4665 | 4,985.33 | 10.19 |
| 类型先验 | 0.5355 | 未独立汇总 | 未独立汇总 |
| 冻结节点路由 | 0.5355 | 4,856.43 | 7.79 |
| 新版矩阵逐节点 Oracle | 0.6065 | 不作部署比较 | 不作部署比较 |

以 Always Large 为参考，其条件化节点 GAP Recovery 为 (0.5355−0.4686)/(0.6065−0.4686)，约 48.5%，即接近一半。这里的"接近一半"是差距恢复比例，不是任务准确率。**类型先验与节点路由的均值相同——主要收益来自阶段粒度，而非问题表示的额外学习能力**；节点路由相对查询路由差异为正，而相对类型先验区间包含零。原结果中 0.6045 是旧 Oracle 选择在新评分器下的重评分；本表采用已留档复核的新版逐节点最大值 0.6065，不混用两者计算差距。

**能力机会的实现限制。** 剩余差距能否由实例级信号稳定利用？剩余差距路由以 large 为强默认，使用 900 任务开发数据拟合两阶段选择器，固定阈值 τ=0.5 后分别评价较小 Conf-200 与较大 Conf-500（表 S4.1-4）。这里的 Oracle 仅取三条同模型传播链，与下文九组合 Oracle 不同。

表 S4.1-4 冻结两阶段路由的确认结果

| 指标 | Conf-200 | Conf-500 |
| --- | --- | --- |
| 任务数 | 200 | 500 |
| large 默认质量 | 0.1900 | 0.1840 |
| 两阶段路由质量 | 0.2000 | 0.1780 |
| 同模型链 Oracle | 0.2350 | 0.2380 |
| 质量差异 | +1.00 个百分点 | −0.60 个百分点 |
| 质量差异 95% 区间 | [0.00,2.50] 个百分点 | [−1.60,0.20] 个百分点 |
| GAP Recovery | +22.22% | −11.11% |
| 切换次数 | 4 | 22 |
| Help／Harm | 2／0 | 1／4 |
| McNemar 精确检验 p | 0.500 | 0.375 |

较小确认集出现正向信号，但差异不显著；在更大确认集上未复现，点估计转负且同样不显著。因此不能将 +22.22% 作为稳定主结果，也不能反向断言剩余差距完全不可学习。在 Conf-200 上，能力画像路由与成对路由分别切换 135 和 137 次，质量为 0.16 和 0.15，低于默认的 0.19；两阶段策略只切换 4 次。该比较提示无充分依据的覆盖会引入损害。Conf-500 的机制分析在 34 个仅 large 占优任务与 27 个替代者占优任务上，触发分数的诊断 AUC 为 0.458：单模型成功可预测、相对优劣可排序以及最终路由有净收益，是不同层次的问题。

低覆盖率选择为何相对安全？将 900 开发任务、200 和 500 个已分析确认任务合并为 1,600 题开发语料，进行任务级五折预测与事后风险—覆盖率分析（表 S4.1-5）。运行时特征来自 large 的实际抽取和推理输出；这一评价不能再称为独立确认，也不等同于零执行成本的到达时路由。

表 S4.1-5 开发语料上的事后风险—覆盖率曲线

| 覆盖率 | 覆盖默认次数 | Help | Harm | 净改善数 | GAP Recovery |
| --- | --- | --- | --- | --- | --- |
| 2% | 32 | 2 | 0 | +2 | +2.47% |
| 5% | 80 | 6 | 0 | +6 | +7.41% |
| 10% | 160 | 8 | 1 | +7 | +8.64% |
| 15% | 240 | 8 | 6 | +2 | +2.47% |
| 30% | 480 | 12 | 15 | −3 | −3.70% |
| 50% | 800 | 22 | 39 | −17 | −20.99% |

在该分析中，5%—10% 覆盖具有正净收益且损害较少；扩大覆盖后，新增有害覆盖逐渐抵消帮助。它支持限制干预范围的机制动机，不证明 5%—10% 是新任务上的通用安全区间，更不能在看到曲线后将这些档位称为事先冻结阈值。既有流程在折分前进行全体无标签特征标准化，且覆盖档位为事后解释，因此本节保留开发层级。

900 任务画像使推理模型消费同模型实际抽取结果，测量传播链能力（表 S4.1-6 与表 S4.1-7）。任务级五折交叉验证保持同任务节点同折。

表 S4.1-6 传播画像中的预测与路由结果

| 指标 | medium | large | coder |
| --- | --- | --- | --- |
| 单模型成功预测 ROC-AUC | 0.7511 | 0.7880 | 0.8391 |

表 S4.1-7 传播画像中的路由质量

| 传播路由策略 | 最终质量 |
| --- | --- |
| 最佳固定模型／类型先验 | 0.1800 |
| 查询路由 | 0.1778 |
| 能力画像路由 | 0.1789 |
| 同模型链 Oracle | 0.2300 |

单模型成功存在可预测信号，但能力画像路由没有超过类型先验，差异区间 [−0.0111,0.0089] 包含零。900 个任务中，693 个三模型链均错、50 个均对、157 个存在模型间结果差异；大量共同失败和共同成功会抬高整体最优命中率，判断可路由性应关注模型表现不同的任务。

**条件能力不等于传播能力**。标准事实推理基准中的最佳固定质量为 0.31、逐任务推理 Oracle 为 0.41，存在 10 个百分点的条件空间；传播画像中最佳同模型链为 0.18、Oracle 为 0.23，只保留 5 个百分点的整链选择空间。但这两组数据的任务集和估计对象不同，不能把差值解释为严格配对的"抽取噪声损失"。零调用审计（证据编号见 FINAL_CLAIM_AUDIT）给出各面板传播 headroom：900 题开发集 5.00pp、Conf-200 4.50pp、Conf-500 5.40pp、合并 1,600 题 5.06pp；共同失败占比 77.0%／76.5%／76.2%／76.7%。本文统一引用上述冻结审计值，不采用无冻结来源的传播差距。由此，条件能力与传播能力必须分开估计：前者揭示理想输入下的能力，后者反映整个输入生成过程与下游执行的联合作用——这是"节点接口表达能力"条件的第一处直接证据。

在能力画像的 200 任务子集上，实际执行三个抽取模型与三个推理模型的九种组合，推理者消费对应抽取者输出（表 S4.1-8）。该子集用于开发机制分析，不是 Conf-200 确认集。

表 S4.1-8 跨模型传播矩阵

| 抽取模型／推理模型 | medium | large | coder |
| --- | --- | --- | --- |
| medium | 10.0% | 9.5% | 9.5% |
| large | 20.0% | 18.0% | 20.5% |
| coder | 13.0% | 11.5% | 11.0% |

该九组合空间的有限候选精确上界汇总于表 S4.1-9。保持推理者 medium 不变，将抽取者从 medium 换成 large，质量由 10.0% 提高至 20.0%；保持推理者 coder 不变，对应变化为 11.0% 至 20.5%。固定 large 抽取后，medium 和 coder 的推理结果分别高于 large 推理的 18.0%。这表明同模型链可能因抽取弱项而掩盖下游优势，独立分配阶段模型能够解除这种绑定。上述比较支持阶段互补的机制解释，但当前未据该汇总表宣称各点估计差异均达到统计显著；large 抽取均值更好也不意味着它在每个任务上都是最优来源。

表 S4.1-9 枚举组合空间的上界与差距

| 对象 | 质量 | 与精确 Oracle 的距离 |
| --- | --- | --- |
| Always Large：E_large→R_large | 18.0% | 12.5 个百分点 |
| 最佳固定组合：E_large→R_coder | 20.5% | 10.0 个百分点 |
| 枚举 3×3 空间内精确 Oracle | 30.5% | 0 |

最佳固定跨模型组合相对 Always Large 增加 2.5 个百分点，恢复对应 12.5 个百分点 Oracle 差距的 20.0%。剩余 10.0 个百分点表示在这九种记录中仍有任务特定机会，不表示当前路由器一定能够预测它们。该上界的完整名称是"枚举 3×3 模型组合空间内的精确 Oracle"（Exact Oracle within the enumerated 3×3 model-composition space），它不包含任意恢复序列、图结构、提示变体或动态预算分支；有限组合穷举不能被表述为完整 Dynamic DAG 的全局最优解。

异构阶段能力真实存在，节点粒度能够更充分利用这些差异；但 Routing Opportunity ≠ Learnable Routing Signal，Conditional Capability ≠ Propagated Capability。


## S4.2 故障种子与难度分层

来源：`adaptive_benchmark/MULTI_SEED_REPORT.md`。

### Multi-seed fault injection (3 seeds: 20260923/24/25)

Mean +/- std over seeds (population std). Same procedure, pools and policies; calls reused at temperature 0; only new prompts executed for real.

| Fault rate | Single LLM (retry) | Static | Dynamic | dQ(Dyn-Static) | dQ(Dyn-Single) | Dynamic recovery | Static survival |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10% | 0.4972±0.0142 | 0.3361±0.0142 | 0.4111±0.0039 | +0.0750±0.0136 | -0.0861±0.0104 | 0.39±0.10 | 0.22±0.08 |
| 20% | 0.4389±0.0142 | 0.3250±0.0236 | 0.4139±0.0079 | +0.0889±0.0208 | -0.0250±0.0068 | 0.42±0.03 | 0.25±0.09 |
| 30% | 0.3639±0.0258 | 0.3111±0.0322 | 0.4083±0.0136 | +0.0972±0.0375 | +0.0444±0.0142 | 0.44±0.01 | 0.29±0.10 |

#### Hard subset (46 tasks)

| Fault rate | Single LLM | Static | Dynamic |
|---:|---:|---:|---:|
| 10% | 0.2681±0.0102 | 0.1957±0.0177 | 0.2754±0.0102 |
| 20% | 0.2174±0.0355 | 0.1667±0.0410 | 0.2754±0.0102 |
| 30% | 0.1812±0.0410 | 0.1667±0.0410 | 0.2681±0.0205 |

来源：`adaptive_benchmark/verifier_ablation/SUBSET_REPORT.md`。

### Hard-Subset Evaluation & Dynamic+Verifier Ablation

Split (pre-execution, frozen): Easy = 1 operator (74 tasks); Hard = >=2 operators (46 tasks).

#### Clean scenario per subset

| Method | overall | easy | hard |
|---|---:|---:|---:|
| router | 0.5500 | 0.7027 | 0.3043 |
| static | 0.3500 | 0.4324 | 0.2174 |
| dynamic | 0.4000 | 0.4595 | 0.3043 |
| dynamic_verifier | 0.4000 | 0.4595 | 0.3043 |

#### Fault scenarios per subset (accuracy)

| Scenario | Method | overall | easy | hard |
|---|---|---:|---:|---:|
| fault 20% | router | 0.4250 | 0.5811 | 0.1739 |
| fault 20% | static | 0.2917 | 0.4054 | 0.1087 |
| fault 20% | dynamic | 0.4083 | 0.5000 | 0.2609 |
| fault 30% | router | 0.3500 | 0.4730 | 0.1522 |
| fault 30% | static | 0.2667 | 0.3649 | 0.1087 |
| fault 30% | dynamic | 0.4083 | 0.4865 | 0.2826 |

#### Dynamic + Verifier ablation (clean)

| Method | Accuracy | tokens/task | latency s |
|---|---:|---:|---:|
| static | 0.3500 | 1503 | 4.63 |
| dynamic | 0.4000 | 2324 | 6.69 |
| dynamic_verifier | 0.4000 | 2727 | 7.06 |

DV vs Dynamic paired: dQ=0.0, help/harm=1/1, McNemar p=1.0.
Verifier signal stats: {"fired": 34, "both_exec": 104, "correct_initial": 34, "wrong_initial": 71, "new_fired": 28}.
DV extra calls vs Dynamic: 146.


## S4.3 恢复归因

下列链条用于区分机制条件，不解释为独立概率乘积。类型级故障归因为种子20260923，不能混用三种子均值。

### Recovery Attribution Analysis (paper Table 3)

Detection → Recovery action → Recovery outcome；各行描述不同条件，不拟合乘积模型。

#### A. Clean scenario: initially-wrong tasks under Dynamic (corrected RD arm)

N = 78 initially-wrong tasks (fixed parser); recovery = task ends correct under RD.

| Failure type (primary, topological) | n | node detection | any detection | recovery success |
|---|---:|---:|---:|---:|
| evidence (parse/empty) | 44 | 100% | 100% | 16% (7/44) |
| evidence (wrong values) | 8 | 0% | 100% | 12% (1/8) |
| execution (r) | 4 | 100% | 100% | 0% (0/4) |
| reasoning (r) | 20 | 0% | 100% | 0% (0/20) |
| verification (v) | 2 | 100% | 100% | 0% (0/2) |

#### B. Fault scenarios: injected faults, Dynamic recovery vs Static survival

##### fault 10%
| Faulted node type | n | Dynamic recovery | Static survival |
|---|---:|---:|---:|
| evidence (injected e) | 7 | 29% | 0% |
| execution (injected r) | 4 | 75% | 50% |
| verification (injected v) | 1 | 100% | 0% |

##### fault 20%
| Faulted node type | n | Dynamic recovery | Static survival |
|---|---:|---:|---:|
| execution (injected r) | 9 | 33% | 22% |
| evidence (injected e) | 10 | 50% | 10% |
| verification (injected v) | 5 | 40% | 0% |

##### fault 30%
| Faulted node type | n | Dynamic recovery | Static survival |
|---|---:|---:|---:|
| execution (injected r) | 11 | 55% | 45% |
| evidence (injected e) | 15 | 40% | 7% |
| verification (injected v) | 10 | 40% | 0% |

#### C. Verifier set: reasoning errors made detectable

signal fired 34 times; true reasoning errors 28 (detection precision 82%); repaired 7 (repair rate 21%).



## S4.4 Adaptive Decomposition事后诊断

该分析复用已执行输出，未新增模型调用。oracle按gold运算符数将46个Hard任务交给Dynamic、74个Easy任务交给Single；它不是逐任务取正确输出的最优oracle，也不是可部署难度估计器。

| 策略 | Clean正确率 | 平均tokens |
| --- | ---: | ---: |
| Single-all | 0.5500 | 602.5 |
| Static-all | 0.3500 | 1503 |
| Dynamic-all | 0.4000 | 2324 |
| Adaptive（gold难度） | 0.5500 | 1308 |
| 问题中至少两个数值 | 0.4083 | 1980 |
| 问题长度不小于中位数14 | 0.4917 | 1528 |
| 表格行数不小于中位数8 | 0.4667 | 1552 |

Single成本采用多目标原始汇总602.5，避免不同报告整数舍入602／603带来的表面冲突。Clean Hard中Single、Dynamic和Dynamic+Verifier均为0.3043，Dynamic-Ideal为0.3261。这一特定分流不提升clean质量，不排除其他尚未验证的候选组合。

| 故障率 | Single-all | Dynamic-all | Adaptive（gold难度） | 当场景最佳规则点估计 |
| --- | ---: | ---: | ---: | ---: |
| 10% | 0.4972±0.0173 | 0.4111±0.0048 | 0.5000±0.0167 | 0.4750±0.0167（长度） |
| 20% | 0.4389±0.0173 | 0.4139±0.0096 | 0.4611±0.0048 | 0.4361±0.0293（长度） |
| 30% | 0.3639±0.0315 | 0.4083±0.0167 | 0.3972±0.0210 | 0.3944±0.0173（数值数） |

误差为三个种子的样本标准差。“最佳规则”按已观察场景事后选出，不代表部署时知道最优规则。20%下的组合优势未被表述为统计确证；30%时gold难度组合低于全量Dynamic，表明难度标签不能替代故障状态。来源：`adaptive_benchmark/ADAPTIVE_SIMULATION.md`。

## S4.5 历史恢复与复用面板

两节点链48题面板Static为25/48（52.08%），Dynamic两个版本均为26/48（54.17%），第二版差值约2.08pp、区间[0,6.25]。独立250题确认面板Static为103/250（41.2%）、Dynamic为110/250（44.0%），差值2.8pp、95%区间[−0.8,6.4]、McNemar p=0.167、Help/Harm=13/6。两个面板沿用理想失败检测协议，不作为部署检测下的独立确认；方向一致但未确证质量收益。

Graph Forest在20个修改型追问中复用40个抽取节点，新执行40次调用，相对80次逻辑重执行需求减少50%，记录token减少91.4%。19/20流程可执行并响应修改，但验证器接受为0/20。该结果仅支持特定多轮工作负载的复用机制，不证明95%答案正确率，也不并入单轮恢复效率。

固定恢复集合为116节点、96任务。再次调用、模型切换、重新取证和局部分解分别恢复2、2、5、2个节点，集合有重叠，并集8/116。预算档位(500 tokens,1秒)、(1000,2)、(2000,3)、(3000,3)、无限下顺序策略恢复率为2.59%、3.45%、4.31%、5.17%、6.90%，同预算动作oracle为3.45%、4.31%、5.17%、5.17%、6.90%。这是已知实际消耗和离线成功停止的回放，不是在线预算保证。

## S4.6 数据与统计来源

- 核心故障：`../static_dag_v0/adaptive_benchmark/MULTI_SEED_REPORT.md`。
- 多目标表与预算曲线：`../static_dag_v0/adaptive_benchmark/MULTIOBJECTIVE_TRADEOFF.json`；表4-6直接取既有汇总，表4-8保留已生成表格，未重跑分析。
- 修正恢复对照：`../static_dag_v0/corrected_replay/CORRECTED_REPORT.md`；解析缺陷说明见同目录`BUG_REPORT.md`。
- 检测与归因：上述修正报告及`adaptive_benchmark/RECOVERY_ATTRIBUTION.md`；Verifier见`adaptive_benchmark/verifier_ablation/SUBSET_REPORT.md`。
- FLARE-DAG：`../static_dag_v0/frp_dag/`冻结记录；MC→LC上界与实际LC→MC回落分开解释。
- 基础与跨域：原实验章及`FINAL_CLAIM_AUDIT.md`中相应基础／跨域条目。该审计文件仍含已撤回的历史四节点主张，不作为修正恢复结果来源；后者以`corrected_replay/CORRECTED_REPORT.md`为准。被解析缺陷推翻的结果不转入本补充材料。
