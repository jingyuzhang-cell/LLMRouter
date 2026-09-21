# 最终论断与一致性审计

审计范围：2026-09-21 最终整合正文。仅整合既有数据和已留档统计，未新增实验、模型调用、阈值选择或方法机制。章标题全部中文。用户指定的 nature-writing 技能在本会话未找到可用文件，未声称已应用该技能。

## 一、可以保留的核心结论

1. 模型阶段优势不同，类型化节点分配具有经验价值；节点确认中相对查询路由约 +6.90pp，主要增益由类型先验解释。
2. 实际上游来源影响下游表现；固定推理者更换抽取者的跨模型矩阵支持解除阶段绑定。该证据不等于严格量化所有抽取噪声的因果损失。
3. 单模型成功存在可预测信号，但当前画像路由与剩余差距选择器未稳定转化为净收益。
4. 九组合内精确 Oracle=30.5%，Always Large=18.0%，最佳固定组合=20.5%；三者仅描述枚举空间。
5. 固定动作在真实失败集合上的并集覆盖低，局部重规划没有新增覆盖。模型与动作覆盖是该困难集合的重要限制之一。
6. 历史图复用在特定修改型追问中减少调用与 tokens，不证明最终正确性。

## 二、必须带限定条件的结论

| 论断 | 必须保留的限定 |
| --- | --- |
| 动态质量正向变化 | 48 任务；理想失败检测；已分析面板；区间含零；250 任务冻结一次性确认方向复现（+2.8pp，CI 仍含零，情形二） |
| 多节点 DAG 选择性动态适应显著优于静态 | +20.0pp，CI [11.7,28.3]；单面板 120 任务、table-text 混合源；933 适配调用全部限于后代闭包、分支隔离零违例、预算违规 0；消融：主要增益来自升级 large 动作（Static-Matched 35.0%），策略超出目标选择仅 +1.7pp（ns） |
| 动态收益不依赖 gold 失败信号 | RealDetector 保留率 91.7% CI [77.8,100]；机制上部分依赖尾节点一致性检查近乎全触发的退化特性；r 值错误检测不到但本面板代价小 |
| 动态第二版降低损害 | 观察到 Harm 从 1 到 0，Help 也从 2 到 1；非零风险保证 |
| 选择性路由较安全 | 当前比较支持动机；Conf-500 未复现收益；不能保证泛化 |
| 5%—10% 覆盖有正净收益 | 合并 1,600 题后的开发/CV/事后分析；不是新确认 |
| 条件 GAP 接近一半被恢复 | 节点评分、新矩阵 Oracle、100 任务；非整链成功率 |
| 预算控制有效 | 回放事先知道实际开销且用离线成功停止；仅可行性分析 |
| 能力覆盖限制恢复 | 固定池、动作、提示与被选择的困难子集；不是唯一普遍原因 |
| 证据齐备仍可能失败 | 25 条探索性记录；完整 D0–D4 配对汇总未定位 |

## 三、禁止回流的结论

- Dynamic 显著优于 Static，或在质量、成本、延迟上全面占优。
- Two-stage 的 +22.2% 是稳定主结果；或者剩余差距完全不可学习。
- 1,600 题风险曲线是独立测试；低覆盖档位是预先验证的通用阈值。
- 精确 Oracle 是完整 Dynamic DAG 的全局最优；它覆盖任意拓扑或恢复序列。
- 类型内所有模型的优势均不相同，或表示学习显著优于类型先验。
- 19/20 图流程响应等于 95% 最终正确率。
- 原 148 节点中 34 次再次成功均为救回；32 个原本正确节点不得进入真失败分母。
- Local Replan 是成功组件；当前证据为 NO-GO。
- 旧分解对照数字（MH +14.0pp／TAT-QA −9.38pp）作为结论引用；严格配对基准已给出替代值并撤回 +14.0pp。
- 所有任务唯一瓶颈是能力不足，或调度在任何未来模型池都无效。

## 四、最终关键数字与来源

