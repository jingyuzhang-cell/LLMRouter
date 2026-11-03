# 四模型×六节点统一证据ID能力矩阵：一次性执行计划

**技术准备READY；真实付费执行HOLD，等待本次完整矩阵费用与范围授权。** 本轮0模型/账户API请求、0GPU、未修改历史结果、原合同、DAG、ZCODE或调度算法。公开价格文档只读查询不属于模型调用。

新目录：`opinion_capability_matrix_id_v1/`。目标是完整24格矩阵，采集成功指预登记格子均有明确观测或已批准的全局停止证据，不要求24格合同全部通过。

## 1. 固定对象与24格清单

证据合同保持 `OPINION_EVIDENCE_ID_V1`，原P7协议冻结 `7621b5e3e821292bf7863d7f4325d918c71b9d53d1f3ec41a897a553223146a6` 不变。图、72片段目录、来源、信息截止、Schema、语义守卫、质量函数及Prompt不改。

|实际节点ID|qwen-flash|qwen-plus|deepseek-flash|glm-5.3|每格输出上限|
|---|---|---|---|---|---:|
|extract_current|复用正式失败|复用正式失败|复用正式失败|新增|16,384|
|extract_media|新增|新增|新增|新增|16,384|
|retrieve_history|新增|新增|新增|新增|16,384|
|reconcile|新增|新增|新增|新增|4,096|
|assess|新增|新增|新增|新增|4,096|
|report|新增|新增|新增|新增|4,096|

六节点都是本次真实LLM条件化测量单元；资料读取、ID定位、引用核验、Schema和质量检查由程序执行，不另调用LLM。逐格输入体积、Token代理、输出、价格、费用、执行动作与顺序见 `EXECUTION_LIST.csv` / `CELL_BUDGETS.json`。`FULL_CELL_TEMPLATES.json`为24格原冻结模板；`REQUEST_MATRIX.json`仅含缺失的21格。

每格创建独立验证状态。三个抽取节点使用固定来源；reconcile/assess/report从合法、来源核验的冻结人工/确定性Stub祖先构建状态。其来源明确标注，不冒充真实上游LLM。每格消息在同一节点四模型间一致，候选模型及思考参数映射是唯一供应商差别；当前单格输出不进入其他格。

## 2. 复用审计：24格已有3格，不重新付费

|复用格|原始运行|原始正式结果|
|---|---|---|
|extract_current / qwen-flash|P7 `REAL_RUN_20261015_153335`|UNIT_SOURCE_UNSUPPORTED|
|extract_current / qwen-plus|独立测量 `REAL_RUN_20261016_011013`|FIELD_ROLE_SCOPE_UNSUPPORTED|
|extract_current / deepseek-flash|同上|UNIT_SOURCE_UNSUPPORTED|

`REUSE_AUDIT.json`确认三条真实REQUEST与P7对应冻结body逐项相等；消息、Schema、目录/来源、模型配置、输出上限、120秒请求参数相同。冻结守卫只读重放的Schema、guard、首错及质量向量与原记录完全一致。原记录hash锁定，不回填成功，不把旧费用计入本轮新增调用费用。

这是**合同/输入/评分版本严格匹配的历史观测复用**，不是同时间随机配对：三条保留原时间、输出、模型返回身份、指纹及原运行策略。P7当时全批首错停止不改变其已完成单格的输入和评分，但不能隐去批次差别。模型别名不能证明权重固定；即使新跑24次也不能凭别名宣称固定权重。最终表必须标记HISTORICAL_REUSE或NEW_API，不把这些观测伪装为同期新调用。

旧quote/offset合同、GLM旧抽取响应、早期截断及权限探针不符合P7同输入/合同条件，全部排除本矩阵。当前 `MATRIX_INITIAL.json` 如实为：3条已观测失败，21格NOT_EXECUTED，成功0。

因此默认方案为：**复用3格正式失败，单次获批后补齐21格**。不自动重复这3格，也不自动退回零散Pilot。

## 3. 模型、来源与参数

|实际请求模型ID|真实端点|思考配置|
|---|---|---|
|qwen-flash|https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions|enable_thinking=false|
|qwen-plus|同上|enable_thinking=false|
|deepseek-flash|https://api.deepseek.com/chat/completions|thinking.type=disabled|
|glm-5.3|https://open.bigmodel.cn/api/paas/v4/chat/completions|thinking.type=enabled, reasoning_effort=low|

