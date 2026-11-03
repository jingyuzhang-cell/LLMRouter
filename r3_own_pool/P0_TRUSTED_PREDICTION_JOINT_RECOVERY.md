# P0可信预测与通用联合恢复最小闭环

日期：2026-10-14。结论：**NO-GO（预测数据与实验资源尚未准入）；联合恢复适配已完成离线闭环。**本轮0真实API请求、0GPU加载、未修改历史账本，未降低Qmin=.8、ε=.1或任何旧任务期限，没有继续扩展缓存功能。

## 1. 已交付的最小实现

- [history_baseline.py](deadline_reward_v1/history_baseline.py)：历史频率、Beta(1,1)平滑、经验请求时延分布/P90、经验截止CDF。只允许pool/model/operation/parameters_group/arm/task_type等公开条件字段。拒绝Gold、答案、输出Token等结果特征；排除synthetic和缓存记录。重复UID不能制造独立样本数。
- [joint_recovery.py](collab_scheduler_v1/typed_dag_v1/joint_recovery.py)：可选JointRecovery控制器，`prepare(Z,pi)`生成闭包R和图/状态绑定动作，`apply(action)`实际驱动原TypedExecutor。复用原类型、事实血统、工具计算和计量，不复制评分器、不修改原图。
- [audit_history.py](p0_prediction_joint_20261014/audit_history.py)：固定UID分组留出，生成可复算的真实记录清单、缺失比例、质量/时延评估。没有将新预测器塞入旧真实运行或更改旧先验。

输出目录：[p0_prediction_joint_20261014](p0_prediction_joint_20261014/INVENTORY.json)。这些是新离线版本，不是已获真实实验授权的冻结启动包。

## 2. 历史数据是否可用

审计范围明确限定为：已完成60题本地确认、7份旧可靠性DISPATCH文件、FE原始/恢复/参数恢复三份云账本、两张实际执行的自动图。**不是全项目所有历史实验的普查**。规划请求不与节点执行混合，Stub/evidence目录不进入统计。

|数据组|真实响应记录|不同任务UID/材料ID|已知输入/输出Token|身份与标签边界|
|---|---:|---:|---|---|
|本地确认medium/large/coder|469|60|164744 / 21099|provider_model全部保存；任务终端质量另有360行/60题，节点真正确率标签缺失|
|本地旧可靠性|1257|113|410383 / 96663|含1笔usage被原预算拒绝的真实响应；重复FIT、SCREEN/VALIDATE合计，不是1257独立题|
|云端资本文档FE|28|5|106810 / 52285|请求模型ID已知，但所选账本没有实际response model/version字段；质量非任务标签，JSON parse另列|
|云端自动图节点|7|2|3227 / 326|qwen-plus响应别名保存；2道开发任务完整结果正确，不等于7个独立质量样本|

本地469响应的模型计数large220、medium87、coder162；可靠性coder366、large520、medium371。云FE GLM-5.3=9、Flash=7、DeepSeek=7、Qwen=5，参数不同的重发不得合并成模型能力率。1257记录的已知usage总507046包含异常4629，不能当全部已正常结算金额；历史超额仍保留。

“不同UID”只证明标识去重，不证明语义独立或完全无开发污染。旧可靠性重复同任务同身份，云FE多次同材料调参数；新云两题已用于开发。文件身份及缺失分母见[INVENTORY](p0_prediction_joint_20261014/INVENTORY.json)和[逐响应记录](p0_prediction_joint_20261014/REAL_ROWS.jsonl)，每模型/操作/参数分组亦单列。

### 2.1 时间与反馈分开

