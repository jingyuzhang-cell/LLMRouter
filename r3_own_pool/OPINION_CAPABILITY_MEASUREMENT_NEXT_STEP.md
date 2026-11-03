# 舆情DAG：结束合同迭代，进入独立节点能力测量

结论：**独立测量技术READY，付费执行HOLD**。保留P7证据ID合同，不修改Prompt、Schema、评分、目录、原图、旧判定及ZCODE。本轮0真实API、0GPU、无Git提交。新文件位于 `opinion_independent_capability_v1/`。

## 1. 单位边界及独立语义错误

123.48所选单位ID `ev_e0e697c6906967ff503ce708` 为第2页[726,1089)，包含金额和年度说明，没有完整“万元”。相邻 `ev_c328d298d0aa3632f36ff5c5` 为[353,726)，包含“（万元）”及年度交易表头；模型已把后者选为role，却未用于unit。**边界将表头与部分数值分开，但原文未遗漏，多个ID可以明确组合；未发现无法表达正确证据的目录缺陷。当前是单位证据选择失败。** 分段是否增加错误率仍UNKNOWN，单次输出不能证明其因果效应；冻结目录不改。

两个独立语义错误另存 `BOUNDARY_AND_SEMANTIC_ERRORS.json`：

- fact_19：9,222.97来自“应付账款”行，却声明actual_transaction_amount。数字可定位不使余额变成交易额。正式第一错误仍是单位证据失败，独立角色错误不取代旧记录。
- fact_1：原文2023年年度交易被写为2023-01-01，无依据增加月日精度。这不是金额定位成功能够证明的时间事实。

P7真实结果保持：1请求、HTTP200、原生Schema通过、完整合同拒绝、0登记；5,674输入+7,939输出=13,613 Token，API56.925秒，客户端58.889秒，费用待核验。新索引保留原P7协议冻结与该次原始运行证据，不回填成功。

## 2. 现有真实数据，不混版本排名

`HISTORICAL_OBSERVATIONS.jsonl`收录17次舆情节点请求：当前四模型16次，另含已退役glm-5.3-flash的1次账户错误。排除权限探针、KDX/ST及其他恢复实验；不是全项目所有付费请求总账。15次有usage，已知Token小计120,213；2次usage未知，不能当零费用。

|请求模型|次数|节点覆盖|已知Token小计|usage未知|
|---|---:|---|---:|---:|
|qwen-plus|4|仅extract_current|22,729|0|
|deepseek-flash|2|仅extract_current|8,904|0|
|glm-5.3|1|仅extract_current|5,228|0|
|qwen-flash|9|current 3、media 2、history 2、reconcile 2|83,352|1|
|glm-5.3-flash（退役）|1|current账户错误|无已知usage|1|

所有现金费用待账单核验；HTTP429/1113是账户/服务可用性事件，不计为模型事实质量失败。Qwen-Flash超时的远端完成状态未知。assess/report没有真实能力观测。现有样本集中于一个事件、多版本，不能解释为17个独立任务。

可比性以实际REQUEST messages规范化hash、输出上限、合同/评价器、输入和来源核查，不只看记录里版本名：

1. `opinion_three_model_extract_v1/REAL_RUN_20261015_095709` 的Qwen/DeepSeek：同messages、同quote-v1+adapter、同1024上限，是一组同任务配置对照；原Qwen适配通过、DeepSeek Schema拒绝均保留。
2. `opinion_node_capability_matrix_budget_v2/REAL_RUN_20261015_105218` 的Qwen/DeepSeek/GLM：同messages hash `66a96562…`、同16,384上限、同评价器，可作该冻结条件下的配对探索。Qwen通过适配；另两者日期等拒绝不改。
3. `qwen_flash_v3_execution_v1/REAL_RUN_20261015_123945` 的current实际messages同为 `66a96562…`，也调用旧同一measurement.evaluate。记录中的prompt_hash不同来自带空格/紧凑序列化差异，不改旧hash。它可补充第2组的**输入/评价协议等价**比较，但跨运行时段、未随机，不能算同时段严格时延配对。
4. 第2组GLM启用thinking-low，Qwen/DeepSeek非思考；是配置服务对照，不是只改变模型权重的因果实验。动态模型别名不证明固定权重。
5. 最早4096截断、单独quote探针、P6全节点quote、P7证据ID不能混成同协议矩阵。单独旧探针与后续adapter即便输入相似，正式合同判定也不可直接合并。P7只有Qwen-Flash一条，无新版跨模型配对。

完整逐请求输入、合同、参数、Token、时延、失败、UNKNOWN与证据路径见JSONL及 `COMPARABILITY.json`。本轮不重评分旧模型输出。