temperature=0，response_format=json_object，stream=false，max_tokens见表。GLM不能禁用思考，保留冻结配置，不暗改指令；对照是配置服务，不是只变权重的因果试验。[GLM官方配置说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)。reasoning/cache usage原样保存，不漏记为免费。

使用已有对应DASHSCOPE_API_KEY、DEEPSEEK_API_KEY、ZHIPU_API_KEY，仅在内存中认证，日志只保留安全指纹。准备阶段未读取凭据、查询账户余额或发送权限探针；不能保证GLM账户在执行时可用。权限、余额/资源包、429或其他HTTP异常按全局规则停止，不切端点规避收费，不充值或购买资源包，不模拟输出。

## 4. Token预算与费用估算

输出预算保持P7不变，不按某个模型是否通过调整：全24格参数上限245,760输出Token；扣除3条复用格的原参数占额后，本轮**最多21新增请求、196,608输出Token**。旧3格真实已耗Token为历史消耗，不重新占新增派发数。

完整服务端输入Token上界仍未认证。代理采用本地cl100k_base对序列化messages计数，**不是四个服务端匹配的Tokenizer，也不覆盖已认证Chat封装开销**。逐格同时提供真实UTF-8体积。完整24格代理240,552 Token；新增21格代理219,366 Token。均不是硬上界。

新增请求前的估算输入预留=`ceil(2×代理+1024)`；合计460,236。这是预算敏感性余量，不是认证Token界，不能改名为硬预算。收到usage后按实际Token重新估算，超过预留时停止后续派发；不能撤回已经发生的账单。

公开单价（每百万Token，缓存未命中）：