- 所选响应全部有输入、输出usage和客户端API duration；它包含传输/潜在服务端排队，**不能称为隔离后的模型推理时延**。
- queue、prefill、decode字段缺失100%，不能从duration推测分阶段时间。
- 切换事件和缓存命中从TASK_LEDGER独立统计，见INVENTORY.cache_and_switch。旧缓存响应latency为历史参考，不能加成新推理。
- 旧节点FAILED/降级反馈另存[OBSERVABLE_FEEDBACK](p0_prediction_joint_20261014/OBSERVABLE_FEEDBACK.json)。这是可部署状态信号，不自动成为任务正确性标签。
- FE仅离线JSON parse可计算；完整来源/引用正确性不能由它推出。silver召回是不同目标、存在历史解析撤回边界，不填补算术任务质量。
- 2题TASK_SUCCESS和旧60题Q_v21来自执行后独立评分，允许用于离线训练/评估标签，但Gold数值和silver内容不进入在线特征或恢复决策。

## 3. 最小预测基线的留出结果

UID哈希固定5折中的一折留出：60题分为47训练、13留出；六臂同UID始终落同一侧，避免跨臂任务泄漏。78留出行仍只有13个任务簇。当前分割是已看过数据上的**事后诊断**，不是新的确认性实验。

|任务质量/旧墙钟基线|频率Brier|平滑Brier|经验P90覆盖|P90与实测时长绝对差均值|
|---|---:|---:|---:|---:|
|不分策略|.26709|.26205|.88462|231.77秒|
|按arm条件|.23798|.23286|.92308|30.53秒|

校准分箱也保存：例如不分策略平滑预测均值.1803，而留出观察.3590，有明显失配。按策略训练点估计SS .2766、NONE .2553、MONO .4681、DS/SD/DD 0，均不能支持Qmin=.8。它们是旧整条策略任务准确率，**不是某个模型节点的能力**。

按策略截止预测Brier为0也不能宣称截止问题已解决：预测/标签都来自旧缓存切换缺陷下的强烈臂级时间差异，未识别新补丁后的真实恢复分布。旧墙钟与conditional service不混合。完整指标、分箱和训练数量见[BASELINE_EVALUATION](p0_prediction_joint_20261014/BASELINE_EVALUATION.json)。

|请求时延条件分组|训练/留出不同UID|留出响应|P90覆盖|准入解释|
|---|---|---:|---:|---|
|本地确认|47 / 13|99|.92929|仅该本地请求菜单诊断，不能当端到端恢复保证|
|本地可靠性|96 / 17|227|.68722|明显不足；与旧6/10格欠覆盖发现一致，但统计口径不同|
|云FE|4 / 1|8|.37500|全部条件组独立材料不足，INSUFFICIENT_DATA|
|云自动图|2 / 0|0|UNKNOWN|当前哈希留出为空，INSUFFICIENT_DATA；不能报覆盖1|

时延分位数来自真实训练响应经验分布；重复响应属于同任务簇，不能充当独立样本。缺失匹配条件不会偷偷退回本地或stub先验。

两个Qwen任务即使都正确，频率=1、平滑=.75、Wilson描述性下界约.3424；[CLOUD_QUALITY_DIAGNOSTIC](p0_prediction_joint_20261014/CLOUD_QUALITY_DIAGNOSTIC.json)仍为INSUFFICIENT_DATA。不得取频率1绕过Qmin。代码的min_tasks=20只是诊断性数据不足守卫，**不代表20样本可认证任何可靠性**；所有输出`calibrated_guarantee=false`，不得直接作为安全门禁证书。

### 3.1 仍缺的确切字段

[REMAINING_DAG_PREDICTION_GAP](p0_prediction_joint_20261014/REMAINING_DAG_PREDICTION_GAP.json)指出匹配新云恢复任务的行数为0。所缺组合是：

`graph_hash × failure_error_code × Z × R × pi × request_parameters × cache_state`对应的`recovery_remaining_wall_s`及`task_success_offline`，并有实际provider版本、派发/排队时间锚。

节点真正确率无法从现有格式标签中恢复；剩余DAG时间也不能简单求和节点P90或假设独立。模型/节点质量条件基线因此返回缺标签，不使用手设0.6/.95。不重启已关闭的旧可靠性校准路线。

