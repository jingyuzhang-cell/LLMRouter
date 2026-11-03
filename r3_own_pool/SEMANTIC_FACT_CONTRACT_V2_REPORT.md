# Typed DAG事实语义合同V2：修复与零调用验收

**结论：SEMANTIC_CONTRACT_OFFLINE_PASS；尚不授权或启动真实实验。** 新合同阻止跨设施事实引用，合法三分支仍可执行，旧协议保持默认行为。566/566当前代码离线回归通过，其中20项为本次专项测试；真实模型请求0、GPU启动0。

## 1. 最小接口与版本

保留现有fact_id、value、source及facts.v1端口，不扩大操作集合，不新增节点、边或计算公式。采用与既有rule_envelope类似的可选外层协议 `semantic-fact-contract.v2`，绑定原图hash。

- [semantic_facts.py](collab_scheduler_v1/typed_dag_v1/semantic_facts.py)：新增来源身份验证、事实绑定、表达式检查及`compile_semantic`可选编译包装。
- [execution.py](collab_scheduler_v1/typed_dag_v1/execution.py)：`TypedExecutor(..., semantic_envelope=None)`。启用后将经核验的身份放入facts的`semantic_identity`，将节点语义要求送入Prompt；表达式登记前检查；已有DONE缓存重用前检查。
- [joint_recovery.py](collab_scheduler_v1/typed_dag_v1/joint_recovery.py)：语义身份加入state_hash；缓存先做语义审查再做数值审查；FULL新实例保留envelope；未放宽失效类型或闭包。
- [computation_ir.py](collab_scheduler_v1/typed_dag_v1/computation_ir.py)：仅对显式携带semantic_envelope_hash的接受协议增加hash匹配；原编译流程、Schema、操作及默认接受行为不变。
- [test_semantic_facts_v2.py](collab_scheduler_v1/typed_dag_v1/test_semantic_facts_v2.py)：20项专项断言。

另改两个既有采集器测试的fixture装载，新增 `test_freeze_fixture_support.py`。它仅在临时Mock目录复制已冻结输入、核验原输入哈希并绑定当前源码，以验证旧协议兼容；不修改历史manifest、不绕过真实入口的verify。断言及预算守卫保持不变。

## 2. 六金额的语义身份与来源证据

新工件目录：[semantic_fact_contract_v2](semantic_fact_contract_v2/EXECUTION_CONFIG.json)。原GRAPH与TASK_PUBLIC、FACT_REQUIREMENTS逐字节复制。图仍为8节点12边，hash仍为 `d5785e788741b98b216a681fdcf86ba474ae97f1c69a61753329cb0f1961379c`。

每个事实保留原数值和fact_id，并增加：

```json
{
  "semantic_identity": {
    "semantic_contract_version": "semantic-fact-contract.v2",
    "contract_hash": "<完整外层协议哈希>",
    "entity_id": "<经来源行名核验的实体>",
    "column_role": "<经来源列头核验的角色>",
    "binding_id": "<显式声明的操作数绑定>",
    "source_ref": {"source_field":"ctx_table", "source_sha":"...", "number_start":2987, "number_end":2991},
    "entity_span": {"start":0,"end":1,"quote":"<实际行名单元格内容>"},
    "role_span": {"start":0,"end":1,"quote":"<实际列头单元格内容>"}
  }
}
```

上例偏移为字段示意，不是冻结的真实值。全部真实值见[SEMANTIC_ENVELOPE.json](semantic_fact_contract_v2/SEMANTIC_ENVELOPE.json)和[SIX_SEMANTIC_FACTS.json](semantic_fact_contract_v2/SIX_SEMANTIC_FACTS.json)。身份不取自模型自行声明，亦不由金额大小或列表位置猜测。

验证要求：数值跨度为完整原始数值Token；实体跨度必须是该数值所在数据行的首列单元格；角色跨度必须是同表对应列的首行表头单元格；三者原文及整份来源hash一致。缺字段、跨行/跨列错配、改写跨度或来源版本改变均拒绝。目前明确支持具有首行表头的HTML表格，不假装覆盖跨行/合并表头、OCR或任意文档结构。

