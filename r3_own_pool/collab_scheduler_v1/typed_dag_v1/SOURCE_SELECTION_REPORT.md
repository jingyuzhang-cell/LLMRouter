# 第三阶段：首个真实非回退图完整执行且评分正确

本轮取得真实执行证据：此前由LLM生成、程序装配且通过验证的非回退图，经新事实选择适配器完成抽取→推理→工具计算→验证，最终11，既有score_v21判正确。**这是旧真实生成图的延续执行成功，不是本轮一次新的生成成功，也不是当前版本完整生成器稳定验收。** 本轮新生成仍失败，未执行任何固定回退图。

## 已证实的根因与勘误

旧 fact_semantics.NUMBER 使用 `(?![\w.])` 作为右边界，排除了句末 `6.`/`17.` 中的数字。实际任务为 `Last year cash: 6. This year cash: 17.`，因此旧候选位置表为空，来源Schema也没有有效数值候选。此前报告将空事实主要归因于模型事实选择，证据不足；本轮隔离执行原始模型解释为“没有提供原始操作数”，候选列表确实被程序错误扫描为空。

已修复为 `(?!\w|\.\d)`：允许句末标点，仍避免从小数中截取整数部分。新增句末数值与完整小数测试，同时验证旧无数字来源仍为空。历史原报告、候选图、费用和轨迹不覆盖；本报告为追加勘误。

另两项实际错误：本机xgrammar不支持uniqueItems，造成一次HTTP400；生成计划Schema未限制节点ID格式，模型产生纯数字ID而装配器拒绝。前者移除解码层字段，重复ID仍由程序严格拒绝；后者已在最终Schema约束ID/依赖/最终节点引用的格式，完成零调用测试与本地编译，**最终ID约束尚未重新真实生成验证**。

## 最小适配及协议

- fact_semantics.source_candidates 扫描公开输入中的全部有限数值出现位置，不按gold筛选；每项含来源SHA、source_id、值、原字面量、位置和上下文窗口。
- LLM只返回 selected_source_ids 和 reason；assemble_source_selection 解析选择、拒绝不存在/重复/过期来源ID，按精确来源装配原 facts.v1。允许有理由的空选择，不凭任务答案替模型补选。候选词法扫描可能包含无关数字，不能作为事实相关性或任务覆盖保证。
- TypedExecutor 的 source_selection 模式继续走原 MeteredExecutor；TRAJECTORY 保留原始模型选择响应，TYPED_EVENTS记录装配注册后的facts、选择、引用快照及派生血统。没有平行费用账本，也没有修改CONTRACTS或评分函数。
- 生成器公开语义规划输入不再暴露合同ID作为可复制任务标签，仅提供可用类型与输入输出能力。计划Schema分类型要求抽取来源；合同仍由assemble唯一匹配，所有图再次完整验证。可变节点数/拓扑保留，不自动增删边、不套固定四节点答案模板。
- generate_and_execute 增加显式 extraction_mode 参数，Stub完整新生成路径已测试。真实入口采用同一Graph/TypedExecutor/MeteredExecutor，source_selection为显式启用；历史调用默认facts模式仍保留。

## 真实成功轨迹

目录 stage3_source_selection_real_05，模型 Qwen/Qwen2.5-7B-Instruct，temperature=0，单GPU锁。Graph SHA `61adaa20a82188fe7386a384c4734e37d9ac7b66e329bca5b53249f98258aaf1`，版本2，来源stage3_fact_reference_real_03/RESULTS.json及其冻结SHA。

| 节点 | 合同 | 实际路径 | 结果 | 本次Token |
|---|---|---|---|---:|
| extraction_1 | facts.v1 | medium真实LLM选择原文候选；程序绑定 | source IDs `s_fb10d70a27db_16`、`s_fb10d70a27db_35`，原始值6与17 | 543 |
| reasoning_1 | expression.v1 | medium真实LLM | `v1 - v0`，在显式映射中绑定稳定fact IDs | 670 |
| transformation_1 | calculate.v1 | 原exec_calc工具，零LLM | 11.0，保留两个来源事实ID | 0 |
| verification_1 | verify_value.v1 | medium真实LLM | 11.0，与派生血统一致 | 135 |