## 3. 独立单格模式与端到端模式分开

新 `START.py`只改变测量调度政策，直接复用冻结P7 core/Schema/Prompt/证据目录/质量函数。

- 每格创建新验证状态。抽取节点使用同一冻结来源；下游使用冻结、来源核验的人工/确定性Stub上游状态，并标注来源，不称为真实LLM上游。
- 六节点均可构造各自合法祖先状态；生成的候选、失败输出和缓存绝不供给下一测量格。新启动器只开放最小两格，不自动跑24格。
- 单格JSON、Schema、证据、角色、期间失败及输出长度截断，保存为质量/合同可用性观测，继续下一个预登记独立格；不补齐、不换模型、不重试。
- 账户/HTTP异常、身份不明、usage未知、输出预算违反、请求超时、全局截止、冻结/文档完整性变化、未分类系统错误仍停止。异常未知项保留UNKNOWN，不冒充普通模型质量失败继续派发。
- 真实端到端DAG仍采用原严格停止和阻断下游规则，本次没有改动该执行路径。
- 单格全部失败也可以形成完整能力观测批；“所有合同通过”不是采集成功标准。

5/5必要离线检查通过：两个质量拒绝均落盘且完成两格；账户/身份/源版本错误停止；原请求逐项不变；全部六节点Prompt仍等于冻结版本；状态及失败输出不串格。仅假传输，不重复数百项回归。

## 4. 指标分别输出

1. 合同可用率：按预登记单元保留原生Schema、适配Schema、完整guard及截断状态；账户/未知状态单列，同时报告总派发数与有输出分母，不偷偷删掉失败。
2. 可验证事实质量：保存原冻结verified指标、限定L1分子/分母及作用域。ID存在、数值命中、别名命中均不是完整事实正确性。
3. proxy和UNKNOWN：自由主张、风险、完整召回和无法判定语义保持null及缺失mask；不合成0/1质量。P7“期间”局部指标只匹配年度，不证明其生成的精确月日正确。
4. C：input/output、cache/reasoning usage、未知占额、费用及账单状态独立保存。账单未核验不报实际现金。
5. L：客户端API roundtrip、单格墙钟、整批墙钟分开；不称远端推理时间，也不是恢复剩余时间或P90。

## 5. 唯一下一轮：同节点两模型，不重复Qwen-Flash探针

最小测量单元：`extract_current × {qwen-plus, deepseek-flash}`，各一次，**最多2请求**。使用原P7任务、原messages、原Schema/guard/评分；固定种子20261015产生预登记顺序，执行前已写入PROTOCOL。两格互不依赖，第一格普通合同拒绝不阻止第二格。

每请求最大16,384输出Token，合计32,768；单请求120秒，完整客户端600秒，60秒保存预留。D仍UNKNOWN，600秒不是任务期限。无额外规划/评审/修复/权限探针。不同厂商的Token化和服务版本差异记录在案，两者均为冻结非思考配置。

输入Token及现金严格上界仍未认证；请求序列化字节数只作为体积证据，不冒充Token上界。不自动充值，不以墙钟代表费用上限。**需要独立两请求付费、载荷出站、凭据认证及不确定费用授权**；已有P7授权已使用，不能续用。

无需网络的技术命令：

```bash
python -B /root/r3_own_pool/opinion_independent_capability_v1/START.py --mode two-model-current
```

新授权另存批准文件后才可执行：

```bash
python -B /root/r3_own_pool/opinion_independent_capability_v1/START.py --execute --mode two-model-current --authorization /root/r3_own_pool/opinion_independent_capability_v1/APPROVED_AUTHORIZATION.json
```

模板approved=false，不是授权证据。新冻结hash保存在该目录FREEZE_MANIFEST.sha256。本轮未发送这些请求，不要求现在批准。

## 6. 如何服务分配与调度

导出契约在 `SCHEDULER_DATA_CONTRACT.json`：按事件/节点/模型/输入/合同/目录/来源及参数连接，保留质量向量、分母、missingness、Token、费用状态、时延及失败类型。

静态分配先仅在同协议同输入已观测单元内比较可用性与已识别Q/C/L，不把未知质量或费用填零后求最优。动态方法只能读取决策之前且排除当前事件/任务的反馈，不能用本题事后标签预测本题；本轮不更新生产先验、不修改调度算法。单事件少量数据不足以支持可靠质量/P90或路由收益，后续需独立事件验证。

**停止合同修补，冻结失败，下一步只做两模型同条件动作观测。技术准备已完成，付费执行保持HOLD。**