|设施实体|授权金额及位置|已提款金额及位置|核验状态|
|---|---|---|---|
|Franklin, Kentucky Distribution Center|54.0 / 2987–2991|51.8 / 3001–3005|行名、两个列头、两数值来源均支持|
|Macon, Georgia Distribution Center|58.0 / 3084–3088|49.9 / 3098–3102|同上|
|Brentwood, Tennessee Store Support Center|78.0 / 3188–3192|75.3 / 3202–3206|同上|

原来的六项位置及语义要求来自独立公共来源审定。程序只将**已明确声明、经来源核验的绑定**与已经抽取出的原事实相连；不补造缺少的数值，不为缺少的语义声明推断身份。未匹配声明的事实不自动获取身份，不能用于要求该身份的表达式。million尺度原文包含在列头证据中，但未扩展现有自动单位换算器。

## 3. IR编译与表达式登记

[SEMANTIC_PLAN.json](semantic_fact_contract_v2/SEMANTIC_PLAN.json)用原Computation IR语义step ref声明每个表达式的entity_id及必需角色→来源binding_id。`compile_semantic`调用原`compile_computation`，再通过已有semantic_ref_map解析到Typed节点ID，并验证已声明facts生产者能提供对应来源。不添加事实生产者、表达式或计算节点。

编译断言确认：新wrapper返回的原图hash完全相同；envelope保留三个独立实体及各自两个列角色；接受spec绑定完整envelope哈希，缺该哈希的结果不能通过新版接受条件。

执行器输入同时包含全部合法上游facts及该节点`semantic_input_contract`。事实中的实体/角色对应关系可见；模型仍负责产出表达式。程序检查：原fact_id存在、来源/版本身份有效、实体为允许实体、角色绑定精确匹配、所有必需角色实际被引用。失败发生在`reference_bindings[u]`和`outputs[u]`写入前。

主要诊断：`SEMANTIC_ENTITY_MISMATCH`、`SEMANTIC_COLUMN_ROLE_MISMATCH`、`SEMANTIC_REQUIRED_ROLE_MISSING`、`SEMANTIC_REQUIRED_FACT_MISSING`、`SEMANTIC_IDENTITY_MISSING`、`SEMANTIC_IDENTITY_SOURCE_CONFLICT`、`SEMANTIC_SOURCE_SPAN`、`SEMANTIC_SOURCE_CHANGED`、`SEMANTIC_CACHE_IDENTITY_MISMATCH`。

来源身份及必需角色检查不等于全部数学语义认证：使用正确两事实却把减法顺序反转仍须原公开运算验收/独立任务评估识别。本次不增加公式推断器或自动改写表达式。

## 4. 原始真实负例回放

[HISTORICAL_RESPONSE_REPLAY.json](semantic_fact_contract_v2/HISTORICAL_RESPONSE_REPLAY.json)使用V2原始shared-1/2/3/4响应内容，未经修改，作为离线传输fixture。不是新的真实生成，也不是重新运行付费探针。

|节点与历史表达式|新版检查点|结果|
|---|---|---|
|Franklin：54−51.8对应原两ID|表达式登记前check_binding|DONE，可合法登记|
|Brentwood：错误引用Franklin两ID|表达式登记前check_binding|SEMANTIC_ENTITY_MISMATCH；未登记binding及输出；其计算节点blocked|
|Macon：错误引用Franklin两ID|表达式登记前check_binding|同上|
|合流|上游未完成|blocked，无最终答案；不自动替换引用|

本轮把“来源存在”与“来源属于本节点业务实体”分开检查，错误首次在Brentwood表达式登记处拦截，不再等到最终6.6验收才发现。

