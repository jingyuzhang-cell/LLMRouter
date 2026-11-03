# 固定LOCAL异构恢复：首批配对采集冻结

结论：**DATA_COLLECTION_READY，等待独立付费授权**。本轮0真实模型请求、0GPU。暂停恢复范围扩张及联合优化；此包只采集固定LOCAL下的模型分配效果和预登记影子决策，不执行生产调度策略。

## 四个任务与独立性

|顺序|公开MultiHiertt dev UID|原始目标|必要事实/列|两臂先后|
|---|---|---|---|---|
|T1|911e291121d743ebb49f3c438db49eb0|2008/2007/2006 Total Collection平均|三年三金额|Qwen→DeepSeek|
|T2|fb2da75c16d640bea45099c8efe695b9|三年Refined products trunk lines总量|2009/2008/2007三金额|DeepSeek→Qwen|
|T3|3dc8d93adbe140da90516aa3058975a3|2006年末经营租赁占全部最低租赁付款比重|经营/资本租赁两金额|Qwen→DeepSeek|
|T4|0c64b517b1594ee2a73d7b1e18fcdb83|2011→2012净研发费用相对变化|2012/2011两金额|DeepSeek→Qwen|

来源：[冻结原公开数据](/root/phase_c9_0/external/MultiHiertt-data/multihiertt_data/dev.json)，SHA256 `0100d9d6832901d0c8ffa3141e548e51c98ecf3ac144407f90d8182ab3bcb0a7`。逐任务TASK_PUBLIC保留原题全文、原表索引、原表全文；SOURCE_AUDIT及SEMANTIC_ENVELOPE保留行/列、准确数字/实体/表头跨度及来源哈希。未根据Gold生成事实；原数据答案和程序仅冻结为独立评分材料。

筛查7314个现有项目/资本应用文本工件，四UID只出现在旧候选暴露登记，均不在该登记used_uids中；未找到问题全文、完整来源表、请求或结果记录。已排除曾进入旧模型节点实验的证券额度占比/证券价值候选、曾执行的预测题和题干歧义候选。四个来源表哈希不同，旧E2及四题间无相同完整表；它们不属于旧13.0三设施题的数值替换。此结论受仓库审查范围限制，不证明云模型训练中未见公开材料。原数据未提供逐表原年报文档ID，该身份保持UNKNOWN；四个独立任务记录和不同完整表不等于独立公司报告或统计IID。四题目标分别是平均、求和、组成比和变化率；它们共享财务算术领域与执行合同，领域泛化不作主张。

## 原图、前置状态与LOCAL

每题3节点3边：extract→form_expression→calculate，另保留extract→calculate事实边。依赖有实际执行作用：表达式必须消费源事实，计算同时依赖已绑定表达式与原始事实。所有节点贡献最终数值，未添加无必要验证节点或虚假分支。这是**浅层恢复机制图**，不是复杂组合优化场景。图来源均明确为MANUALLY_VALIDATED_MECHANISM_DAG；不计自动规划成功。

仅extract为DONE：从原始表格准确位置确定性构建2或3个事实，核验fact_id、实体、列角色、数值、跨度及语义合同版本。其来源标记为MANUAL_REVIEWED_DETERMINISTIC_PUBLIC_SOURCE_NOT_MODEL_OUTPUT。恢复目标表达式保持空白，没有人工表达式缓存或答案输入。INDEPENDENT状态重建断言、语义守卫及源哈希同时生效。

受控故障：对同一pending表达式执行实例用本地TypedExecutor.parse接收`{`，记录OUTPUT_SCHEMA_OR_ARITHMETIC、attempt=1；事实和原来源不变。固定种子20261014，明确不是自然云故障，不消耗请求。LOCAL R严格为该表达式及下游calculate两节点。每臂一次真实云表达式调用、一次确定性计算；前置extract缓存是相同合法手工状态。π只改变表达式执行模型，calculate的模型标签不产生调用。

