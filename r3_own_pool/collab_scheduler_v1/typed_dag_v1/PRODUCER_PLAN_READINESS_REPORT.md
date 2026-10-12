# 第三阶段新任务准备：单一生产者关系协议

本轮只做零调用代码准备、历史重放和任务冻结。完整回归173/173（原160项+新增13项）通过，4.949秒；最终移除受限入口废弃旧题常量后，相关17项再通过。真实LLM请求0，未启动模型，没有提交或推送GitHub。冻结实验、固定48配置、评分代码和历史候选未修改。

## Prompt与输入输出审计

现有CONTRACTS定义：extraction读取question/context产facts；reasoning读question/facts产expression；transformation读facts+expression产value；verification读question+value，或question+facts+expression，产value。generation.py的类型描述与这些合同一致。

旧语义Prompt要求LLM通过dependencies选择所有上游，但没有明确逐输入角色的生产者选择。尤其transformation必须同时提供facts和expression；只依赖reasoning不会自动拿到其祖先facts，旧真实计划遗漏了这一点。**旧语义Schema本身只有一套dependencies，并非已经让模型输出多份重复边字段。** Graph兼容诊断才同时表达inputs与dependencies，这条路径保留为历史诊断，不作为新默认生成协议。

本次把默认规划改成input_producers：只表达一次每个所需语义输入的精确生产者。LLM不再生成dependencies、合同ID或原始port bindings。程序派生dependencies，现有装配器选择唯一合法合同并绑定端口，最后verify_producer_bindings逐输入确认绑定恰好等于LLM明确声明的生产者，不能将别的上游代替它。

示例仅表示接口，不是生成模板：

```json
{"ref":"evaluate","name":"Compute requested result","type":"transformation",
 "subtask":"Evaluate the requested expression",
 "input_producers":{"facts":["sourceA","sourceB"],"expression":["formula"]}}
```

extraction.input_producers={}，来源仍通过context_field选择；reasoning使用facts；verification可选value或facts+expression。所有节点question及已选ctx字段由程序绑定。上述角色来自现有合同，不允许任意新角色。LLM仍决定节点数量、类型、内容、精确生产者和最终输出引用；不固定三/四/五节点或某张拓扑。

## 程序装配边界

新模块producer_plan.py：compile_producer_plan、producer_schema、verify_producer_bindings、guard_raw_repair。

- 只把已声明的生产者关系转换成边，invented_edges=0；没有搜索“看起来合适”的生产者、递归补祖先边或补缺失节点。
- facts角色可有多个唯一生产者；expression/value必须是一个明确ref。未知、歧义、自依赖和环继续由semantic_validation拒绝；已知但输出类型不符在编译阶段拒绝。
- 不接受同时提供input_producers和dependencies，返回DUPLICATE_DEPENDENCY_REPRESENTATION。
- 中间边集合是逐角色关系的并集，原角色列表完整保存并逐端口复核；不是删掉非法关系来合法化图。
- 保留前向引用、多根、重名不同ref、可变拓扑；程序仍统一生成最终执行ID。
- 合同装配之前执行完整语义依赖预检，之后继续现有Graph验证/TypedExecutor/MeteredExecutor。没有另建Graph、执行器或费用账本。
- 编译失败后的修复也保护原始节点身份和明确声明关系，不能因未得到compiled plan就删除子任务。对已歧义的旧ref仍保守拒绝一一对应；错误输入生产者替换在保留检查下也可能需人工重新协议化，不能保证所有合法修复都自动接受。

旧dependencies计划可重放，但明示protocol=legacy_dependencies_diagnostic；不自动升级成新生产者协议。新Graph provenance包含raw_planner_plan和producer_plan，记录exact producer selections与0个猜测边。报告生成成功须同时说明规划协议、是否回退、图验证和执行结果，不把程序补未知边称作LLM成功。

## 代码改动与验证

- 新增producer_plan.py、test_producer_plan.py。
- 修改generation.py：新Schema、单来源Prompt、生产者编译/装配复核、原始修复保护和provenance。
- 修改fresh_acceptance.py：必须显式指定公开manifest及独立evaluation文件；预先核对内容/评分来源哈希，再启动资源流程。评分数值只在score_final读取；规划只接收公开任务。废弃旧题常量移除；增加producer_plan源码哈希绑定。
- 新增next_fresh_acceptance_v1任务包及本报告。