四节点均done，执行COMPLETE，最终任务质量true，零恢复、零缓存别名、3新增真实请求、1348Token。实际执行墙钟2.923秒、服务需求2.903秒。该运行总墙钟77.888秒，model_load_s=37.095秒；总墙钟还包含检查点核验和客户端初始化等，不能以执行时间替代运行总耗时。

原图生成阶段在历史来源中为3请求/3558Token、墙钟11.869秒。它是旧运行费用，不计为本轮新的生成费用；不可简单把跨版本跨运行的生成与执行时延相加宣称同次端到端性能。SOURCE_SELECTION_COMPLETED_GRAPH.json保存图、模型分配和来源引用。

本例抽取值在原文精确定位，数学与评分正确；单位仅能标unknown/UNDETERMINED，未声称语义单位全面认证。生成子任务标签仍不充分，验证节点检查的是数值一致性，不能保证复杂任务语义正确。

## 本轮资源及所有失败

本轮新信封16请求/49152Token/600秒，上轮22请求/21250Token单独保留，不复用余额。

| 运行 | 请求尝试 | 已知Token | 未确认预留 | 结果 |
|---|---:|---:|---:|---|
| source_selection_real_01 | 4 | 3953 | 0 | 新生成两题均因抽取来源缺失而回退；回退未执行 |
| source_selection_real_02 | 1 | 0（已知usage下界） | 8192 | HTTP400 Schema不支持uniqueItems；未确认预算保留 |
| source_selection_real_03 | 1 | 251 | 0 | 旧图延续，旧扫描遗漏句末数值，空选择后阻断 |
| source_selection_real_04 | 4 | 4312 | 0 | 新生成两题均因纯数字节点ID而拒绝；回退未执行 |
| source_selection_real_05 | 3 | 1348 | 0 | 旧真实图延续执行成功、评分正确 |
| 合计 | 13 | 9864 | 8192 | 已知＋预留18056；未扩大上限 |

各运行墙钟合计389.797秒（含模型加载，不含运行间代码修改间隔）。逐DISPATCH reserved/response对账见SOURCE_SELECTION_REAL_EVIDENCE.json。HTTP失败不登记为零消耗证明，未确认8192仍扣住；成功后剩余3次请求不继续消耗，GPU已释放。

新生成失败的01/04各首次合法0/2、修复后合法0/2、回退2/2。均是同两个开发任务重复诊断，不能合并为独立样本成功率。02/03/05延续不增加生成分母；成功执行仅一题，不支持总体正确率、模型排序或算法优势。

## 测试和边界

最终110/110零调用回归通过，原73项保留，加事实引用/来源选择/句末扫描/来源及ID Schema测试。本地xgrammar选择及最终计划Schema可编译。测试SHA记录在SOURCE_SELECTION_TEST_RESULT.json；真实运行每目录PROTOCOL绑定其实际执行版本，最后仅零调用ID约束修改没有冒充真实证据。

```bash
cd /root/r3_own_pool
python3 -m unittest collab_scheduler_v1.typed_dag_v1.test_typed_dag collab_scheduler_v1.typed_dag_v1.test_generation collab_scheduler_v1.typed_dag_v1.test_assembly collab_scheduler_v1.typed_dag_v1.test_fact_semantics collab_scheduler_v1.typed_dag_v1.test_source_selection collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime
```

实际修改：fact_semantics.py、execution.py、generation.py、assembly.py、real_fact_reference_smoke.py；新增test_source_selection.py及独立报告/证据/图导出/诊断目录。冻结实验、48配置、既有评分、TEST16均未改；无git提交/推送。未进入结构优化。

可声明：至少一张真实LLM非回退图已完成真实执行并评分正确；来源装配与稳定引用机制在该例有效。不能声明：当前新生成到执行的一次完整实时闭环已经通过、稳定合法率/总体任务成功率、生成DAG优于固定图、多目标算法优势。

下一阶段应在明确的新验证协议下测试最终ID约束及依赖修复，争取当前版本同次“任务→新生成→验证→执行→评分”成功；仍留在第三阶段，不进入结构优化。本轮真实调用已停止。
