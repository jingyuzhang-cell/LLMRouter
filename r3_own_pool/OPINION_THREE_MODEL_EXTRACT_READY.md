# 三模型 extract_current 云端单节点执行准备

结论：**READY（独立探索性协议与代码准备就绪；未获本批付费授权，0次真实请求）**。这不是三端点已完成在线鉴权或余额验证，也不是完全同推理模式的确认性能力比较。任何执行前凭据、文件或预算门禁失败均不得派发。

## 1. 实际模型及参数

|请求模型ID|实际端点|认证变量|冻结专属参数|
|---|---|---|---|
|qwen-plus|https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions|DASHSCOPE_API_KEY|enable_thinking=false|
|deepseek-flash|https://api.deepseek.com/chat/completions|DEEPSEEK_API_KEY|thinking.type=disabled|
|glm-5.3|https://open.bigmodel.cn/api/paas/v4/chat/completions|ZHIPU_API_KEY|thinking.type=enabled，reasoning_effort=low|

三者均冻结 temperature=0、stream=false、max_tokens=1024、response_format=json_object；JSON模式不替代客户端完整Schema与证据验证。使用requests直接序列化HTTP，不依赖SDK默认补充参数，禁止重试、重定向与localhost回退。完整脱敏请求在 `opinion_three_model_extract_v1/REQUESTS.json`，包含实际system/user全文，未保存密钥。

官方依据：