新13项覆盖3/5节点、多根、前向引用、重名、缺角色、错误生产者、多个expression生产者、双份依赖字段、循环、悬空引用、历史协议隔离、修复删节点保护及新Schema完整Stub执行。

新Schema在实际服务r3_venv离线xgrammar编译通过。独立mock_3/mock_5保存原始模型Stub响应、Graph、完整调用与执行日志，均GENERATED→COMPLETE，使用explicit_input_producers.v1；都是通用2/3数值夹具，不是新冻结任务。

四个历史真实候选完整重放，JSON内容不变、invented_edges=0，仍全部非法。证据HISTORICAL_REPLAY.json逐个保存SHA与现版本错误；没有给候选补边、断环或选择新生产者。

## 两个新任务冻结

目录：next_fresh_acceptance_v1。

|UID|任务及公开数据|内容SHA位置|
|---|---|---|
|stage3-fresh-stock-20261011-03|仓库期初52箱、入库17箱、出库24箱，求结余箱数|TASK_MANIFEST.json.content_sha256|
|stage3-fresh-utilization-20261011-04|产线每小时150件、运行3小时、实际315件，求0至1的产能利用率比值|同上|

两题与已调试的现金差值、分部收入、发票折扣及批次均价不是相同任务内容。冻结前在r3_own_pool与e2_1_protocol检索两题独特源文本均无匹配；未对这两题运行生成器/Stub，只有公开内容和哈希准备。精确文本扫描不能证明对所有语义近似任务的彻底去重；这仍是两个合成机制任务，不是泛化基准。

TASK_MANIFEST只含公开context/required_outputs及内容哈希。EVALUATION_ONLY.json独立存储冻结数值，manifest仅引用评分文件SHA，不含gold数值。SOURCE_HASHES.json冻结当前生成、编译、验证、执行及入口源码。生成、覆盖审查、分配和恢复不读取评分文件。两题都使用原score_v21，不改变评分口径。

## 新信封草案（未批准）

RESOURCE_ENVELOPE_DRAFT.status=DRAFT_NOT_APPROVED：最多24新请求、24000Token、20分钟；每题12请求，生成/修复6000、执行/恢复6000；最多5节点、1次生成修复、1次执行恢复，HTTP零重试；单模型Qwen2.5-7B。

每题最多2次规划+2次覆盖审查=4请求；最多5个LLM节点+1次失败节点恢复=6请求，工具节点不额外收费。两题结构性上限20次；24是全局硬顶，不是要求消耗满额。执行恢复只允许同题一次，且保留未完成/错误答案。

Token不是固定每次8192预留：每次实际chat模板输入长度+该阶段最大输出上限预留。错误反馈、事实血统和覆盖审查可能变长；只有charged+reserve满足阶段及全局上限才派发。24k不能保证全部最坏输出都跑完，超过就停止；不能挪用执行预留继续生成。1170秒后不再派发，预留30秒清理；模型加载、核验和服务清理计入20分钟。

预算获批后才可使用同一受限入口（以下仅待批准命令，本轮没有运行）：

```bash
cd /root/r3_own_pool
/root/autodl-tmp/r3_venv/bin/python -u -m collab_scheduler_v1.typed_dag_v1.fresh_acceptance --manifest collab_scheduler_v1/typed_dag_v1/next_fresh_acceptance_v1/TASK_MANIFEST.json --evaluation collab_scheduler_v1/typed_dag_v1/next_fresh_acceptance_v1/EVALUATION_ONLY.json --output collab_scheduler_v1/typed_dag_v1/stage3_producer_fresh_real_01 --execute
```

## 准备状态与剩余风险

具备受限新任务真实验收的工程准备条件：新协议装配、原160项与新增测试、历史拒绝边界、Stub变长闭环、任务/评分隔离及源码哈希已经就绪。**预算尚未批准，不启动任何真实调用。**

尚不能保证LLM会生成唯一ref、有效生产者或正确语义任务分解；角色合法不代表事实支撑、完整任务覆盖或答案正确。重复旧引用及错误生产者替换仍受保守修复限制；输入上下文和6k生成预算可能不足。下一轮必须分列首次合法、修复后合法、回退、COMPLETE和最终正确性，不能把程序装配成功等同于真实LLM端到端可靠。
