# 初始化DAG目标一致性专项审计（零调用）

## 根因矩阵
|原始证据|问题分类|代码依据|确定性判断|语义边界|
|---|---|---|---|---|
|最新A final_outputs→n4，n3→n1，n5→n1+n3|最终目标生产链不完整；未消费声明分支|semantic_validation.py:54 connectivity_errors|n3/n5不在n4反向依赖闭包；FINAL_OUTPUT_CONNECTIVITY|不能据名称判断n3究竟应计算什么；不能改final或删节点|
|最新A唯一抽取n1.context_field=ctx_table|明确公开必需来源ctx_text遗漏|source_coverage.py:64 audit_plan_sources|在本轮冻结必要来源声明下ctx_text无进入最终链的生产者|非默认强制两来源；未知必要来源应待独立审查|
|最新B两个step输出expression_remaining_labels|生产者定义违反唯一性|goal_ir.py:31 compile_goal_ir、50行唯一符号检查|同一确切symbol在图局部作用域内有两定义，无分支选择协议，不可接受|Prompt早已明确全图唯一；不是名称相似度问题|
|最新B calculate_remaining_labels.operation=form_expression|描述意图无法静态证明；声明操作无法产生目标类型|goal_ir.py:13-15 OPERATIONS；protocol.py CONTRACTS|按照声明操作，它是expression生产者，不是calculate；全图不存在remaining_labels生产者|不从ref/name把操作自动改为calculate；描述是否选错必须独立语义审查|
|最新B final_goal remaining_labels:calculated_value，verify输入remaining_labels|最终目标与消费者均缺明确生产者|goal_ir.py:输入symbol检查、最终goal检查|原编译器先停在重复符号；新只读审计同时列IR_GOAL_UNCOVERED与IR_MISSING_PRODUCER|不能根据表达式名字猜目标或新增节点|

最新原件位于ab_review_diagnostic_v1/execution/A、B/generate_HTTP_RESPONSE.json。两组均HTTP/JSON/Schema通过不等于上述语义声明合法。A未装配、B未装配，两组未调用语义审查。本报告不更改原结论。

## 生产链与操作目录
已有compile_producer_plan验证精确ref、输入角色、合法类型；inspect_semantic_plan验证唯一节点、缺失依赖、自环、环、多根汇聚和所有声明节点到达至少一个final。compile_goal_ir验证输出类型、符号唯一、输入存在/类型/单位、必需角色、final生产者；source_coverage验证声明必要来源及其最终路径。execution.py:46、81已有运行时表达式绑定与血统检查，规划未产生事实/表达式文本时无法提前证明事实正确。

操作仍仅extract→source_facts、form_expression→expression、calculate（已有facts+expression）→calculated_value、verify_value(value)及verify_expression(facts+expression)→verified_value。calculate.v1使用合法表达式的确定性求值，不新增LLM计算能力，不支持根据description隐式决定加减。facts不可来自derived value，expression不能当value。单位目前为符号链精确标签匹配，不是完整物理量维度演算。实际操作意图统一REQUIRES_SEMANTIC_REVIEW，声明静态一致不等于正确任务规划。

图内symbol命名空间必须唯一，不按字符串相似度或输出type另造作用域。多个显式生产路径若有同一symbol，当前协议无选择/合并算子，保守拒绝；需要未来注册明确算子后才能支持。

## 最小机制改动
仅新增goal_chain_audit.py audit_goal_chain与test_goal_chain_audit.py。复用旧编译/检查器，输出原始符号多生产者清单、消费者绑定状态、final生产者、唯一可追踪时的反向闭包、来源状态、周期路径与操作意图待审查。不同独立声明错误可同时展示，避免第一异常掩盖缺失目标。编译失败/歧义时不构造假的依赖图，不编造完整链。未改生产Prompt、生成修复次数、执行器、模型分配、计量或评分，也未将只读审计自动变为新生产准入门。

325既有+11新增=336/336零调用测试通过（318typed+18固定入口）。合法3/5节点、多个根汇聚、三种初始化协议、运行目的不从名称猜测均不会被误拒绝。新增覆盖缺最终生产者、必要死分支、重复表达式、缺表达式、自环/环证据、角色输出冲突、来源遗漏及未知状态、候选不被修改。原有Stub完整表达式求值/血统测试继续通过。

## 历史重放
HISTORICAL_REPLAY.json重放6个原始候选：最新A/B和run02 B、run03 B、run04 A/B，均保持拒绝或待独立语义审查，不修改原件。最新B独立列出重复表达式、未定义remaining_labels；A列出n3/n5死分支和ctx_text缺失。run04 A输入合同可静态满足但缺ctx_table；run03 B缺facts、run04 B缺expression；run02 B重复结果symbol。原始错误与新静态清单分别保留，源SHA前后相同。重放不是新LLM生成成功。

## 风险、协议建议与下一轮条件
当前协议可以表达这些合法任务，证据尚不足以认定表达能力不足；真正缺口是LLM未生成满足其自身声明目标的完整计划。不要再单题堆Prompt或放宽编译器。
最小可选协议建议（仅设计，未实施）：由公开任务需求可选提供期望final输出类型/单位；Graph或IR检查声明final类型与该公开约束一致。不能由节点名字推断，不能统一强制所有任务计算或验证。迁移需goal_ir_schema、生成器公开输入及两模式final类型适配，保留旧任务未声明时待审查；补类型误拒绝测试，无需改变执行器。它仍不保证算术意图或全部来源语义正确。
离线工具与回归已就绪，但本轮没有准备/冻结下一真实入口；现有已暴露诊断题不具备独立泛化验收条件。新独立真实生成验收须先冻结未调试任务、两模式一致公开输出约束/来源协议、完整预算、版本及独立语义审查。零新增真实调用，无提交推送；冻结实验/48配置/评分/历史结果不变。完成后停止，不自动启动A/B。