下列路径相对项目根目录 /root/r3_own_pool。区间沿用冻结结果或此前已保存审计，并非本轮新增实验。

| 面板／指标 | 最终值 | 依据 |
| --- | --- | --- |
| 节点主面板 | 100 任务、493 节点 | `paper_method_feedback_aware_dag/重构初稿_20260920/DERIVED_EVIDENCE.json` |
| 查询／节点／类型先验 | .466531／.535497／.535497 | 同上 |
| 节点减查询及区间 | +6.8966pp；[3.4413,10.6122]pp | 同上 |
| 节点减类型先验区间 | [−1.2097,1.2121]pp | 同上 |
| Always Large／新矩阵节点 Oracle | .468560／.606491 | 同上；旧选择重评分 .604463 不作新矩阵最大值 |
| 条件节点 GAP Recovery | 48.53% | 上述同面板数字的算术比例，33/68 |
| 900 题单模型 AUC | .7511／.7880／.8391 | `static_dag_v0/capability_profiling/CAPABILITY_ANALYSIS.json` |
| 900 题固定／能力路由／Oracle | .1800／.1789／.2300 | 同上 |
| 跨模型矩阵 | [[.10,.095,.095],[.20,.18,.205],[.13,.115,.11]] | `static_dag_v0/cross_model_matrix/CROSS_MODEL_RESULTS.json` |
| 九组合 Oracle／Always Large／Best Fixed | .305／.180／.205 | `static_dag_v0/exact_optimality_audit/AUDIT.json` |
| Oracle GAP／最佳固定距上界 | 12.5pp／10.0pp | 同上 |
| Conf-200 默认／两阶段／GR | .19／.20／+22.22% | `static_dag_v0/confirmation_200/CONF_RESULTS.json`、`static_dag_v0/confirmation_200/STAT_AUDIT.json` |
| Conf-500 默认／两阶段／GR | .184／.178／−11.11% | `static_dag_v0/confirmation_500/CONF500_RESULTS.json` |
| 5%覆盖 Help/Harm/GR | 6／0／+7.41% | `static_dag_v0/gap_learnability_analysis/GAP_LEARNABILITY.json` |
| 10%覆盖 Help/Harm/GR | 8／1／+8.64% | 同上；开发/CV/事后 |
| 静态／动态第二版 | 25/48／26/48；差异区间[0,6.25]pp | `static_dag_v0/live_static_dynamic/LIVE_ANALYSIS.json`、`static_dag_v0/dynamic_v2_test/TEST_ANALYSIS.json`、前述留档审计 |
| 真实失败／恢复并集 | 116 节点／8 节点（6.90%） | `static_dag_v0/recovery_matrix_v2/full_4983983/ORIG_CORRECTNESS.json`、`static_dag_v0/recovery_matrix_v2/full_4983983/SEQUENTIAL_RECOVERY.json` |
| 局部重规划新增覆盖 | 0；NO-GO | `static_dag_v0/recovery_matrix_v2/dev_replan_pilot/DEV_ANALYSIS.json` |
| 无预算限制的恢复上限 | 6.90% | `static_dag_v0/budget_surface/BUDGET_SURFACE.json` |
| 图复用／调用减少／token减少 | 50%／50%／91.4% | `static_dag_v0/graph_forest_v1/RESULTS.json` |

## 五、已纠正的口径与旧结果风险

1. `exact_oracle/EXACT_ORACLE.json` 与 `exact_optimality/EXACT_OPTIMALITY.json` 中旧基线索引曾把 Always Large 记为 .095。本文采用最终 AUDIT 的 .180，不使用旧 .210 GAP 及派生比例。
2. 条件节点 Oracle 采用既有留档审计的逐节点最大值 .606491；.604463 是旧选择在新评分下的结果。48.53% 的恢复比例与前者一致。
3. Conf-200 与跨模型 200 题不混用；1600 合并后不再保持确认属性。
4. 旧 formal E2E 的均值、历史成功率和新 48 题 live 结果不拼表。不把 formal replay 视为实际错误传播。
5. 真实失败以原最终答案错误为准，区别于中间缺陷分类；116 不替代原协议池 148 的历史规模。
6. 动态调用真实发生与失败判定使用答案可以同时成立；正文明确披露该限制。
7. tokens、服务时长、墙钟延迟和货币成本不互换；缺测项不补零。

