# 四个瓶颈：文献核查与可执行方案

审计日期：2026-09-08。结论：采纳诊断、成本敏感平局处理、排序/FiLM 消融；不接受“先证明回归失败”“ranking 必胜”“实测 latency 是唯一空白”或“后处理大概率立刻可发表”等预设结论。正在执行的四模型采集与这次 CPU 后处理独立，本轮未停止采集、修改旧代码或调用模型 API。

## 1. 文献到底支持什么

| 原始论文 | 核查结果 | 项目里的用法 |
|---|---|---|
| [EquiRouter, 2602.03478](https://arxiv.org/html/2602.03478v1) | 原文存在；94.90% 是其 RouterBench 大预算可行集合的 top-2 margin 统计；约 17% 是相对其最强旧 router、GPT-4 质量点的成本差，不能迁移为本项目预期。§4.3 明确在质量 tie 时按成本构造偏序，并非跳过全部 tie。 | 最近的方法基线；按原实现复现后，再移植到本项目。FiLM/ranking 是已有方法，不能标首创。 |
| [RouterBench, 2403.12031](https://arxiv.org/html/2403.12031v2#S3) | AIQ 为共同成本区间上单调凸包曲线的平均质量；Zero Router 是固定模型的概率混合。 | 本轮实现 AIQ/Zero Router，按 μ=0 与全部网格投影分开报告。 |
| [Routing Gap, 2607.03436](https://arxiv.org/abs/2607.03436) | 噪声分解针对随机生成和重复采样；论文百分比来自其特定模型池。 | 使用现有三次重复做“另外两次选、留一次评分”的稳定性诊断，未来独立重复采样再估计可重复上界；不宣称已经认证去偏。 |
| [Co-failure Ceiling, 2606.27288](https://arxiv.org/abs/2606.27288) | arXiv 官方编号、标题已核对；结论约束输出某个候选答案的选择策略。 | 二元成功率下计算 1−β；分级质量使用 mean(max Q)，不能把阈值成功率与平均分相减。相关性不能独自确定共同失败率。 |
| [IRT-Router, 2506.01048](https://arxiv.org/html/2506.01048v2) | 模型能力与 query 属性交互确有依据；表 3 的 2.72%/2.15% 是特定 α=0.8 配置，不能泛化为所有 ID accuracy 都无用。 | 学习 model descriptor 可作为后续对照；派生 difficulty 仅分析或用训练内模型预测，不能读测试候选结果。 |
| [RouteLLM, 2406.18665](https://arxiv.org/abs/2406.18665), [Shnitzer et al., 2309.15789](https://arxiv.org/abs/2309.15789) | 偏好监督和分模型性能预测已有先例。 | 保留分类/性能预测为公平基线，不以它们必须失败组织叙事。 |
| [Router-R1, 2506.09033](https://arxiv.org/abs/2506.09033), [BaRP, 2510.07429](https://arxiv.org/abs/2510.07429) | 前者研究 RL 多轮路由/聚合；后者研究部分反馈和可调偏好。 | 相关工作比较作用域；当前全信息、单次选择数据不冒充同一反馈与推理预算。 |
| [RouterWise, 2604.10907](https://arxiv.org/abs/2604.10907), [Beyond Accuracy and Cost, 2607.18253](https://arxiv.org/abs/2607.18253) | 已有基于 profiling 的 latency 路由，以及考虑服务负载/TTFT、联合质量成本延迟的研究。 | 必须增加到 related work；“三轴+latency 从未有人做”不能成立。单卡顺序测量可为受控数据贡献，但不代表生产负载下的动态 SLO 保证。 |

## 2. 本轮已执行的 D0（新文件，不训练）

命令：`OPENBLAS_NUM_THREADS=1 python3 /root/router_decision_diagnostics/analyze.py`

输入：`router_suggestion_audit/OOF.npz`、RESULTS/PROTOCOL，以及生成 C8 的两份冻结 repeat 文件；仅 419 个开发 query，未访问 v3/v4 结果。逐项复核原始指标、三重复均值与矩阵一致，输入 SHA256 前后不变。

产物：DIAGNOSTICS.json、REPORT.md、DIAGNOSTICS.svg/png、INPUT_MANIFEST.json。六项单元测试通过，凸包曲线另与独立线性规划在 150 个预算点对照。

实际发现：
- Top-2 严格 tie 为 53.22%，margin≤0.05 为 66.11%；全池范围≤0.05 仅 24.11%。近似 tie 不是“无路由机会”，很多题仍有差模型可避开。
- Ridge 的 AIQ=0.804182，Zero=0.800957；Δ=0.003225，任务 bootstrap 95% CI=[−0.001966, 0.010540]，仍跨零。
- 保持经验 Best Single 质量时，现有 Ridge 离散策略成本更高 90.82%，其描述性凸包混合也更高 43.42%。不能改写为“省钱 X%”。允许直接退回 Best Single 可保底，但这本身不是学到的收益。
- Qwen-turbo 的质量 marginal oracle contribution 仅 0.005337，但移除会使 Zero Router AIQ 减少 0.011143；这直接反驳“低于 0.01 就是死重”的规则。是否扩池必须同时看成本和质量。
- 三次均值 Oracle=0.880707；用两次选、第三次评分=0.857408。后者仍不是最终真实 Oracle，也不能把差值全部认作不可学习噪声。
- 观测配对 SD=0.062723，不是附件假设的 0.1–0.3。固定当前效应，80% power 的正态近似约需 2924 个独立测试 query；这不是训练集规模。当前 5000 cohort 的 750 test 不足以保证检出这种小效应，不改已有 split 去追显著性。

以上成本继承历史口径，CI 条件于固定 OOF 模型；曲线顶点/插值是在开发数据上作描述性后处理，不能当已验证的线上策略。

## 3. D1：先测成本敏感的平局选择（下一项可执行实验）

保持原 encoder/特征、五模型、分项 Ridge 和 kNN 参数不变。在独立脚本重建相同 OOF 预测，保存每题每模型的 Qhat、Chat、Lhat、fold_id。旧 OOF 仅保存 argmax 决策，无法从中恢复完整预测分数；因此本轮没有伪造 tie-aware 结果。

定义候选集 Aε(q)={m: Qhat_m≥max Qhat−ε}，在其中按预测成本选最小者；成本相同按预测延迟、最后固定 model_id。预测差距不是质量损失保证。ε 候选预先固定为 {0,0.005,0.01,0.02,0.05}，只用训练内验证选 ε/质量约束，外层测试一次评估；不使用真实 test C/L 选择候选。

数据输出：预测 JSONL、各 ε 的选择率、质量差、成本比、配对区间。提供 train-only 最佳单模型和验证选择的 Zero mixture。探索报告保留全部 ε；正式报告只用验证冻结的 operating point。

采用条件：在预先指定质量非劣界 δ 下，质量差 CI 下界≥−δ，且成本节省 CI 下界>0；δ 不看 test 结果决定（候选业务容忍度必须在下一轮实验冻结）。严格“质量不降”用 δ=0。若未满足，不把它升级为默认 selector。

## 4. D2：公平比较 regression、ranking 与 FiLM，避免一次堆叠

先做 2×2 消融：同一共享 trunk/参数预算，(无 FiLM / 有 FiLM) × (pointwise / pairwise)。再加 regression+ranking 联合目标作为额外组。已有 C8 soft pairwise 几乎退化为常数预测，必须保留该结果；“已经做过的 pairwise”与“EquiRouter 的成本 tie 偏序+FiLM”是不同实验。

- Query 特征仅请求时可用信息。保持现有 encoder；能力画像只从训练数据估计。所有 model ID 的学习 embedding 不代表未见模型零样本能力。
- Pointwise 预测校准 Q（与独立资源预测一起计算 U），作为保留基线。
- EquiRouter 对照采用严格质量顺序，质量完全相等时按成本顺序，所有相同者无强制序；每 query 有效 pair 数归一化，无 pair 时返回可反传的零损失。近似 tie 的 ε 扩展单列为实验适配，不能冒充原文。
- 学到的纯 ranking score 只有顺序意义，不能直接当 [0,1] quality 去做 `score−λcost−μlatency`。纯排序组用预测资源构建预算可行集合后取最大 score；或者另训 preference-conditioned utility ranking，与校准 Q 路线分组对比。
- 所有组沿用同一训练/验证/测试协议和随机种子集合（预设 42/1234/20260908）；调参只在验证集，报告每 seed 与跨 query 配对区间。不以 419 开发集反复胜出宣称最终成功。
- EquiRouter 官方代码须另外保存仓库 URL、commit、许可证、默认配置；先跑官方测试/小样例，再做同池适配。只有确实跑过才能写“已复现”。本轮仅核对原文，没有伪称复现完成。

仍保留用户指定八项 baseline（Random、Best Single、KNN utility、MLP winner、线性 Reward Regression、MLP Reward、Transformer Router、Oracle），补充 Zero Router 和 EquiRouter。先运行便宜消融，Transformer 不作为当前采集的前置任务。

## 5. D3：数据量、模型池和正式延迟验证

5000 四模型采集继续，不因为这份建议取消。收齐并通过评分/成本/泄漏门禁后，用固定 validation/test、训练子集 500/1000/2000/3500 画学习曲线；这些是真正的训练 query 数，不能写成 5000 个训练 query。20k 扩展需看学习曲线和预注册的测试功效，而非固定把响应行数当独立样本。

扩池先在训练/验证域比较 leave-one-model-out 的质量 Oracle、Zero frontier、可恢复增益与不确定性；没有达到预设贡献门槛才考虑候选专家，不能从 419 开发集移除模型再回报同一集上的“提升”。同族大小模型也可能靠低成本有效，不要求每个模型质量冠军。

Phase 2 在相同硬件、精度/量化记录、并发/batch、上下文限制下记录 TTFT、decode、total latency；控制 warm-up、请求到达率和缓存，记录失败、重试、截断和 Router 自身 overhead。单卡顺序重测只支持该受控部署，动态负载结论需另外验证。价格必须明确币种/日期/实际账单与代理价差别。

## 6. 论文叙事

建议研究问题：在模型结果高度重叠、监督有噪声且部署成本有差异时，哪些监督与决策设计能在受控质量约束下带来可重复的资源收益？

暂不预先声称 pointwise 有结构性失败、FiLM 必提高样本效率、ranking 必恢复 gap、latency-aware 是独有创新。负结果、公平消融和受控测量可以形成证据；方法贡献需由相对强基线的独立验证来决定。