- [阿里云结构化输出](https://help.aliyun.com/zh/model-studio/qwen-structured-output)：JSON Object模式。本次Qwen参数同时与已完成的真实单节点请求逐项一致。
- [DeepSeek JSON输出](https://api-docs.deepseek.com/guides/json_mode/)与[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)：明确deepseek-flash、json_object和disabled映射。空输出仍可能发生，届时停止，不重试。
- [智谱GLM-5.3模型页](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)：官方请求模型ID为小写glm-5.3，支持Chat端点，思考始终开启；不能发送disabled。原项目大写GLM-5.3/Anthropic配置原样保留。本批独立迁移到官方Chat端点，避免文档所述某些订阅账户只能调用Chat的限制。
- [智谱结构化输出](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output)：json_object参数；GLM-5.3模型页列出该能力，但教程例子使用glm-5.2。GLM-5.3在本账户对此参数的实际接受情况未在线验证；发生参数拒绝即保存并停止，不临时改请求。

**身份边界**：以上是冻结的请求ID及官方协议依据，不是本轮服务端身份实测。派发后记录实际返回model、fingerprint、原始usage和时间；返回身份不在冻结白名单则停止，不由模型自称身份。别名背后的权重版本无法离线固定，记UNKNOWN_UNLESS_REPORTED。认证变量映射已检查，本轮未读凭据、未查询账户；未来明确授权后，仅内存读取允许变量，所有模型缺任一凭据则在首次请求前停止。账户权限与余额保持UNKNOWN；首个API拒绝不重试。

## 2. 固定对象与公平边界

复用原冻结事件、extract_current节点、来源六个窗口、截止时间、任务目标、Schema、quote守卫及其质量口径。不修改原DAG和Contract V2。三臂system/user消息字面相等，分别保存请求体，canonical messages哈希记录为prompt_hash。模型不能读取其他模型输出，没有共享客户端缓存或可变事实登记状态；每臂独立实例化验证器。服务端自动缓存不能强行关闭，保留usage中的缓存字段作为成本差异来源。

模型顺序预登记为Qwen→DeepSeek→GLM，不按本次结果改顺序。一次事件、每臂一次，仅为部署配置的描述性对照，受时段/顺序、分词器、提供方缓存、GLM思考模式等混杂影响。相同max_tokens不代表相同可见答案空间：GLM可能把额度用于思考并截断；记录思考存在性和usage细节，不为它暗增额度。temperature参数相同也不保证跨服务商采样机制相同。不能据此断言稳定能力排序或路由收益。

旧Qwen真实样本的消息和请求体与新Qwen完全一致，但模型权重版本无法核实一致，且旧结果已用于适配开发。`HISTORICAL_COMPARABILITY.json`明确将其排除出新的前瞻三臂分母。原CONTRACT_REJECTED和后续影子结果分列；本批需要重新采集Qwen一次，不能以影子回放代替新真实臂。

## 3. 已接入的真实接收调用链

`RUN.py --execute` → 全冻结文件和真实来源核验 → 独立授权范围核验 → 三供应商凭据存在性检查 → 排他持久化派发claim → 逐臂持久化请求与预留 → 官方HTTP → 保存原始响应及原始正文 → `adapter.receive` → 原生Schema → 仅允许裸对象数组封装 → 适配Schema → 冻结QuoteValidator → 原子候选登记 → 独立确定性指标审计。

原始正文不修改、不纠正quote/实体/字段/金额。每臂保存raw_schema_pass、adapted_schema_pass、evidence_guard_pass、adaptation_type、transport_format_violation；格式适配成功不记为模型原生成功。任何Schema、来源、身份、请求或合同失败停止整批；保留未执行模型，不能为凑齐三臂追加请求。没有下游节点、恢复或LLM评审调用。

## 4. Q/C/L记录与未知项

每臂独立目录保存REQUEST、原始RESPONSE.bin/json、RAW_MODEL_OUTPUT、ADAPTER_RESULT、RECORD；全局CALL_LEDGER采用fsync，派发前记录完整占额状态；使用永久claim阻止崩溃后重复启动或续跑。record包含请求/实际模型、prompt_hash、版本、Token、原始usage、API往返、节点接收/校验墙钟、费用状态、合同结果、候选数量和第一失败原因。

- 可确定性核验：来源存在及版本、quote精确唯一定位、字面数值支持、来源信息截止有效性。它们不是世界事实真值。
- proxy：实体与来源注册表一致、field_role词面支持、格式合规、非法候选比例。程序未证明所有交易对手/表格列归属；不得将entity一致性扩大为完整事实语义正确率。
- UNKNOWN：fact precision/recall、语义完整性、期间/列口径、主观风险及未来影响；不新增人工Gold、不调用模型自评。
- C：记录真实usage，实际费用保持PENDING_ACCOUNT_BILL_VERIFICATION；不将零/猜测价格填作实际账单。费用核验须另有账户账单只读权限，按request_id/UTC、模型和账单窗口匹配，匹配不到保持待核验。
- L：单调时钟测客户端持续时间，UTC记录事件。API往返包含网络与远端排队，不冒充服务端纯推理时延；该值UNKNOWN。客户端超时不证明远程已取消，完成/费用未知继续保留。

## 5. 冻结资源信封（等待独立审批）

- 最多3次真实生成，各模型最多1次；每请求max_tokens=1024，配置输出额度合计3072。
- 单请求客户端截止120秒；完整启动器480秒，自启动准入开始计时，包含验证、请求和保存；每派发前检查至少150秒剩余（120请求+30结束预留）。三请求上限360秒+30预留=390秒，余90秒供前置核验及本地处理。未用额度不转成追加调用。
- 输入Token完整上界及实际费用上界仍**未认证**。历史Qwen输入3855只作单次观测，不迁移为其他模型上界；本轮未使用别家Tokenizer冒充认证。
- 未知usage记UNKNOWN而非0；派发预留不因异常撤销；客户端停止后远端取消情况未知。不使用或修改正式StrictMeter，不宣称严格云端Token/费用硬预算。
- 无额外计数、规划、修复、模型评审、模型列表或健康检查请求；不启动GPU。

## 6. 必要离线验证

7/7通过，仅验证本次新增路径：三请求消息和额度一致、三臂FakeSession均进入实际适配器、原生失败与适配成功分列、合同失败立即停止、不获授权不读取凭据也不请求、缺凭据不派发、重复claim不启动、历史样本排除。FakeSession中使用历史数组作为测试输入，不是真实三模型结果。

`TEST_OUTPUT.txt`保留原始测试结果。旧quote包、适配器、Contract V2、原DAG及真实响应的全部清单项重核无变化。

## 7. 启动命令与最终门禁

零调用检查（默认不读取凭据）：

```bash
python /root/r3_own_pool/opinion_three_model_extract_v1/RUN.py
```

只有另获明确付费授权后，独立创建授权JSON，按 `AUTHORIZATION_TEMPLATE.json`填写approved、费用风险接受、实际冻结清单SHA256及固定3请求/1024/480秒范围，再使用：

```bash
python /root/r3_own_pool/opinion_three_model_extract_v1/RUN.py --execute --authorization /absolute/path/to/approved_authorization.json
```

模板默认approved=false，不能启动；本轮没有创建有效授权、读取密钥或派发claim。

**技术准备READY；真实执行HOLD，等待本批独立付费授权以及派发前凭据/账户实际响应检查。** 不能保证未调用的远端账户一定可用；参数拒绝属于应记录的真实失败，不允许退回旧接口、换模型或修改Prompt继续跑。当前没有需继续开发的顶层接收接口阻塞。完整6节点DAG下游合同迁移不属于本次范围，本轮完成后停止。