## 六、尚未核实、未进入正式数值结论的内容

- **传播后 reasoning headroom≈4.1pp：待来源。** 找到条件推理 .41−.31=10pp，以及传播整链 .23−.18=5pp，但它们不是同一估计量。不得据此推导或替代 4.1pp。
- **完整 D0–D4／Gold Evidence 诊断：待配对评分汇总。** 已找到 `static_dag_v0/structure_aware_experiment/dev_structured_results.json`、`static_dag_v0/structure_aware_experiment/STRUCT_REASONING_RESULTS.json` 和原始调用，但完整输入—输出—评分配对未定位。25 条覆盖记录和零正确列表只作探索性描述；不得将另一节点基准的 31% 作为该子集的金标准证据成功率。

以上待核项已向用户询问来源。它们不妨碍完成其余章节，但在来源补齐前不能将稿件称为所有指定诊断均已获验证的最终投稿版。

## 七、一致性检查结论

本轮已核对章节术语、面板层级、Oracle 候选空间、关键比例和显著性措辞。方法采用用户指定十节结构，实验按八个研究问题组织；讨论和摘要不突出小确认集收益。自动文档检查另见 CONSISTENCY_CHECKS.json；它检查格式及可计算关系，不能替代上述人工证据判断。冻结源文件的 SHA-256 清单见 FINAL_SOURCE_MANIFEST.json。

## 八、待核项闭环（2026-09-21，零调用审计）

第六节两项待核来源已按"从冻结输出零调用重算"原则闭环，结果以审计 JSON 为准：

1. **传播 headroom（原"4.1pp"）**：`static_dag_v0/propagated_row_oracle_audit/REASONER_ROW_ORACLE_AUDIT.json`。以冻结加载器与冻结评分器逐任务重算三条同模型传播链：headroom = 5.00pp（900 题开发集）／4.50pp（Conf-200）／5.40pp（Conf-500）／5.06pp（合并 1,600）；共同失败 77.0%／76.5%／76.2%／76.7%。正文已统一引用审计值；"传播后 4.1pp" 查无冻结来源，作废。原正文 5pp／77% 表述与审计一致，保留。
2. **D0–D4／Gold Evidence 配对汇总**：`static_dag_v0/structure_aware_experiment/EVIDENCE_DIAGNOSIS_AUDIT.json`。结论收窄：(i) B 臂 25 个应答全部可解析、重打分 Q=0/25 与保存零向量一致；早期"100% 操作数覆盖"不可复现（现版本化代码重算 top-30 覆盖 0/25、全量事实 14/25；原生成代码未版本化），该覆盖数字不再引用；(ii) D2–D4 仅应答冻结、配对输入缺失，百分比不可重算、不予报告；(iii) D0、D1、C_Gold 无冻结工件，口头数字（0%、4%）无审计支持；(iv) 补充首评 ERv2 100 个失败任务的已冻结调用：S0/S1/S2/S3 = 8%/8%/5%/8%（探索性，非预注册）。

两项均已写入正文（5.2 传播 headroom 段、5.8.3 证据诊断段）。稿件中不再存在"凭记忆引用且无冻结来源"的数字。

3. **Dynamic v2 大规模确认（2026-09-21 运行完成）**：`static_dag_v0/dynamic_v2_confirm_250/`。250 个 TAT-QA train split 全新任务（选择规则与清单在任何调用前冻结并提交，commit 020b15d；与全部历史工件零重叠），策略与 48 任务面板逐字一致，一次性运行 852 次调用。结果：静态 41.2%（103/250）、动态 44.0%（110/250），配对 ΔQ=+2.8pp，95% CI [−0.8,+6.4]，McNemar b=13/c=6 p=0.167，Help/Harm 13/6，ΔC=−12.8 tokens，预算违规 0。预注册三情形判定：**情形二**。正文已更新（摘要、5.7、6.3、7）。任何后续修改策略或阈值并在同一数据集上重跑的行为都被禁止。

