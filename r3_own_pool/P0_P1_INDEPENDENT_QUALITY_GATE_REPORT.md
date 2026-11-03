# P0/P1 独立质量与新领域数据验收

**最终状态：HOLD，不启动真实API。** 已完成独立评分器技术实现、零调用机制测试、新领域官方数据落盘及资格审查；没有把缺少真值的真实任务判成通过。没有修改ZCODE、旧冻结DAG、旧Q或历史账本。

## 四个Gate

|Gate|本轮结果|具体阻塞|
|---|---|---|
|P0-1 四任务评分|程序/机制测试 **82/82通过**；真实参考验收HOLD|四任务的terminal_evaluation.ground_truth目前是“人工标注...”文字说明，没有对应完整冻结标注文件|
|P0-2 独立性|**PASS**|评分仅使用最终输出、评价端参考、原始材料及引用；通过自评/调度字段注入不变性和import白名单检查|
|P0-3 结构|证书机制测试通过；实际图**HOLD**|缺原子工作/端口合同及真实变换绑定，不能仅依据拓扑合法声称语义保持或质量收益|
|P1 新领域|官方数据下载、Schema与标注引用完整性通过；复杂任务资格**HOLD**|SciFact多论文标注常是替代证据；当前SWE样例没有证明必要的独立生产模块分支，且测试环境未复现|

## 1. 实际交付

目录：`/root/r3_own_pool/dag_terminal_quality_gates_v1/`。

- `p0/terminal_scorer.py`：F1/F2/O1/O2四类终端入口及extraction/aggregation/verification/reasoning/generation/retrieval六类节点评价。无调度器或网络依赖。
- `p0/F1_FINAL_OUTPUT_SCHEMA.json`等四份Schema：独立评价投影的结构要求，不含答案enum/const；不修改原执行合同。
- `INDEPENDENT_QUALITY_PROTOCOL.md`：分母、UNKNOWN、必要遗漏、数值单位、有限语义、证据支持、时间、召回前提及结构变换边界。
- `p0/REFERENCE_COMPLETENESS_AUDIT.json`、`ACTUAL_REFERENCES_EVAL_ONLY.json`：逐任务真实缺口；缺失处为null，没有生成虚构Gold。
- `p0/FROZEN_SOURCE_BUNDLES.json`、`TASKS_AND_MATERIALS_PUBLIC.json`：来源与公开材料投影。预写facts/claims/relations/assessment/report不进入公开投影。
- `p0/structure_gate.py`、`ACTUAL_GRAPH_AUDIT.json`：只读结构资格检查，不修改或替换ZCODE优化器。
- `COUNTERFACTUAL_PROTOCOL.json`：A单模型、B静态异构、C固定图动态恢复、D完整图森林的同条件对照；目前未执行。
- `p1/`：SciFact及SWE-bench Lite原数据、公开输入、评价端参考、候选与依赖审查、HTTP及哈希记录。

## 2. 真实任务参考缺口

|任务|已保留材料|仍缺的独立参考|
|---|---|---|
|F1|卓然/纳川/欢瑞9份PDF，按SHA256匹配原始文件而非按字节数猜文件|完整公司风险事实集、可比期间/法律口径、独立风险排序/并列依据；任务截止尚未冻结|
|F2|西王3份PDF|完整事件—日期—主体对应集及排序/去重边界、独立因果关系、当前风险状态；任务截止尚未冻结|
|O1|既有欧菲光当前/历史公告和媒体材料；按page保留来源|原始泛化任务的完整claim-verdict-evidence及口径标注。已有数值/来源断言核验不能升级成利益输送外部真假结论|
|O2|同一公开来源包|独立逐期情感标签、采样宇宙、趋势窗口/阈值、事件关联及未来观察结果；全部缺失维度UNSCORABLE|

12个证券代码原文跨度与既有manifest一致，仅为文档身份锚点，不是12个风险/因果/情感Gold。旧SOURCE_ENVELOPE中存在预写关系和报告；本包没有把这些执行合同内容冒充独立外部真值。

真实任务当前四个Q_terminal均无法识别；没有真实端到端输出被新评分，也没有把null转换成0。82个测试的答案均为明确标记的synthetic fixture，只验证程序，不作为实际任务参考。

## 3. 评价独立性与指标

Content F1、引用合法性、命题支持、时间及运行合同分开。错误日期/金额/角色不因其他字段正确而放过；合同或证据失败不会抹掉已可评分的内容。引用命中只证明跨度存在；支持还要求冻结命题支持集合及预测命题正确。

F1同时检查事实、比较口径、风险排序；F2检查事件—日期配对、重复、额外错误及完整必要事件顺序；O1将判决、引用与支持分开；O2无真值不打主观分。

原型Q_terminal只在全部必需客观维度有独立参考且可评分时取其最小值，作为保守瓶颈指标；不是成功概率、不直接作为Router标签或在线Qmin。开放报告整体主观质量仍UNSCORABLE。

retrieval recall必须有已核验的NECESSARY_SET，相关性precision另需完整相关性真值；本次四任务均没有该必要集合，因此严格召回率不可评分。

## 4. 实际图的结构发现

下表来自上游依赖列表重算，未改写上游文件：

