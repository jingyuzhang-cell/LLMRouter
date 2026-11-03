# OPINION_CONTRACT_V2首次节点能力Pilot

**实际结果：INCOMPLETE / TRUNCATED_OUTPUT。已执行1次Qwen-Plus真实请求；未形成三模型能力对照，未执行下游。**

## 1. 范围、授权与冻结

对象为原欧菲光6节点6边DAG，原结构、材料、截止、V2合同、质量协议均未改动。本批独立探索信封获明确批准：最多18请求、最大输出4096 Token、120秒/请求、2400秒完整客户端墙钟，并接受未认证输入/费用风险。限定凭据读取先经自动审核拒绝，取得明确授权后已作为独立操作获准；密钥仅在内存用于官方认证，未写入请求、Prompt或账本。

确定性reconcile不调用模型，因此实际计划是5个LLM节点×3模型=最多15请求；18为绝对上限，不是要求用完。固定候选qwen-plus、deepseek-flash、GLM-5.3，不预设模型适用节点。GLM沿用项目历史Anthropic接口和低推理参数，未模拟其JSON模式或固定权重身份。

每节点三个模型使用同一system/user及Prompt哈希；原Graph subtask目标不变，首次请求前冻结模板后没有修改。下游共同输入预登记为Qwen参考轨迹的合法输出，目的为固定输入，不是模型适用性选择。参考失败则停下游，不用其他模型替换，也不用Stub/Gold补齐。这样的设计本来只估计给定参考输入下的条件差异，不能代表所有上游分布。

准备目录：[opinion_node_model_capability_v1](opinion_node_model_capability_v1/)。实际目录：[REAL_RUN_20261014_221508](opinion_node_model_capability_v1/REAL_RUN_20261014_221508/)。

## 2. 实际请求与Q/C/L

|节点|实际模型|HTTP/身份|结果|输入Token|输出Token|客户端API时延|实际费用|
|---|---|---|---|---:|---:|---:|---|
|extract_current|qwen-plus|HTTP 200，返回model=qwen-plus|finish_reason=length，输出截断|5164|4096|91.074秒|待账单核验|

实际总请求1，服务端报告Token合计9260（输入5164＋输出4096）。这些是响应usage，不能认证派发前输入上界；本次没有缺失usage的请求。system_fingerprint为null，别名返回不证明固定权重版本。没有获取账户账单，不预测费用、不报虚构金额。

完整客户端启动器墙钟**91.080秒**；起止UTC为2026-10-14T14:15:08.006972+00:00至2026-10-14T14:16:39.087049+00:00。不把启动器墙钟冒充整个准备/报告交互耗时。返回为length，不是HTTP超时；日志通用字段remote_completion=UNKNOWN_IF_TIMEOUT是条件提示，不应将本次报告成发生远程取消。

extract_current的contract_pass=0，原因是响应截断，无法获得完整JSON及完成Schema/Guard评分。source_grounding、entity consistency、temporal validity及真实fact precision/recall均**UNKNOWN/未完成评价**，不能将格式失败等同全部事实错误或用未知值填0。主观风险正确性、未来影响、投资价值继续UNKNOWN。

## 3. 停止原因与只读归因

输出恰好达到冻结4096上限，原始文本在第7项事实的entity_ref中间结束，没有闭合完整JSON，也没有生成完整claims数组。保存了原始HTTP响应、输出文本、usage、请求及失败账本。

运行器原始状态采用通用INTERFACE_OR_BUDGET_FAILURE及INTERFACE_IDENTITY_OR_REQUEST_FAILURE；原始记录不改写。根据明确length及TRUNCATED_OUTPUT_STOP证据，报告层准确分类为**输出截断/节点交付失败**，而非端点不支持、身份失败或模型永久故障。

只读解码了6个完整事实片段以定位问题，6个至少有一项引用跨度与冻结原文不一致。例如首项evidence_ref的start/end与quote长度及原页文本不匹配。诊断说明问题还涉及直接生成Unicode offsets的可靠性，不能只归因为Token上限。

这些片段没有注册为合法事实，没有补成完整JSON，也没有计为节点成功；没有更改已冻结质量定义去给截断片段评分。详见PARTIAL_FRAGMENT_DIAGNOSTIC.json。

同一事实输出重复4套完整EvidenceRef、SHA及元数据，多项事实展开造成结构性输出开销。但没有证据证明仅提高输出预算便能得到正确跨度。禁止本轮自动扩大输出或更改Prompt重跑。

## 4. 未执行项与能力矩阵

DeepSeek和GLM在首请求触发全局停止后均未派发；它们不是失败样本，不能填质量0。新闻、历史、合流、评估、报告均未执行。本批仅一个已观测单元，不能回答节点间模型差异。

NODE_CAPABILITY_MATRIX.json保留全部计划单元和NOT_DISPATCHED状态。它是**不完整观测登记矩阵**，不是完成的模型能力矩阵或模型排名。

可自动核验的部分本来包括合法来源、数值token、实体证据、时点与引用。引用覆盖、结构、角色线索属proxy；语义precision/recall、unsupported claim率和主观风险仍无独立标签。此次输出未完成，未得到完整节点verified质量向量。

## 5. 对RQ1和后续路由的结论

RQ1尚未获得三模型对照证据，无法判断是否存在可利用的阶段能力差异。不能从Qwen一次截断推断其比DeepSeek或GLM差，也不能把停发当其他模型成功。

**尚不支持后续动态路由实验。** 当前真实阻塞定位为首节点输出交付：大量重复证据元数据导致上限截断，并出现直接生成跨度错误。下一阶段应先在独立新版本中解决可核验的引用传输/表达开销，保留来源、角色及数值约束；不应在本轮重试、降低检查或把剩余额度用于试错。

本轮结束，保留原请求与失败记录；0GPU、0恢复/动态路由、无历史反馈更新、无Git提交。旧两个冻结包的18＋27份文件复核未改变。
