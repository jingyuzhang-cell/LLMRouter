# 四模型×6节点：24请求成本审批与最终准入

审查日期：2026-10-15（北京时间）。本轮0付费API请求、0GPU，无账单或密钥读取，不修改ZCODE、deadline_reward_v1、joint_search_v1、原DAG或历史结果。

**结论：严格费用预算准入NO-GO，现金上界为UNBOUNDED_OR_UNVERIFIED。** 不能把3600秒墙钟或本地Token估算当费用上界。已完成逐请求估算、评分隔离和停止路径核查，并建立统一输出额度的新审批版本；技术入口可离线核验，不等于已获真实调用许可。

## 1. 四个实际请求ID及服务规格

|ID|官方端点|模式|上下文/最大服务输出|
|---|---|---|---|
|qwen-plus|https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions|非思考|1,000,000 / 32,768|
|deepseek-flash|https://api.deepseek.com/chat/completions|非思考|1M / 384K|
|glm-5.3|https://open.bigmodel.cn/api/paas/v4/chat/completions|强制思考，low|1M / 128K|
|glm-5.3-flash|同上智谱Chat端点|强制思考，low|1M / 128K|

依据：[Qwen官方模型/价格](https://help.aliyun.com/zh/model-studio/qwen-plus)、[DeepSeek官方规格/价格](https://api-docs.deepseek.com/quick_start/pricing/)、[GLM-5.3官方](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)、[GLM-5.3-Flash官方](https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5.3-flash)。本轮Flash页面已可读取，确认model code为glm-5.3-flash及文本参数与GLM-5.3相同。不是FlashX，不能替换为其他名字。

这是配置ID和官方支持，不是本账户本轮实际服务身份验证；没有调用模型列表或鉴权探针。返回model必须匹配白名单，服务版本/fingerprint按实际响应记录，无法固定的权重版本记UNKNOWN。GLM账户权限和余额没有在线认证，若运行时被拒则全批停止，不模拟或换端点。

六格节点依次为extract_current、extract_media、retrieve_history、reconcile、assess、report。前三执行来源抽取；reconcile执行原任务要求的语义范围核验，assess/report是分析与表达，不把确定性文件读取/跨度检查/单纯血统合并算作LLM节点。它们都对应现有图中语义职责，图和依赖未改。四供应商每个节点的实际消息相同；GLM思考模式与其他模型不同，仍为明确混杂。

## 2. Token估算依据及输出额度问题

使用本机缓存tiktoken的cl100k_base，对完整system/user messages的规范JSON序列化计数。禁止编码表网络下载。本编码既不是四个远端模型的官方Tokenizer，也没有服务端Chat模板和隐藏包装认证；数值仅为**统一可复算代理估计**，不是任何模型的硬上界，不能用相同估值冒充相同真实Token。

24请求输入估计合计 **293,508 Token**；每模型6请求估计73,377。按节点（每模型相同输入字面，不代表实际分词相同）：

|节点|每请求输入代理估计|4请求合计|
|---|---:|---:|
|extract_current|5,549|22,196|
|extract_media|3,008|12,032|
|retrieve_history|14,240|56,960|
|reconcile|16,569|66,276|
|assess|15,975|63,900|
|report|18,036|72,144|

原4096额度不具备合理完整输出依据：reconcile依法合同必须回传全部上游事实和主张，仅这部分紧凑序列化就36,473字节、约12,425个代理Token；既有合法完整reconcile样例约13,256，history样例约9,484。它们不是模型Tokenizer下的数学下界或所有合理答案上界，但足以识别原预算的明显截断风险。extract_current旧全字段样例不是新版轻量合同合法输出，不用其2418代理Token冒充新合同需求；既有真实轻量输出508/530仅是观测。

仅改输出预算，建立 **opinion_node_capability_matrix_budget_v2**：全部24请求统一max_tokens=16,384，输出配置占额合计 **393,216**（每模型98,304），不在执行中按模型调整。原v1 SHA256 5955c269465a56f1d55ffd2e64284da3493b7a989873a48a4eff766927ef27af保持不变。原Prompt、输入、事实、合同、质量规则和模型参数除max_tokens外逐项相等。16,384小于所有已公布服务输出上限；估计输入+输出远低于上下文，但完整输入未认证，不能作严格上下文证明。思考占额、开放答案长度和120秒超时仍可能导致截断，照实计为失败，不保证全格成功。

## 3. 已核实费率与未核实项目

- Qwen：北京、非思考、输入不超过128K的公开原价为输入 **CNY 0.8/M**、输出 **CNY 2/M**。情景估算按该档、无缓存优惠；若真实输入跨档，单价改变。账户折扣、赠额及真实账单未核验。
- DeepSeek：公开高峰缓存未命中价为输入 **USD 0.30/M**、输出 **USD 1.20/M**；非高峰为0.15/0.60。用较高档估算，不假定缓存折扣，不转换成人民币。时段按官方UTC规则，真实账单另核。
- 两项GLM：官方规格可查，但[官方价格页](https://open.bigmodel.cn/pricing)本轮只取得页面空壳，未获得可复核的绝对数值。Flash页面只有相对价比说明，不足以推出绝对费率。第三方所列8/28或0.8/2.8等没有作为已核实价格或预算依据。单价、情景费及硬费用上界均保留UNVERIFIED。

下表费用是**输入代理估计+输出达到16384时的条件情景估算**，并非真正最坏现金上界；每行严格上界均为UNBOUNDED_OR_UNVERIFIED。所有单价为每百万Token。

|#|node_id|model_id|输入估计|输出上限|输入价/输出价|币种|高输出情景估算|严格费用上界|
|---:|---|---|---:|---:|---|---|---:|---|
|1|extract_current|qwen-plus|5549|16384|0.8/2|CNY|0.0372072|UNVERIFIED|
|2|extract_current|deepseek-flash|5549|16384|0.3/1.2|USD|0.0213255|UNVERIFIED|
|3|extract_current|glm-5.3|5549|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|4|extract_current|glm-5.3-flash|5549|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|5|extract_media|deepseek-flash|3008|16384|0.3/1.2|USD|0.0205632|UNVERIFIED|
|6|extract_media|glm-5.3|3008|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|7|extract_media|glm-5.3-flash|3008|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|8|extract_media|qwen-plus|3008|16384|0.8/2|CNY|0.0351744|UNVERIFIED|
|9|retrieve_history|glm-5.3|14240|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|10|retrieve_history|glm-5.3-flash|14240|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|11|retrieve_history|qwen-plus|14240|16384|0.8/2|CNY|0.0441600|UNVERIFIED|
|12|retrieve_history|deepseek-flash|14240|16384|0.3/1.2|USD|0.0239328|UNVERIFIED|
|13|reconcile|glm-5.3-flash|16569|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|14|reconcile|qwen-plus|16569|16384|0.8/2|CNY|0.0460232|UNVERIFIED|
|15|reconcile|deepseek-flash|16569|16384|0.3/1.2|USD|0.0246315|UNVERIFIED|
|16|reconcile|glm-5.3|16569|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|17|assess|qwen-plus|15975|16384|0.8/2|CNY|0.0455480|UNVERIFIED|
|18|assess|deepseek-flash|15975|16384|0.3/1.2|USD|0.0244533|UNVERIFIED|
|19|assess|glm-5.3|15975|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|20|assess|glm-5.3-flash|15975|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|21|report|deepseek-flash|18036|16384|0.3/1.2|USD|0.0250716|UNVERIFIED|
|22|report|glm-5.3|18036|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|23|report|glm-5.3-flash|18036|16384|UNVERIFIED|CNY|UNVERIFIED|UNVERIFIED|
|24|report|qwen-plus|18036|16384|0.8/2|CNY|0.0471968|UNVERIFIED|

### 按模型和节点汇总

|模型|请求数|输入估计|输出额度|条件情景合计|
|---|---:|---:|---:|---|
|qwen-plus|6|73,377|98,304|CNY 0.2553096|
|deepseek-flash|6|73,377|98,304|USD 0.1399779|
|glm-5.3|6|73,377|98,304|UNVERIFIED|
|glm-5.3-flash|6|73,377|98,304|UNVERIFIED|

没有将人民币和美元相加，也没有把未知GLM价格当0；**全实验费用总计和硬上界均不能认证**。按节点四请求的已知部分情景如下，均另有两项GLM未知费用：

|节点|Qwen CNY|DeepSeek USD|两项GLM|
|---|---:|---:|---|
|extract_current|0.0372072|0.0213255|UNVERIFIED|
|extract_media|0.0351744|0.0205632|UNVERIFIED|
|retrieve_history|0.0441600|0.0239328|UNVERIFIED|
|reconcile|0.0460232|0.0246315|UNVERIFIED|
|assess|0.0455480|0.0244533|UNVERIFIED|
|report|0.0471968|0.0250716|UNVERIFIED|


## 4. 独立参考隔离与Q的可识别性

实际检查24个请求的完整JSON，包括嵌套user和context JSON：没有L1参考集合对象、reference_id、评分字段或期待目标输出对象。原公告自然含正确数字，是合法抽取输入，不能将这种必要来源误报为泄漏。参考仅由measurement在收到响应后载入。下游共同前置状态来自已披露的人工Stub输入，含合法源事实/UNKNOWN关系与受限assessment，是条件输入，不是该目标的Gold；不能据此声称测量了无参考上游的完整DAG。

请求只有system/user消息，无工具访问评分文件、无previous_response_id/显式cache_id；每格独立Guard，无跨模型结果缓存或生成器注入参考。本地序列化路径未发现评分答案泄漏。不能检查提供方隐藏系统Prompt、训练记忆或内部缓存状态，因此不声称这些已被排除。自动提供方缓存usage如实保存，不把缓存命中认定为已发生答案泄漏。

|节点|可独立核验|proxy/UNKNOWN|
|---|---|---|
|extract_current|限定参考匹配的实体/金额/单位/角色/落款日期；原文跨度和材料截止|期间未输出或不唯一时UNKNOWN；22项范围外recall/precision和世界真值UNKNOWN|
|extract_media|引用、来源及材料时间合法性|主张含义、类型、媒体归属多为proxy；事实真假UNKNOWN|
|retrieve_history|来源及数值字面、引用版本|完整范围/期间/预计与实际语义多为proxy，未有完整独立参考|
|reconcile|已知ID、上游数据连续性、引用存在性|支持/矛盾分类正确性UNKNOWN，范围差异仅代理|
|assess|ID和来源存在|支持充分性、风险严重程度、未来影响UNKNOWN|
|report|引用有效、上游ID及覆盖代理|报告整体正确性、语义支持和主观质量UNKNOWN|

raw_schema_pass、adapted_schema_pass、evidence_guard_pass继续分列；UNKNOWN不填成0/1或模型先验。没有任务级可靠Q总分，不能直接用这些代理相加求“最优DAG分配”。本轮仅准备采集，不执行任何调度优化。

## 5. 运行与停止机制

新版本保留原运行代码字节不变，预算只改配置；新增START.py作为一键父进程超时及全24格状态收口：

1. 默认离线，不读密钥；执行必须有新版本匹配的独立授权JSON。旧3请求授权不适用。
2. 独立cell、最多24请求、每格一次、请求120秒、全客户端计划上限3600秒，保存前预留60秒；父进程最多给自有子进程3540秒，超时只终止它，不操作其他实验。
3. 派发前fsync预算/请求占额；max_tokens由服务请求限制，未知usage保留UNKNOWN，不记零。没有完整输入/现金硬门禁，不能宣称StrictMeter认证或总费用受硬上限保护。
4. 格式、Schema、证据失败照常保留，可继续其他独立格；网络、账户、身份、资源及不可恢复异常停止全批。绝不修正事实、不重试、不按模型改输入。
5. 原始HTTP及模型正文、usage、身份、时延和费用待核验状态均保存。单次失败与NOT_EXECUTED分列；崩溃时有PENDING记录的格记IN_FLIGHT_OR_UNKNOWN，不能记为零调用/零费用。
6. 客户端/父进程截止不能保证远端取消，UNKNOWN债务及永久claim保留，禁止自动重启。同一授权包不能重新派发。
7. 费用核账需要授权账户账单，以request_id/UTC/模型匹配；未取得匹配账单始终PENDING，不通过任何其他模型调用补齐。

父进程时间控制只约束客户端受控工作，不能证明远端计算绝对按时结束。3600秒不提供现金上限。目录及冻结核验、参数一致性断言、START/RUN/measurement语法检查已完成；未新增模型实验或运行整套回归。

## 6. 正式运行技术与预算裁决

- **技术**：四请求ID和API规格已有官方依据；原接线可复用，新统一额度在规格内。账户实际可用性/完整输入与思考输出空间仍须以首次真实结果验证，不预先承诺成功。
- **预算**：NO-GO。唯一核心预算阻塞是**无法形成可信可执行的全实验现金上界**：两项GLM绝对单价未官方核实，四供应商完整计费输入无认证，程序也没有现金封顶。已知部分估算不是全局预算。
- **独立探索**：如人工愿意明确承担新24请求、16384输出及未知GLM价格/输入费用风险，可另行批准此版本；即使批准，也仍不能把预算状态改称已认证安全。本轮没有这样的授权。

零调用准入命令：

```bash
python /root/r3_own_pool/opinion_node_capability_matrix_budget_v2/START.py
```

未来获批后：按AUTHORIZATION_TEMPLATE.json创建独立外部授权文件，必须填写新FREEZE_MANIFEST.json的SHA256、approved=true、exploratory_fee_risk_accepted=true、unverified_glm_prices_accepted=true，以及24请求、16384输出/请求、3600秒和四模型列表。唯一支持的一键命令：

```bash
python /root/r3_own_pool/opinion_node_capability_matrix_budget_v2/START.py --execute --authorization /absolute/path/to/approved_authorization.json
```

不要沿用旧4096版本启动命令或旧冻结哈希。新模板默认false，本轮未生成任何有效付费授权、LAUNCH_CLAIM或DISPATCH_CLAIM。

明细与汇总文件：COST_AND_ADMISSION.json、PER_REQUEST_BUDGET.csv、BUDGET_ONLY_CHANGE.json。新冻结清单将本报告和原准备包身份一起绑定；没有修改ZCODE审查文件、核心调度、联合搜索或任何其他Agent分支。
