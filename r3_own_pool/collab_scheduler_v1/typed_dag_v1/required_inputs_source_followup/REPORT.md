# 必需输入与来源覆盖零调用修复

## run04准确根因
A原图只绑定ctx_text、question，遗漏ctx_table中“6 packs / 7 labels each”。HTTP诊断入口只调用assess_plan进行Schema/结构装配，未运行InitialDAGGenerator的coverage_review；因此“结构合法”并非来源检查已通过。原结构验证不证明语义覆盖。
B calculate_remaining_labels仅有total_labels、labels_set_aside两个source_facts；没有expression输入，也没有form_expression步骤。未由装配丢失。旧Schema允许输入类型并设置minItems=2，两个facts满足该必要条件但不满足完整角色合同。

## 输入协议
此前新增可选goal_input_mode=roles已提供操作独立的必需键、类型和基数。保留flat Goal IR和input_producers。facts/expression/value不互换；角色展开不补造输入。INPUT_CONTRACTS.json记录实际合同。calculate.v1为通用AST表达式求值而非自带sum/product规则；表达式是运算规则输入，不是要求模型再算一次。既有表达式由确定性transformation执行，不添加LLM调用。如果未来引入具备明确内置规则的操作，应注册其独立合同，本轮不冒充已经具备。

## 来源与静态检查
新增source_coverage.py：manifest为公开ctx_table/ctx_text建立整字段及行跨度、文本哈希；validate_requirements核对显式data_id/source_id/原文证据；audit_plan_sources装配前、audit_graph_sources装配后及固定回退检查必需来源能否进入最终输出。generation.generate新增可选required_source_data，不含数值gold，两方案走同一检查与语义审查。来源未知状态PENDING_SEMANTIC_REVIEW；路径存在只登记DECLARED_SOURCE_PATHS_PRESENT，不声称事实已抽取、声明全集完整或答案正确。完整性仍需原审查，审查通过标MODEL_REVIEW_PASS_NOT_PROOF。

原编译器继续检查唯一生产者、角色、单位、环、最终可达性；原执行器的事实溯源和表达式绑定继续验证实际执行引用。规划阶段没有执行表达式文本，不能提前宣称其事实引用正确。多表支持表现为注册ctx_table内多个精确行跨度，未扩展成任意新执行端口；选择字段不等于逐字段正确抽取。没有强制所有表/文本使用，未编造来源或自动补边。

## 测试与重放
299typed+18固定入口=317/317零调用测试通过；在此前305项上新增12项（含已有297项）。覆盖两模式同级来源检查、装配前拒绝、多表跨度、无关来源不强制、3/5节点汇聚与原执行器血统闭环、证据伪造、类型/单位冲突。已有码覆盖缺必需facts/expression、派生值与事实混用、原表达式执行等。run04原件保持；A仅在显式公共来源需求的离线审计中FAIL，未冒称旧运行已有该元数据；不提供完整声明时保持UNKNOWN。B保持拒绝，未改写为成功。详见RUN04_REPLAY.json。

## 条件与下一步
零真实调用/模型加载，无Git提交推送，不改冻结实验、48配置、任务或评分。当前具备离线准备下一轮诊断的基础，但新增源码/Prompt使旧冻结入口不可复用，需新版本哈希、实际Tokenizer包络与独立授权。
建议下一轮从通信诊断转为生成+语义审查的小规模准入：A/B各最多1次生成+1次审查，全局最多4请求，Token上限必须以新Prompt和审查图最大长度测量后冻结，不能复用旧10000的“已批准”表述。墙钟建议20分钟（需加载实测预检），无修复、无节点执行；任何失败按真实结果记录。不在本轮创建或启动新真实实验。
