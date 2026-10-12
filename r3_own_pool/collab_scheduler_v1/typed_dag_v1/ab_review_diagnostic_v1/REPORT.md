# 317项修复后的A/B诊断准备

状态PREPARED_NOT_AUTHORIZED。本轮0 HTTP、0模型加载，325/325零调用回归通过（317既有+8新增）。源代码、生成Prompt、Schema及转换审计、源manifest、公开输入、独立臂预算、模型权重身份和Tokenizer文件哈希已冻结。默认入口哈希检查通过。

## 请求包络
|阶段|A input_producers|B goal_ir（roles）|
|---|---:|---:|
|生成准确Tokenizer输入|2322|2488|
|生成输出上限|768|768|
|生成最大预留|3090|3256|
|审查样例输入（人工5节点图，仅测量）|2055|2106|
|审查可执行输入硬边界|7936|7936|
|审查输出上限|256|256|
|审查请求最大预留|8192|8192|
|每臂最多2请求总上界|11282|11448|

建议独立全局4请求/22730Token；每阶段最多1请求，两个臂不借预算。审查上界来自真实服务配置8192上下文减256输出，必须在每次派发前用实际Tokenizer检查；超长候选拒绝，不截断。该上界仅保证被准入的路径有界，不保证所有结构合法候选均可审查。生成请求预留同时扣住后续完整8192审查资源。失败未知用量保留整次输入+最大输出；仅明确usage才结算。HTTP500/身份/响应usage异常停止整个诊断，无自动重试。

Tokenizer按真实medium的chat template测量完整user消息，内含任务、来源manifest、必要数据、Schema以及全部指令。response_format的服务Schema额外传给grammar后端，不当作额外user文本重复计量；先前run03/run04输入Token与同路径本地计量一致。审查消息亦包含自身Schema和任务来源。真实响应仍须核对usage；缺失或超出保留不得视作零费用。

## 入口与共用标准
ab_review_diagnostic.py使用InitialDAGGenerator（A semantic/flat，B goal_ir/roles）、原完整Schema、来源检查、coverage_review、MeteredExecutor及Budget，max_repairs=0、fallbacks={}、max_nodes=5。每臂独立缓存/账本，medium单次加载，无模型切换，不执行TypedExecutor、节点或评分。A/B使用同一公开任务、显式来源需求和审查指令。B新增角色协议差异已明确记录，不能将对照称为原flat-B不变。

实际审查图和node_refs由新候选决定，不能预先冻结成某个示例图；冻结的是审查协议/构造源码，示例Prompt+Schema另有哈希，实际请求前另存实际Prompt/Schema/payload哈希。若候选没通过结构/输入/来源，不调用审查，也不把剩余请求挪作新尝试。审查PASS仍不是答案正确证明。

## run04离线重放
A结构/接口PASS，显式公开来源需求下ctx_table路径缺失→FAIL，来源需求未声明时仅PENDING_SEMANTIC_REVIEW；不具备非回退图准入。B原响应缺expression，合同FAIL、未装配、来源未评估；不具备准入。未修改历史候选，重放不计真实生成成功。见RUN04_REPLAY.json。

## 用途与墙钟
仍是曾参与run02/03/04及Prompt改进的标签诊断任务，明确暴露，不是独立泛化样本。未使用四题正式任务或gold；诊断不设评分答案文件，gold不进入任何阶段。公共需求声明仅引用原文，表示本次人工明确的必要来源，不声称程序自动识别了任务全部需求。

离线权重审计+Tokenizer实测46.84754秒；预留按2倍实测向上取整为94秒（安全因子为协议选择）。加载硬限300秒、4请求各30秒、清理30秒→建议全程硬限544秒（9分4秒）。94秒CPU阶段、加载及请求由计时器约束；时间不足提前停止。这是受限信封而非完成时长保证，加载失败或超时不扩大。历史加载至清理约105秒仅作背景，不作为新完成承诺。

## 下一步
技术离线条件通过；真实调用尚未授权。准确建议批准：4请求/22730Token/544秒；A11282、B11448Token；无修复、无重试、无节点执行或评分。执行命令仅在独立批准后使用：python -m collab_scheduler_v1.typed_dag_v1.ab_review_diagnostic --packet collab_scheduler_v1/typed_dag_v1/ab_review_diagnostic_v1 --execute。

旧实验/48配置/评分不修改，历史SHA核验一致，无提交推送。