每臂独立重建Executor、输出、绑定、账本和恢复action日志；禁止跨臂复用生成结果。同一题两臂post-fault state hash、消息正文、Schema、来源及R一致，详见PAIRED_IDENTITIES和各任务ACTION/REQUEST_TEMPLATES。程序原有缺事实、单位、源血统保护全部保留。若新表达式引用或合同失败，该臂停止，另一独立臂仍可记录；基础设施、身份、usage、全局时间或冻结安全失败停止整批。

## 模型及费用口径

Qwen `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`；DeepSeek `https://api.deepseek.com/chat/completions`。固定qwen-plus/deepseek-flash，temperature=0、JSON object、stream=false、max_tokens=512。分别设置enable_thinking=false和thinking.type=disabled。JSON模式不等于完整Schema认证，客户端严格Schema/表达式绑定/源语义验证仍执行。

官方当前文档将Qwen别名对应到qwen-plus-2025-12-01，将DeepSeek Flash注明为DeepSeek-V4.1-Flash；实际返回模型名、fingerprint、参数、原始响应逐臂保留。别名不是不可变权重保证。两模型消息字节相同但Tokenizer、基础设施、非思考开关和服务缓存不同，不能称完全同质基础设施。

[Qwen官方模型页](https://help.aliyun.com/zh/model-studio/qwen-plus)北京非思考≤128K原价输入0.8/输出2元每百万Token；[DeepSeek官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)Flash输入缓存命中0.003/0.006美元、未命中0.15/0.3美元、输出0.6/1.2美元每百万，区分低峰/高峰。[DeepSeek请求规范](https://api-docs.deepseek.com/api/create-chat-completion/)确认非思考参数与JSON输出。文档核验记录在MODEL_DOCUMENTATION_CHECK。真实账单、账户优惠、峰谷与缓存比例待核验。

分别以各模型同一公开原价口径记录CNY/USD，不相加或假定汇率；Token另册对照。缓存命中/未命中usage字段原样保存，必要时区间估费。统一现金币种与成本最优路由尚不在本批结论范围。

## 预算与停止

最多8生成请求（每题每模型1次），0非生成模型API请求，0规划/模型评审/修复请求，0GPU。每次最大输出512，总输出参数限额4096。完整客户端墙钟**1800秒**，单次绝对请求等待120秒，为证据保存/评分预留120秒；8×120=960秒，另有720秒门禁/前置/检查余量。每次请求前进行剩余墙钟准入，主循环在1680秒内停止，保存阶段使用剩余预留。进程/网络/云端不能确认的取消不写成功，远端执行/费用记UNKNOWN。

D仍UNKNOWN；1800是客户端实验上限，非任务期限。不改变Qmin=.8、epsilon=.1，也不调用未认证概率的生产门禁或声称按时收益。

完整消息长度T1–T4为4442、4508、3498、3442字符；各模型序列化载荷約3982–5180字节。它们**不是输入Token计数或认证上界**。输入Token及实际费用预先上界仍UNKNOWN，必须另行明确接受探索费用风险。仅示意：假设每臂输入5000、输出512，四次Qwen原价约¥0.020096，四次DeepSeek高峰全未命中约US$0.0084576；这不是预测值、费用承诺或硬预算。实际usage原样落盘；缺usage保留整次未知曝险，停止后续，不记零。

派发前持久化全局RESERVED_BEFORE_HTTP和每臂原始请求/账本；一协议一次claim，崩溃后禁止自动重启、恢复派发或补齐。HTTP无SDK重试、重定向、模型回退。本批请求必须逐字段等于冻结REQUEST_TEMPLATES，旧localhost路径不可进入。

## 评价与信息截止

主指标：恢复后task_success_offline、合同/语义/来源状态、recovery_remaining_wall_s、实际input/output/total usage、费用估算及账单状态。辅助记录节点输出、实际模型、输入长度、异常、缓存、取消状态、未派发臂。

每臂剩余墙钟从恢复决策开始，含合法性检查、调用、计算、来源及公开规则验收；不含执行后Gold评分。API客户端区间另记，服务端队列/纯推理分解UNKNOWN，不能把网络区间直接称纯服务时延。总客户端从启动器入口含哈希门禁、状态恢复、故障、所有执行及评分和主结果保存。

在线输入只包含题目/公共表格事实/语义合同/受控异常，不读取Gold。执行后公开规则检查不改表达式，以必要fact_id精确集合及数值/探针运算检查平均、总量、组成比、变化率；有限探针不是数学等价证明。源与派生血统连续核验。**两臂全部停止后**才读取独立GOLD_EVAL_ONLY（原公开答案和program），数值容忍abs=1e-5、rel=1e-8；合同或源语义失败不能被答案相同覆盖。安全中止的部分任务仅在全部派发停止后评分，标记不完整，不加入后续信息。所有失败留在分母，未派发明确区分。

任务顺序T1→T2→T3→T4预登记；先后模型交替。每题首次请求前保存SHADOW_DECISION时间、历史UID列表及统计；只使用之前完整任务已可用标签，当前题和未来标签均禁止。旧E2继续保留，但剩余3节点合同不同，不用于本批3节点链历史排序。第一题无匹配数据，预登记Qwen回退。后续简单规则按历史成功频率、再平均剩余时延、再Qwen平局决定；既不拟合复杂Router，也不将频率写成可靠质量概率。两固定模型基线与simple_history分别在事后SHADOW_COMPARISONS对照实际已测臂；付费执行仍为配对测量，并非自主在线路由实验。跨任务算术类型的统计转移仅探索性；4题不能认证校准、P90或稳定优势。

## 实现与必要测试

新代码仅在feedback_local_batch_v1：BUILD.py任务筛选/编译/状态冻结；RUN_BATCH.py复用现有TypedExecutor、语义守卫、LOCAL闭包、云HTTP和账本；FREEZE.py哈希索引；TEST_BATCH.py针对性检查。旧模块、旧E2和历史结果没有改动。

10/10针对性测试通过：四题来源隔离、八臂Mock与独立评分、消息/故障状态一致、付费未授权拒绝、当前/未来标签排除、不完整任务排除、请求/时间拒绝、HTTP失败及未知用量、崩溃claim拒绝、来源变化拒绝、输出合同拒绝无重试。Mock八臂通过仅证明接线，**不是真实模型质量证据**。不重复566项通用回归。原E2历史哈希在HISTORY_HASHES与HISTORY_INTEGRITY_AFTER核对。

## 冻结与启动

协议文件SHA256：`e33841089335fad5c3b7e83cb988a1600aad67cd8fb66d853782cfbc95436bc1`。完整执行冻结索引为MANIFEST.json（任务、源文件、请求模板、状态、模型配置、运行代码及复用模块），最终索引SHA记录在GATE_RESULT.json。它与协议文件哈希是两个不同身份。

取得独立付费授权后才创建签署receipt，授权模板当前approved=false。运行命令：

```bash
python /root/r3_own_pool/feedback_local_batch_v1/RUN_BATCH.py --authorization /root/r3_own_pool/feedback_local_batch_v1/AUTHORIZATION_APPROVED.json --run-directory /root/r3_own_pool/feedback_local_batch_v1/REAL_RUN_01
```

简短授权文本：批准本冻结索引对应的一次固定LOCAL四任务×Qwen-Plus/DeepSeek-Flash配对探索采集，最多8次生成请求，每次输出≤512 Token，客户端完整墙钟≤1800秒；接受未认证输入Token及实际费用风险；不重试、补样、规划、评审、GPU或恢复范围扩张，D保持UNKNOWN，完成或停止后不追加实验。

当前结论只为采集准备READY。四个新任务可以直接测量一次表达式LOCAL及下游确定性计算，不再请求上游抽取。尚未证明历史反馈有可利用信号、路由收益或稳定模型排序。下一步只差本批明确付费授权及执行时密钥/身份/哈希/重复实例门禁；本轮到此停止。
