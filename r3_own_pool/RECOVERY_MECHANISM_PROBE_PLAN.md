# E1抽取失败归因与E2冻结前置状态恢复机制探针

**RECOVERY_MECHANISM_PROBE_READY（探索性、未获付费授权）**。再次获得独立授权后，可直接测量恢复动作，不需要重新调用extract。本轮0云模型请求、0GPU启动，不重跑V3，不修改任何E1真实响应或账本。

## A. SOURCE_VALUE_UNSUPPORTED的准确根因

原运行：[V3真实报告](semantic_recovery_probe_v3/REAL_RUN_20261014_162628/RESULT_REPORT.md)。六金额、设施、列角色、数值位置及原始行跨度逐项见[SOURCE_VALUE_DIAGNOSIS.json](recovery_mechanism_probe_v1/SOURCE_VALUE_DIAGNOSIS.json)。

- 六value与number_start均正确；它们对应Franklin的54/51.8、Macon的58/49.9、Brentwood的78/75.3；设施与列角色可从相同行/列头的冻结来源证据确定。
- 模型evidence只填写设施名称，evidence_start指向真实设施名称文本。这些跨度确实存在，但**均不含任何金额数值Token**，不能支持value。
- [fact_semantics.py:ground](collab_scheduler_v1/typed_dag_v1/fact_semantics.py:14)要求value在evidence引文中有精确数值支持；number_start进一步约束这一匹配，不能替代它。首事实在数值匹配处拒绝，未到实体注册。
- 用同一数值位置和完整原表格行作为独立正例，在不声明未支持unit的情况下，六项都通过原守卫。**没有发现守卫错误拒绝包含金额的完整行**。未修改原始模型响应。
- Prompt中有数值位置与设施/角色绑定，但新版output_format对“evidence必须包含金额”不够明确；Schema只约束evidence为非空字符串，不能表达value与引文的关联。这是输出指引/Schema的弱约束，不是来源守卫冲突。模型还声明了unit="(in millions)"，但当前单位合同只接受相邻来源支持的unit；该风险尚未成为首个触发错误，不回写为本次实际首因。

E1的最小约束建议仅为：明确evidence使用**包含所选金额的短原文单元格/行引文**，禁止把entity_span.quote当金额evidence；number_start仍必须准确；unit缺少当前合同支持时省略。保留现有ground/语义守卫，不自动换引文、换fact_id或修正数值。本轮没有修改V3 Prompt/Schema或重新请求模型。

## B. 独立合法前置状态

目录：[recovery_mechanism_probe_v1](recovery_mechanism_probe_v1/STATE.json)。原图8节点12边、图hash `d5785e788741b98b216a681fdcf86ba474ae97f1c69a61753329cb0f1961379c` 完全保持。来源、六事实要求及语义envelope复用已审定版本。

状态来源明确为 **MANUAL_REVIEWED_DETERMINISTIC_PUBLIC_SOURCE_NOT_MODEL_OUTPUT**，不是历史模型输出，也不是LLM自动初始化成功：

1. 从已冻结原表数值跨度及所在原文单元格取value/evidence，执行原fs.ground，再执行已核验实体/角色绑定；六fact_id、设施、column_role、value及完整source_ref皆保留。
2. 对Macon和Brentwood两分支，按原图subtask明确的“授权−已提款”规则人工审定操作数角色，确定性建立其表达式绑定和计算输出。不增节点、不改规则、不读取Gold。语义身份检查与来源/cache守卫独立重验。
3. extract、两个兄弟expression及两个calculate共5个DONE节点构成缓存前置。Franklin expression及其calculate、aggregate保持pending；没有提前写入最终答案，也没有构造已完成目标后再宣称恢复。
4. prospective assignment仍是原执行菜单；缓存producer_model=null、real_model_calls=0。不得将手工语义缓存称为Qwen生成结果或跨模型真实输出缓存。