|模型|输入|输出|条件/依据|
|---|---:|---:|---|
|qwen-flash|¥0.15|¥1.5|北京、输入≤128K；更高输入阶梯另计，[官方价格](https://help.aliyun.com/zh/model-studio/qwen-flash)|
|qwen-plus|¥0.8|¥2|北京、非思考、输入≤128K；更高阶梯另计，[官方价格](https://help.aliyun.com/zh/model-studio/qwen-plus)|
|deepseek-flash|US$0.30|US$1.20|采用峰时未命中价作估算，非峰时更低，[官方价格](https://api-docs.deepseek.com/quick_start/pricing/)|
|glm-5.3|¥8|¥28|普通API标准价格，当前缓存存储限时免费；不当作永久免费，[官方价格](https://docs.bigmodel.cn/cn/guide/start/pricing)|

价格核查于北京时间2026-10-16，保存 `PRICES.json`。不读取第三方报价替代官方价格；不假定资源包、优惠或缓存必然覆盖。

在以上价格条件下，以代理输入且输出全部用满估算新增费用：

|模型|新增格数|输入Token代理|输出参数总上限|条件费用估算|加倍输入预留后的估算|
|---|---:|---:|---:|---:|---:|
|qwen-flash|5|53,076|45,056|¥0.07555|¥0.08427|
|qwen-plus|5|53,076|45,056|¥0.13257|¥0.17913|
|deepseek-flash|5|53,076|45,056|US$0.06999|US$0.08745|
|glm-5.3|6|60,138|61,440|¥2.20142|¥2.73168|
|新增合计|21|219,366|196,608|**¥2.40954 + US$0.06999**|**¥2.99508 + US$0.08745**|

人民币与美元不使用臆造汇率合并；平台实际换算/支付币种待账单核验。完整24格的相同“代理输入+输出用满”参考为¥2.47360+US$0.09177，其中包含旧格假定用满的参考，不代表过去实际费用。

**建议一次性授权的累计估算停止阈值：CNY ¥10.00及USD US$1.00，分别监控。不是现金硬上限。** 每请求前预留加倍输入估算及全部输出上限；已结算估算+下一预留超过对应阈值不派发。响应后按真实usage、公开阶梯价格、峰时保守价格重算；缓存按未命中估算。未知usage保留整笔估算预留并停止，不能记0费用。

不能覆盖为硬保证的部分：服务端完整输入、动态价格/阶梯、思考计量、存储/额外收费、汇率及延迟账单、客户端停止后未确认的远端处理。最终实际费用保留PENDING_ACCOUNT_BILL_VERIFICATION；需要用户明确接受探索性费用风险。

## 5. 执行顺序与停止机制

24格顺序由种子20261016在看新增结果之前冻结，避免连续三格同模型/同节点；移除3格复用后，按剩余21格顺序一次连续执行。不是按第一个模型全六节点再换模型。模型状态/客户端结果缓存隔离；供应商缓存usage原样记录。

- 单格请求最大120秒，连接15秒/读取105秒及信号总截止；整批客户端3600秒，最后60秒用于保存状态。D仍UNKNOWN，3600秒不是任务期限或现金上限。
- 理论请求截止之和21×120=2520秒，额外解析/验证/存盘也占整批时钟。每派发前要求足够剩余120秒；父进程watchdog在保存预留前停止新增工作，不以阶段建议延长总墙钟。
- JSON、Schema、引用、单位、角色、期间、关系证据、UNKNOWN传播等普通质量拒绝：保存原始输出及该格失败，继续其他格，不修复或补事实。
- 输出因长度截断：作为该格输出质量失败保留并继续，无重试。非标准服务完成状态按系统异常停止。
- 全局停止：账户/HTTP失败、身份不明、usage未知、输出参数越界、累计估算预算或输入估算预留超出、单请求超时/远端完成未知、全局墙钟不足、文档/目录/冻结变化、未分类系统异常。超时安全停止已明确列入本次待审批规则，不声称远端已取消。
- 不因完成1—2格而退出。完成21新增格后汇总24格；若提前全局停止，仍生成24行，余格NOT_EXECUTED，不宣称矩阵已完成。无自动续跑、换模型、重试、评审或修复请求。

## 6. 状态、质量与输出

每格分别保留：实际模型/版本字段及请求ID、原始请求/响应、原生Schema、适配Schema、证据守卫、引用来源、字段/期间诊断、verified局部指标及分母、proxy、UNKNOWN、usage（含cache/reasoning）、费用估算/币种/账单状态、API roundtrip及单格墙钟。

合同失败只代表该格输出不能被严格执行器使用，**不等于事实错误率100%或任务质量0**。未评分/未执行保留null及状态，不能记0/1。限定L1字段评分不冒充完整事实precision/recall或风险质量。每个模型—节点仅一条、一个事件，不能据此声称稳定能力排名、P90或调度收益。

本次条件化能力矩阵不运行真实端到端DAG，不将任意单格结果下传。真实DAG的错误阻断机制不改。未来给静态分配/调度的数据必须附输入、目录、合同、模型参数、观测时间与missingness；不得用本批当前事件的事后标签作为同题在线预测，不自动更新生产策略。

## 7. 准入与一次性授权方案

6/6必要离线检查通过，其中包含21格全部模拟质量失败仍完整结束24格，以及账户/usage/完整性/预算异常停止、全六节点固定祖先输入一致、3格复用不重派。无新合同回归扩展。

新冻结SHA256见 `opinion_capability_matrix_id_v1/FREEZE_MANIFEST.sha256`。只读启动核查：

```bash
python -B /root/r3_own_pool/opinion_capability_matrix_id_v1/START.py --mode fill-24
```

本轮没有有效付费授权；`AUTHORIZATION_TEMPLATE.json`默认approved=false。可供一次性批准的文本：

> 批准此计划新冻结版本的一次四模型×六节点统一能力矩阵采集。复用审定的3条历史正式失败，最多新增21次真实请求，形成24格；每新增格最多一次，不重试、修复或追加探针。允许将冻结P7公开来源片段、节点任务及合法人工/确定性前置输入发送至https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions、https://api.deepseek.com/chat/completions、https://open.bigmodel.cn/api/paas/v4/chat/completions，分别使用现有DASHSCOPE_API_KEY、DEEPSEEK_API_KEY、ZHIPU_API_KEY仅作内存认证。三个抽取节点每请求最大16,384输出Token，reconcile/assess/report每请求最大4,096，新增累计最大196,608，完整客户端3600秒，单请求120秒。批准累计费用估算停止阈值CNY ¥10和USD US$1，知晓这不是实际现金硬上限，接受未认证完整输入及实际费用风险。单格质量失败继续其余独立格；按本计划所有全局停止条件执行。不将单格输出下传，不启动GPU、不改历史或ZCODE、不提交Git。无需每1—2格再次申请授权，完成全部或触发全局停止后结束。

批准并另存新授权后，准确命令：

```bash
python -B /root/r3_own_pool/opinion_capability_matrix_id_v1/START.py --execute --mode fill-24 --authorization /root/r3_own_pool/opinion_capability_matrix_id_v1/APPROVED_AUTHORIZATION.json
```

**本轮到此停止，未发起任何新付费请求。**