## 4. 联合动作已能进入TypedExecutor

已有8节点12边原图、来源及上下文保持不变。新控制器的输入是显式动作：

```text
{ Z: NONE|LOCAL|FULL, R: 闭包节点集合, pi: 恢复及剩余节点的模型映射,
  graph_hash, state_hash, action_id }
```

- NONE：记录停止，无调用，不伪造最终输出。
- LOCAL：R是所有失败节点及其后代闭包；已消费DONE后代拒绝改写。π必须完整覆盖R和其余pending/blocked节点，且模型在metered.bindings注册。
- FULL：另建同图TypedExecutor实例，原执行状态保留；使用同一个metered预算、继承尝试计数、完整π，不能回滚失败成本。
- 来源版本和缓存：动作绑定完整Graph（含provenance）、context、输出、状态、reference binding、派生血统及分配。复用事实重新ground并对比fingerprint，表达式重新核验绑定，计算/合流值重算一致性，验证值与其输入对照。源/状态改变拒绝stale action。
- 新恢复实例使用公开action_id反馈绑定Prompt身份，避免错误响应被缓存替代；不补造公式、事实、步骤或边。已有合法缓存的复用与底层physical/cache计量分列。
- 先fsync STARTED，再执行；同state/action被认领后不得自动换π重派，崩溃需显式对账。异常保留部分状态、成本和FAILED记录。各节点上限沿用有界尝试保护。
- 切换由原共享transport负责，控制器不启动GPU或模型；预算reserve/settle仍走现有metered入口。若真实transport不记录切换/未知usage，就不能由控制器宣称费用或时间已闭合。

没有改默认TypedExecutor路径、旧协议或缺事实保护。这是可选的泛化Graph动作适配，不是已验证的优化策略或云端真实调度。

### 4.1 哪种失效合法

本轮支持的最小实例失效是**LLM输出JSON/端口合同解析拒绝**（`OUTPUT_SCHEMA_OR_ARITHMETIC`且失败的是LLM节点），例如表达式节点返回未闭合JSON。反馈是原始输出及解析错误，不用Gold。用一次输出合同注入即可复现；任务结构/公式/来源不改。没有在真实服务上注入。

FACT_MISSING、UNIT_MISMATCH、DERIVATION_UNTRACKED、REFERENCE_CHANGED等仍拒绝LOCAL和FULL盲修；换下游模型不能补造上游事实。数据引用、来源或确定性算术错误本适配也不自动当作可模型重试。原提议“不存在事实引用”仍不是准入失效场景。

### 4.2 8节点图实际离线轨迹

[STUB_JOINT_TRACE](p0_prediction_joint_20261014/STUB_JOINT_TRACE.json)保存完整动作、π、状态、来源输出和计量。使用原Graph、冻结原输入，只有Mock模型输出；不读独立Gold作为执行输入。

|动作|失败前Mock调用|恢复新增Mock调用|复用DONE节点|增量MockToken|结果|
|---|---:|---:|---:|---:|---|
|LOCAL + 目标/剩余π重分配DeepSeek别名|4|1|5|30|原图完成，保留事实/计算血统|
|FULL + 全π重分配DeepSeek别名|4|4|0|120|同图新实例完成，共享预算累计8调用|

计算和合流仍是原确定性工具，不伪称LLM节点。模型名只是注册Mock bindings，**不证明真实DeepSeek服务身份、能力或延迟**。图可完成的13数值来自冻结事实的工具计算，仅为Mock接口结果，不计真实TASK_SUCCESS。

## 5. 云模型池最小元数据冻结

[CLOUD_POOL_CANDIDATES](p0_prediction_joint_20261014/CLOUD_POOL_CANDIDATES.json)保存脱敏配置候选及未知项，无密钥。实际端点来自真实代码；未对服务发请求。