4. **多节点真实 DAG 实验（2026-09-21 运行完成）**：`static_dag_v0/multidag_dynamic_120/`。120 个 TAT-QA train split 全新任务（answer_from=table-text，策略与任务清单在任何调用前冻结并提交，commit 7d6e6c1），4 节点 DAG（e1 表格抽取 + e2 文本抽取 → r 汇总 → v 校验），一次性运行 1413 次调用。结果：静态 16.7%、动态 36.7%，配对 ΔQ=+20.0pp，95% CI [11.7,28.3]，McNemar b=28/c=4 p≈1.9×10⁻⁵，Help/Harm 28/4，ΔC=−90 tokens，预算违规 0；选择性更新审计：933 次适配调用全部限于失败节点或其声明后代（越界 0），分支隔离 134 例检查零违例。预注册判定：**情形一（confirmed）**。边界：理想失败检测、单域、动态收益部分来自 r/v 升级 large。正文已更新（摘要、5.7、6.3、7）。

5. **多节点消融与真实检测臂（2026-09-21 运行完成）**：`static_dag_v0/multidag_ablation_120/`（预注册 commit 7a197f2，830 次新调用）。Static-Matched（静态语义+动态升级目标）Q=35.0%，策略超出目标选择 +1.7pp（CI [−4.2,+7.5]，p=0.77，不显著）；Dynamic-RealDetector（全部署信号检测，无 gold）Q=35.0%，增益保留率 91.7%（CI [77.8%,100%]），与理想臂无显著差异（b=2/c=0，p=0.5），成本 2,459.5 tokens 更低。正文已更新（摘要、5.7、6.3、7）。禁止在这批任务上再做任何阈值或策略修改。

6. **严格配对分解基准（2026-09-21 运行完成）**：`static_dag_v0/decomposition_benchmark/paired_run/RESULTS.json`（协议 FROZEN_BEFORE_EXECUTION，commit 5748b63/872d7fb；300 任务三臂一次统一会话；抽取失败即判失败）。对比 A（拆分本身）：MH +6.0pp CI [−2,+14] 不显著、TAT-QA −21.0pp CI [−28.5,−13.5] p≈4×10⁻⁷、总体 −12.0pp 显著；对比 B（异构分工）：总体 +5.0pp CI [+1.3,+8.7] p=0.014（TAT-QA +8.5pp 显著、MH −2pp 不显著）。复杂度分层（表 5-7 对照）：TAT-QA −27.1/+21.1/+50.0pp 随步数单调上升（3 步 n=19、4+ 步 n=4，仅作描述）；MultiHiertt 无此趋势。总体 Mono-L 38.7% 仍高于 DAG-L/M 31.7%：异构分工缓解但未完全抵消分解损耗，正文必须保留该限定句。**旧 +14.0pp 撤回**；正文（摘要、2.2、5.3/5.8、6.3）已更新。禁止再引用旧数字作为分解收益。

7. **Math500 跨域六臂（2026-09-21 运行完成；定位为探索性诊断）**：`static_dag_v0/cross_domain_math/`（协议 commit 87a14f5/b9bfb44/66122d1，1751 次调用，运行时不使用 gold）。面板从 398 个纯数值可归一化任务中冻结、排除了 102 个符号型任务（外部 schema 审计 d4e99b9 指出该排除可避免），故按探索性结果报告；正式主表为分层 100 协议（d53c08d，FROZEN_BEFORE_EXECUTION）；该正式面板已于同日运行完成并复现塌缩（`p3_xdomain/math_run/RESULTS.json`：large 54% / 查询 50% / medium 49% / DAG 13—16%；静态对 large −39.0pp CI [−50,−27]；动态对静态 +1.0pp b=1/c=0；两类分解接口族均塌缩；求解节点 32% → 校验后 15%）。5.9/5.10/6.9/摘要已按"已确认跨域对照"升级。结果：large 单体 63.5% / 查询路由 48.0% / medium 37.0% / 三个 DAG 臂 20.5%—21.5%（有限候选 Oracle 69.5%）。RQ1/RQ2/RQ3 全部否定（详见 MATH_ANALYSIS.json）；机制定位为接口表达力不足（求解值正确率 11.5%）。正文已更新（摘要、5.9、6.9）。该负结果禁止任何事后调整；引用时必须同时给出接口条件结论。