[INDEPENDENT_STATE_AUDIT.json](recovery_mechanism_probe_v1/INDEPENDENT_STATE_AUDIT.json)使用独立的原文切片/value/哈希/角色断言，结合原来源、语义和缓存守卫核验，不读Gold。[CONSTRUCTION.json](recovery_mechanism_probe_v1/CONSTRUCTION.json)明确记录人工审核规则；启动器还必须重新复现状态并与冻结STATE完全相等。

STATE文件SHA256：`fd411c8c99c96c16eb51763ab52afbbe88a8522a5261992b39d054660a03760e`

实验协议SHA256：`5f51e513e4741dbb3bd055410506c97d671416e7bf4fdf0eb607a190847a66fd`

执行manifest SHA256：`2796ed002c129084e3a982ce9a47d12af15359703dfedb5d4b34dd1e837d1ecc`

## C. 可直接进入恢复的真实入口

唯一入口：[RUN_PROBE.py](recovery_mechanism_probe_v1/RUN_PROBE.py)，实现：[recovery_mechanism_probe.py](collab_scheduler_v1/typed_dag_v1/recovery_mechanism_probe.py)。新增文件独立于V2/V3，不修改生产奖励、预测器、Qmin=.8或epsilon=.1。

启动链：冻结核验/独立付费收据 → 凭据与原子一次性认领 → 重新审核前置状态 → 恢复其合法缓存 → 对Franklin待执行实例调用原parse解析“{”并记录受控JSON失败 → 原JointRecovery.prepare/apply → TypedExecutor真实请求恢复expression → 语义登记 → 工具calculate及aggregate → 公共来源/结果验证 → 停止所有派发 → 读取Gold独立评分。

故障类型是**本地可重现的受控解析失效，非自然模型失效**；注入没有付费请求，没有改变事实、来源、模型历史输出或Gold。错误码沿用合法恢复白名单OUTPUT_SCHEMA_OR_ARITHMETIC。缺事实、单位、血统、实体/角色错误仍不能被强行送进恢复。

## D. 最小两臂对照及公平性

|臂|Z / R|π中的真实LLM模型|真实请求数|输出上限|
|---|---|---|---:|---:|
|A|LOCAL；Franklin expression、calculate、aggregate三节点|目标expression=qwen-plus；工具节点不调用模型|1|512 Token|
|B|同一LOCAL闭包|仅目标expression改为deepseek-flash；工具节点不调用模型|1|512 Token|
|总计|原节点/依赖不变，无extract重执行|两模型最小子池|最多2|合计名义1024输出Token|

两个动作不同在π，是**预先指定的固定动作测量，不是反馈策略自主选择**。两臂恢复前JointRecovery.state_hash相同；人工状态分别深拷贝、缓存原来源身份各自重验；响应缓存隔离。五DONE的共同离线构建成本独立记为人工/确定性准备，0云请求，不伪称它没有人工成本。

可见messages逐字一致：把恢复反馈中只用于审计的execution_instance映射为同一个冻结故障实例ID；各臂真实action_id及请求key仍分别保存。模型自身必要参数不同，故不能假称模型内部采样机制完全相同。A后B固定顺序，单次实验存在服务负载/时序混杂，不能做因果优势或显著性推断。provider输入前缀缓存折扣按实际usage单独记，不把它当本项目响应复用。

Qwen：北京DashScope chat/completions，qwen-plus，enable_thinking=false，temperature=0，JSON object。DeepSeek：api.deepseek.com/chat/completions，deepseek-flash，thinking.type=disabled，temperature=0，JSON object。两者均512、非流式、同一客户端Schema及语义检查。两个密钥仅离线确认存在，未查询账户权限或余额。旧DeepSeek禁思考真实记录有JSON成功，但不是本次合同的真实接收认证。

DeepSeek官方文档确认canonical模型名、非思考切换及JSON模式，当前公开版本为DeepSeek-V4.1-Flash；当前新输入的API实际接受情况仍是下一次真实测量内容，不能用Mock冒充。[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)、[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)。Qwen官方配置依据见[Qwen-Plus文档](https://help.aliyun.com/zh/model-studio/qwen-plus)。响应实际model/system_fingerprint均保存，不把别名当绝对固定权重。

## E. 时延、质量、费用与停止

- 每臂从RECOVERY_DECISION_BEGIN开始计recovery_remaining_wall_s，包含动作合法性、源缓存检查、API、工具及最终公共验收；到完成/失败都保存。完整客户端从首次冻结核验起至结果持久化，最多1200秒；单请求120秒，预留120秒保存。D=UNKNOWN、on_time=null，绝不计算正式按时收益。
- 节点实际输入、原始请求/响应、状态、Z/R/π、缓存来源、source/hash/binding快照、usage、客户端API时延、模型身份、未知服务器阶段均保存。
- 先停止全部派发，再独立Gold评分task_success_offline；不回写模型先验。失败也进分母，无重试、评审、规划、修复调用。合法交付但语义失败只终止本臂，另一独立臂仍可按协议测量；HTTP/身份/usage/超时/资源故障停止整个panel。
- 输入Token预调用硬上界及实际费用硬上界未认证，需要接受探索性风险。未知usage保留全请求敞口，不记零。Qwen参考低输入档CNY¥.8/¥2每百万；DeepSeek参考USD输入缓存未命中峰值$.3/非峰$.15，输出峰值$1.2/非峰$.6，每百万。实际峰段、缓存比例、币种和账单须独立核验，不擅自换汇合并成本。[DeepSeek价格依据](https://api-docs.deepseek.com/quick_start/pricing/)、[Qwen价格依据](https://help.aliyun.com/zh/model-studio/qwen-plus)。记录的估算不是实际账单。
- 若一模型无法交付合同合法表达式，真实记录失败；不会为了获得恢复PASS追加请求、改变π或删事实。

## F. 离线证据与证据边界

**29项针对性测试通过**：9项新机制入口＋20项现有语义合同专项，没有重复数百项通用回归。网络与进程启动阻断。覆盖原始坏引文/完整行正例、手工状态可复现、相同状态/消息、两个π、无extract、真实恢复闭包、缓存复用、跨设施拒绝、Gold隔离、超时未知敞口、授权与重复启动拒绝。

[MOCK_PAIR_FINAL](recovery_mechanism_probe_v1/MOCK_PAIR_FINAL/RESULT.json)为最终离线演练，两臂各1个Stub交付、两工具执行、各得到13.0。它不是任何真实模型成功，不计为异构优势或模型画像数据。

E1继续是V3真实extract失败：1请求、6084 Token、6.960秒、未进入LOCAL。E2的全部前置由人工/确定性构建，其成功只能证明冻结前置下的真实恢复路径和相应条件质量/剩余时延观测。不能替代E1，不证明P90、生产策略通过Qmin、动态优化或复杂DAG净收益。这个浅算术图只用于最小接口机制测量。

历史文件哈希索引复核，不改变真实失败记录或正式评分协议。本轮0付费请求、0GPU、无Git提交。

## G. 下一次独立授权文本

> 批准执行manifest `2796ed002c129084e3a982ce9a47d12af15359703dfedb5d4b34dd1e837d1ecc` 对应的一次RECOVERY_MECHANISM_PROBE：同一人工/确定性公开来源前置状态及受控解析故障，A=LOCAL＋Qwen-Plus、B=LOCAL＋DeepSeek-Flash。每臂最多1次真实生成，总计最多2请求，每次最大输出512 Token，完整客户端1200秒。我接受未认证输入Token及两服务实际费用风险。不重试、不加调用、不抽取上游、不规划/评审、不GPU；不修改原图或历史数据。D保持UNKNOWN，失败保留并按冻结规则停止；E2不宣称E1端到端成功或动态策略优势。

**直接回答：可以。再次获得上述独立授权后，入口能够直接测量合法恢复动作，不再被上游抽取错误阻塞。当前只缺真实付费风险授权；实际服务拒绝或节点合同失败将作为测量结果保存，不自动修复。**