|模型|端点与既有参数|缺口|
|---|---|---|
|GLM-5.3、GLM-5.3-Flash|open.bigmodel.cn/api/anthropic/v1/messages；temperature0；low effort/8192为既有调参候选|所选账本实际response版本缺失；本图质量/恢复时延0行；官方价表未能读取，历史cash=0不能当免费|
|deepseek-flash|api.deepseek.com/chat/completions；temperature0；thinking disabled，2048|新参数只覆盖少量FE，实际返回版本缺失；本图任务标签与恢复时延0行；官方价格页读取超时，旧推算价不能认证当前账户成本|
|qwen-plus|dashscope.aliyuncs.com/compatible-mode/v1/chat/completions；两自动图实际request含enable_thinking=false、JSON object、temperature0、512|只有2开发任务，无当前三分支恢复数据；返回别名不等于固定权重版本；完整输入上界和账单未认证|

阿里云当前官方页面给出北京地域输入≤128K的非思考原价输入¥0.8/百万、输出¥2/百万、缓存命中输入¥0.16/百万；这是公开参考价格，**不是全地域/全输入档位或本账户最终账单**。[官方Qwen价格与模型页面](https://help.aliyun.com/zh/model-studio/qwen-plus)。未沿用其他供应商价格。

[DeepSeek官方价格页](https://api-docs.deepseek.com/quick_start/pricing/)此次获取超时；[BigModel官方价格页](https://open.bigmodel.cn/pricing)未提供可读取价表，相关金额保持UNKNOWN，不用第三方价表填认证缺口。没有全面四池扫描，也没有把大写请求ID静默改成小写API别名。

本轮冻结的是**候选元数据和未知项**，不是完整实验准入包。旧17请求草案未获授权；总输入、现金、候选任务D仍未认证或重新冻结。客户端超时不证明云服务取消。

## 6. 验证与最终准入

新增13项针对性检查覆盖LOCAL/FULL/NONE、π与闭包、来源漂移、缓存事实篡改、缺事实保护、重复/崩溃认领、预算停止、重复UID及禁止oracle特征；复用Typed/合流/Stage4相关回归，共**79项通过**。网络和进程启动在测试中被阻断。[REGRESSION_OUTPUT](p0_prediction_joint_20261014/REGRESSION_OUTPUT.txt)。没有以增加无关测试代替数据缺口。

|直接问题|裁决|
|---|---|
|真实质量预测数据是否足够|本地可做受限诊断；新云三分支任务**INSUFFICIENT_DATA**，不能支持Qmin|
|时延是否足够支持P90|本地请求有经验分位数但校准留出欠覆盖；云独立材料太少，剩余DAG/恢复分布缺失|
|联合动作是否进入TypedExecutor|**离线YES**，原8节点图消费完整Z/R/π；不是云端执行成功|
|合法失效|LLM输出格式/端口合同拒绝；不允许缺事实/血统错误盲修|
|云池缺什么|匹配图/动作/参数的任务正确性和剩余完成时间；实际provider版本、队列锚、输入/费用证据|
|下一次真实配对READY?|**NO-GO**，不自动实验|

**最少还需优先解决一项：取得匹配本图合法恢复状态和候选π的任务级结果标签与剩余完成时间数据。**具体缺口不是笼统“预测不可信”，而是上述复合条件下`task_success_offline`和`recovery_remaining_wall_s`都是0条。现有两题成功、FE JSON成功或本地P90都无法填这两个字段。

这通常需要独立授权的最小数据采集，而不是继续写预测公式。单条正常/恢复轨迹最多验证接线和时间分量，不认证.8质量或.9按时概率；所需独立样本量必须按明确分布/置信目标审定，不在本轮擅自追加。云请求预算/服务身份也需同期完成准入。代码缺口已显著收口，不再把“通用联合动作完全未接线”作为当前结论。

本轮到此停止，保持所有历史失败、超额和UNKNOWN。