合法正例的模型响应由合成fixture提供，分别引用三设施正确ID；TypedExecutor实际执行其三次工具计算与合流，得到13.0，最终血统覆盖六个源事实。见[LEGAL_BRANCH_JOIN_STUB.json](semantic_fact_contract_v2/LEGAL_BRANCH_JOIN_STUB.json)。它只证明新版执行合同可用，不记为真实LLM成功。

## 5. 缓存与恢复

- fact_id仍保持原来源身份；新增语义元数据进入现有事实fingerprint/表达式snapshot。请求key增加完整envelope digest，恢复state_hash也绑定envelope。
- `_cache_guard`先验证实体/角色身份，再审查原来源和数值。旧缓存缺身份或版本不一致拒绝，绝不自动升级；与新版声明匹配的缓存保持合法。
- `TypedExecutor.run`遇到已有DONE状态同样验证语义缓存；不只保护JointRecovery入口。拒绝写入`SEMANTIC_CACHE_REJECTED`审计事件，不派发新调用。
- LOCAL合法受控JSON故障：3节点闭包、5个DONE复用、仅1个新增Mock模型调用，合流13.0。
- FULL：新实例接收同一envelope，原图、依赖及模型π保留。
- NONE：不产生调用。
- 缺原始事实报`SEMANTIC_REQUIRED_FACT_MISSING`；现有LOCAL/FULL仍拒绝这类失效。新跨设施语义错误也没有被擅自加入恢复白名单，必须作为观测错误保留，不能用“可恢复”绕过保护。

## 6. 回归、版本与文件哈希

最终[REGRESSION_CURRENT_CODE.txt](semantic_fact_contract_v2/REGRESSION_CURRENT_CODE.txt)：**566/566通过，0 failures，0 errors**，其中20项语义专项；覆盖单链、分叉合流、原NONE/LOCAL/FULL、旧预算与异常约束。测试全程socket及进程启动被阻断。

首次直接使用原历史包做全量回归出现16项FROZEN_HASH_MISMATCH（保留在[FULL_REGRESSION_OUTPUT.txt](semantic_fact_contract_v2/FULL_REGRESSION_OUTPUT.txt)）：原因是授权的新源码不同于原包冻结源码，旧入口正确拒绝。不能改写历史manifest让它“通过”。后续仅在临时Mock工件中绑定当前源码、复测旧协议行为，故最终全通过是**当前代码兼容性回归**，不是旧真实包在新源码下仍可运行的声明。

129项原V2工件/真实日志审计前后哈希一致，原失败结果仍是6.6、task_success=false。被修改的3份生产源码改前字节已保存在SOURCE_BEFORE，且每份与原V2manifest中对应源码hash相符；详见[SOURCE_VERSION_AUDIT.json](semantic_fact_contract_v2/SOURCE_VERSION_AUDIT.json)。旧源码冻结身份与新代码版本分列。

新工件manifest SHA256：`6078b39ae2fecb0880bf7496f0453e29be0c2fd34509efdd06f9a812dd94d5af`。运行工件/源码身份见[MANIFEST.json](semantic_fact_contract_v2/MANIFEST.json)。报告、回放日志、回归及历史哈希身份见单独EVIDENCE_INDEX。

## 7. 下一次真实试验的具体阻塞

**事实语义合同的离线接线已完成。真实试验仍需新版独立启动器显式读取并传入semantic_envelope，绑定其接受spec，并冻结增加语义字段后的完整请求、配额和费用风险授权。** 原V2的run_probe入口没有该参数，且其旧manifest已因源码版本改变拒绝运行；不得重跑它或静默沿用其已耗尽授权。

此外需明确新语义失效的安全停止路径：现有恢复白名单只允许LLM输出格式失效，不能默认LOCAL会修复跨设施错选。可以先验证新合同拒绝/正确执行，不把这自动称为成功动态恢复。D继续UNKNOWN，正式配对仍NO-GO；质量概率/P90与调度收益不由本次测试建立。

本轮到此停止，未启动真实模型、未改原图或历史Gold、未修改奖励/预测器、未提交Git。