|任务|节点|实际边|上游概要边数|拓扑关键链（节点数）|最大并行宽度|
|---|---:|---:|---:|---:|---:|
|F1|6|5|7|4|3|
|F2|6|6|7|5|2|
|O1提案|7|6|8|5|3|
|O2|6|5|7|4|3|

这里O1是ZCODE的七节点提案，**不能冒充原已冻结的六节点opinion_multisource_dag_v1**；两者身份保持隔离。

SPLIT/MERGE/REWIRE单测证明声明式工作全集、必要信息路径、端口和内部顺序可被检查，并检测节点数/宽度/关键链变化。没有真实绑定证明时实际图仍HOLD。拓扑性质变化不是实测C/L，更不是已证实ΔQ。现有SPLIT原型复制节点依赖，没有工作内容分区证书，不能直接认证为语义等价优化。

## 5. 新领域实际数据

### SciFact

从[官方仓库](https://github.com/allenai/scifact)指向的公开数据包实际下载并解析：**5,183篇摘要；train809、dev300、test300条claim**。官方[数据说明](https://github.com/allenai/scifact/blob/master/doc/data.md)区分公开标注与未标注测试集。逐标注检查文档存在和句子索引，0处无效引用。

有多论文标注的claim：train37、dev10；test无公开证据/判决标注。181篇被引文档跨官方split出现，未认证论文簇隔离，不能宣称新的独立事件/论文簇测试。

选取dev claim70作为只读候选：两个论文均各自提供SUPPORT rationale。它们是**可替代的支持证据**，没有证据表明原始单claim任务必须两条独立分支合流。因此当前不认定复杂多分支资格，不改写问题为人为多论文比较。公开候选只含claim及完整corpus入口，不含Gold文档ID和判决。

许可证原文已保存：claims/annotations为CC BY 4.0，abstracts为ODC-By 1.0。[官方许可说明](https://github.com/allenai/scifact/blob/master/LICENSE.md)。

### SWE-bench Lite

从[发布方数据集](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Lite)固定revision `6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2` 实际下载：**dev23、test300条**；必需字段完整，instance_id无重复。输入与patch/test_patch/FAIL_TO_PASS/PASS_TO_PASS分开保存，hints_text未纳入在线输入。

只读开发候选`sqlfluff__sqlfluff-1625`，base commit `14e1a23a3166b9a645a16de96f694c77a5d4abb7`。按issue中的L031名称获取对应源文件：HTTP200、8,076 bytes；按既有测试命名惯例尝试的测试路径HTTP404，已如实记录。未从Gold patch反推生产代码路径。

该issue目前展示的是规则诊断→修改→测试链，没有证据证明必要的跨生产模块并行分析。未创建环境、未执行代码、未应用参考patch，也未复现FAIL_TO_PASS基线，因此解决率UNSCORABLE。[官方评价流程](https://www.swebench.com/SWE-bench/guides/evaluation/)要求提交patch并在固定环境运行测试，下载字段不能替代这一验证。

本轮开发审查读过dev样例及test前两条issue文本，不将其作为未见确认样本。SWE数据卡未明确给出本次数据集许可字段，未臆造许可结论。

## 6. 对照协议及停止点

固定同一输入、材料版本、模型池、预算、D、初态及公平缓存规则；A/B/C/D分别保存全部失败与未执行。t0从协议规定的第一项任务工作开始，方法内的规划/检索开销计入。D仍UNKNOWN，客户端上限不是任务截止。

B-A、C-B、D-C仅在其他条件匹配时支持分配/恢复/图森林机制包的增量比较；不把D优于A直接解释为纯结构收益。没有真实运行，本轮不报告ΔQ/ΔC/ΔL、Pareto收益或P90。

**下一步的最小实质门槛是先给一个真实任务补齐独立终端参考，而非再建更多DAG。** 当前F2至少需要一份完整且来源支持的事件—日期—主体及必要因果/状态标注；F1/O2的主观排序/情感不能靠程序自造。结构线同时需要任务级工作/端口/绑定证据；本包已列接口，但不改ZCODE实现。

按要求停止在验收结果，不因机制测试通过启动API，也不把缺失Gold当作新的付费授权问题。

## 7. 哈希与离线复核

评分实现SHA256：`efba124ad37d04e5988e8a095e6111664f9fe5789fa92ce08e32af3dfd8d668d`。包冻结身份见`FREEZE_SHA256.txt`；官方下载文件SHA和HTTP记录见`p1/FETCH_RECORDS.json`。原输入身份检查33份、0变更。

```bash
python /root/r3_own_pool/dag_terminal_quality_gates_v1/VERIFY.py
python /root/r3_own_pool/dag_terminal_quality_gates_v1/p0/test_gates.py --check-only
```

可对已有最终输出作**离线侧评**，不会派发模型请求；真实参考未齐时保持UNSCORABLE：

```bash
python /root/r3_own_pool/dag_terminal_quality_gates_v1/SCORE_OFFLINE.py \
  --task F2 --final-output /path/to/existing_final.json \
  --output /path/to/new_F2_quality_sidecar.json
```

本轮0真实LLM调用、0GPU、0训练，未提交或合并Git，未启动容器或真实恢复实验。