8. **MBPP 代码域正式六臂（2026-09-21 运行完成）**：`static_dag_v0/p3_xdomain/mbpp_run/RESULTS.json`（协议 d53c08d FROZEN_BEFORE_EXECUTION；100 任务，确定性排除近重复与辅助函数依赖任务，与历史 14,650 条查询零重叠；运行时只读单元测试/运行时错误，不读参考实现）。结果：medium 68% / large 76% / 查询路由 71% / 阶段分配 73% / 静态 74% / **动态真实 80%**（有限候选 Oracle 87%）。动态对静态 +6.0pp，CI [+1.0,+12.0]，McNemar p=0.070（两检验分歧如实报告）；恢复率 7/26=26.9%；Help/Harm 7/1；代价 +95.7 tokens、预算违规 22/100。其余对比（阶段 vs 查询 +2pp、静态 vs large −2pp、动态 vs large +4pp）均不显著。正文（摘要、5.10、6.9）已更新；引用时必须同时给出成本与预算越限；表述规范冻结为"提升 6.0pp、bootstrap CI [+1,+12] 不含零、exact McNemar p=0.070 未达 0.05 显著"——禁止写"显著优于"；跨域对照在正式 Math-100 完成前只作初步呈现，不作已确认结论。

9. **正式 Math-100 完成与跨域对照升级（2026-09-21）**：协议 d53c08d 原样执行（534 次调用，零协议改动）。结果复现接口塌缩（见上）；按预注册条件规则，跨域正反对照由"初步呈现"升级为"已确认"。**全部实验自此停止**：P1/P2/Decomposition/Router/Local Replan/MBPP 扩展/Graph Forest/正式 Math 均封口；下一步仅剩论文主线重构（阶段能力异质性→任务分解与能力解耦→异构节点分配→反馈驱动动态调整→适用边界分析）。

10. **外部基线对比（2026-09-21 完成，641 次调用，协议 c4ac148/2de6fab，one-shot）**：三个 style 基线（明确标注 adapted to same pool/panel/scorer/budget，不代表原方法本身）在 Finance TAT-QA-200 与 MBPP-100 上执行。结果与口径：RouteLLM-style 两域均退化为始终选 large（0 切换）——写'在本文冻结模型池与训练分布下未产生有效切换'，禁止写'RouteLLM 无效'；FrugalGPT-style cascade：Finance −20.0pp（CI [−26,−14.5]，McNemar p<1e-10）vs Code +5.0pp（CI [+1,+10]，**exact McNemar p=0.0625 未达显著，禁止写'显著反超'**）；Self-Refine-style：Finance 8.0%（−44.5pp，p<1e-10，自批判改坏 90/200）vs Code 85.0%（+9.0pp CI [+4,+15]，McNemar p=0.0039 显著）；Code 上 Self-Refine vs Dynamic-Real：+5.0pp 点估计，CI [−2,+12] 跨零、McNemar p=0.267 未达显著——只写'点估计更高、成本一半，配对差异未达显著'。**命名硬规则**：Finance 面板 40.0% 是 DAG-L/M（异构静态阶段分配），不是 Dynamic-Real；Dynamic-Real 从未在 TAT-QA-200 面板上运行，禁止并格。实验自此永久关闭（FINAL_EXPERIMENT_AUDIT.json）。