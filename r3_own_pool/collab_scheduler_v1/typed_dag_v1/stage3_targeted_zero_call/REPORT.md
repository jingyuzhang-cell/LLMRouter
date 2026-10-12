# Stage 3 专项零调用修复

## 原始失败归因
库存初始、修复原件为stage3_producer_fresh_real_01/RESPONSE_01_RAW.txt、RESPONSE_02_RAW.txt。定义节点n1/n2/n3/n4，却直接生成n1_facts_0、n1_facts_1、n2_expression_0、n3_value_0。compile_producer_plan只保留精确字符串并派生dependencies，未制造或重命名这些引用。原Prompt说exact ref strings但未明确输出实例与节点ref的区别；JSON Schema只能约束字符串形状，不能表达同一动态对象内跨节点引用集合。程序验证仍为最终引用约束。

产能审查原件RESPONSE_04_RAW.txt：prompt2228、completion160、finish_reason=length。字符串在char91开始后未闭合，json.loads抛Unterminated string；不是图候选JSON截断。原审查仅json_object、长reason无长度约束，要求requirements重复列节点ID，整个图provenance重复包含规划信息，均增加负担。长度终止证据证明响应在输出上限处停止；不能推断只增大上限就能解决语义覆盖。

下一修复REQUEST_PRECHECK为input1713+maxout768=2481，已有3913，合计6394>6000。原路径准确派发前阻断，但未事先为审查和执行请求数留出可观察预检。全局7652<24000不允许借用独立执行预留。

## 代码变化
- generation.py：唯一生产者命名空间明确为当前nodes[*].ref；禁止fact/port/output实例ID。保留前向、多根、可变拓扑、稳定执行ID和严格原验证。审查传递图结构，移除重复provenance。
- coverage_review.py（新增）：PASS/FAIL、错误代码、问题节点、160字符证据、replan；审查严格Schema由真实HTTP使用；截断/JSON格式/Schema/语义拒绝分别标记，未闭合JSON绝不接受。历史Stub审查仅保留显式legacy_review_diagnostic兼容。
- fresh_acceptance.py：审查严格json_schema，输出上限384。ScopedBudget.preflight记录已知/未知保留、当前最大预留、后续资源、独立6000执行保护、题/全局请求余量与墙钟。规划保留审查+最多5次执行请求，审查保留5次执行请求；保留原reserve最终强制计费。
- test_stage3_targeted.py（新增）：12项历史原件重放、审查错误分类、矛盾PASS拒绝、未知用量、执行保留、未来Token/请求、墙钟测试。

## 测试与边界
原173项全部通过；新增12项通过，总185。原前向、多根、三/五节点、重复/歧义、自依赖和环检查均回归。历史响应只读，冻结48配置及评分协议未改，无真实模型启动或调用，无Git提交/推送。

## 预算预检的准确边界与剩余问题
每次真实请求仍按实际tokenizer的输入+输出上限做最大预留；失败未知用量不退款，执行6000受保护。preflight支持显式future_tokens/future_requests，但当前入口对未知后续生成/修复文本不宣称可精确预知Token最坏总量；future_tokens默认0，强保护为固定执行信封而不是完成执行的数学保证。未知回复会改变后续输入长度，必要时仍安全停止。墙钟30秒是清理底线，不是未知模型服务时间保证。新真实实验前仍需冻结新源码哈希、为具体新任务制定审查/修复未来Token包络及最低执行资源；旧准备阶段源码哈希已失效，不得原样放行。

生产者说明加强是Prompt修复，尚未真实验证模型遵循率；历史非法候选仍拒绝、不猜测、不删边。产能旧图只用ctx_text的语义缺口仍需新审查实测；形式合法不保证覆盖或答案正确。本轮只提供零调用修复证据，不增加历史生成成功率。等待用户确认下一轮预算。
