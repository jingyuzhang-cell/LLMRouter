# P0截止预测归因与动态恢复配对准入审计

结论：**NO-GO**。本轮0模型请求、0GPU加载、0业务DAG执行；只读取历史代码和账本、复算138条决策时间记录、编译一个人工机制候选图。未修改奖励、Qmin、生产代码或历史实验。本报告及目录为新版本，不覆盖`DYNAMIC_ROUTING_P0_DIAGNOSIS.md`。

**主要失败不是奖励权重，也不是已经证明任务没有恢复机会。**31次是在决策时真实墙钟期限已经耗尽；其近因是缓存命中仍先切换模型，133.03秒切换占决策前可恢复观测墙钟下界的99.95%。另外15次是未校准的未来争用/服务模型把可行集压空。既有期限在当前执行编排下确实不足，但不能据此判断去掉不必要切换后的冷执行是否按时。下一轮最重要的阻塞是缺少可部署、与实际执行口径一致的任务质量与端到端时间预测依据；通用联合动作适配仍有工程缺口。

## 1. 原始证据与复算范围

- 历史运行：`deadline_reward_v1/confirmatory_runs/conf_20261012_214907/{DS,SD,DD}/TASK_LEDGER.jsonl`。本轮138条为每臂46条动态决策，**不是138个独立任务**；旧360条任务记录不增加样本。
- [逐任务时间证据](deadline_pair_admission_20261014/TIME_TASKS.jsonl)：UID、原账本行号、panel单调时间、实际剩余时间、候选z范围、切换/缓存证据。
- [汇总](deadline_pair_admission_20261014/TIME_SUMMARY.json)、[复算脚本](deadline_pair_admission_20261014/time_audit.py)。每臂31/15分解相同；17个tight+14个medium已过期，15个wide未过期。
- 原始概率、预算与权重反事实沿用[上一轮诊断](DYNAMIC_ROUTING_P0_DIAGNOSIS.md)，移除争用只作敏感性分析，不是修改真实协议或实际执行成功。

## 2. 时间起点与计量：不是推理耗掉133秒

`joint_verification_runner.execute`在共享base结束后，为每臂复制同一缓存并新建RealClock。绝对期限是`clock.time()+G3_MULT[tier]*planned_path_work`，在`panel_start`前创建；不是从故障被发现或恢复请求派发时重新计时。tight/medium/wide倍数为15/25/50。W来自独立FIT的planned路径服务均值，明确排除排队和切换；准入却使用真实墙钟剩余时间。

另建的结算`d_abs`使用第二组clock读数，和决策字典有微小起点差。完整逐任务绝对deadline未单独精确落盘；结算D已舍入，不能由它完全恢复每个绝对deadline。实际记录的`d_remain`是本轮裁决依据。

|臂|决策前墙钟下界(s)|两次实测切换(s)|切换占比|缓存调用|新推理调用|
|---|---:|---|---:|---:|---:|
|DS|133.296872|72.801701 + 60.431486|99.9522%|180|0|
|SD|132.457258|72.550300 + 59.828149|99.9405%|180|0|
|DD|133.095302|72.606113 + 60.423238|99.9504%|180|0|

下界为panel_start→最后一次决策前call结束；不冒充包含最后call到decision之间全部开销的精确时长。180调用为60题的前置阶段缓存请求。

**直接代码原因**：[stub_engine.py](deadline_reward_v1/stub_engine.py:276)在`_call`先执行`_switch(model,uid,key)`，然后才构造输入身份、查询缓存。`supplementary_runner.RealClock.advance`不睡眠，缓存响应保留的历史latency不能当本轮新推理墙钟。DD两次切换为coder→large、large→medium；medium→coder的第三次切换发生在动态决策之后，不计入上述133秒。

这证明当前缓存回放编排存在可避免的服务生命周期成本。未来最小修复建议是先核验上下文/上游输出并构造输入身份，命中合法缓存直接返回；只有miss才启动/切换模型。保持缓存模型、上下文、上游版本身份，不复用失效缓存。**本轮未实施生产补丁，不重算历史成绩。**新实验必须明确冷端到端或相同post-fault条件，不能混用两种估计量。

### 2.1 是否重复计入

历史加载和排队已自然耗掉RealClock剩余时间；`policy._score_and_pick`对未来服务分布加一次`own_switch+contention`，传入`e1_on_time`一次shift。未发现把同一笔已发生切换再次显式加入未来shift的直接代码证据。问题是：服务均值设定的D面对墙钟执行、缓存命中仍加载、未来争用启发式不对应实际批调度。不能笼统称为“所有时延双计”。

### 2.2 31次期限耗尽

DD实际剩余时间范围−65.262923至−19.703085秒。此刻任何非负未来运行时间都无法完成原期限，按时概率应为0。删除争用或修改奖励都不能逆转过去时间。无法证明无不必要切换的新编排下这31题会成功，也不能将旧D延长后追溯判为按时。

### 2.3 15次争用阻塞

DD剩余时间93.479161–93.687170秒。未来争用140–590秒来自其余任务remaining_work_est；初始化每任务10秒（v均值7 + stop .5 + start coder2.5），而不是当时真实队列遥测。批处理中许多前置调用已缓存，后续执行/降级又会改变队列。该值是代码明示的估计，不是实测上界。恢复请求未派发，因此无对应候选的真实完成时间，无法确认估计准确或恢复必然可行。

移除争用后的离线选项可为LOCAL r/v均large，合成先验p_on=1。不得把这个1当真实预测：补偿器每模型启动2–3秒，与本臂实测单次切换60–73秒不一致。单切换路径加独立FIT服务时间在93秒内**具有可能性**，两次60秒级切换则很可能不够；这不是新路径的实测时延，更不是0.9概率认证。不得据此派发。完整冷任务、switch前后状态和云端候选必须各自测量。

### 2.4 为什么全部p_on=0

正态路径用`sigma=(p90-mu)/1.2816`和`0.5*(1+erf(z/sqrt(2)))`。DD候选z在−1672.667至−46.792；DS、SD也远小于0。有限sigma的正态尾部数学上不严格为0，但erf结果数值饱和后CDF为0；最大z对应的尾部上界远小于0.9（见[概率数值复算](deadline_pair_admission_20261014/NUMERICAL_PROBABILITY_AUDIT.json)）。改成稳定CDF只能保留极小非零数，不能恢复可行集。根本是分布/shift输入失配，而非可以靠浮点修补恢复的概率。

## 3. DS质量0.6：确实是手设常数

[PRIORS_STUB_V1.json](deadline_reward_v1/PRIORS_STUB_V1.json)明示`stub_test_only`、synthetic、hand-set，r|medium q_success=.6。真实[confirmatory_launch.py](deadline_reward_v1/confirmatory_launch.py:131)把它同时传给OutcomePredictor、DeadlineCompensator及policy；独立FIT只用于D，没有替换这些质量/时延常数。r|large=.95、v|coder=.85、v|large=.95也是手设。DS限制原分配，保留r|medium，其min组合质量≤.6，低于Qmin=.8。

- **常数代替能力估计：确认。**并非校准任务正确率、置信界或具体任务证据。
- **节点/任务混用：确认缺依据。**用节点手设q的min组合不是已验证任务级成功概率。
- **代理/正确率混用：存在边界。**合同/parse、nonempty只说明格式/声明，不证明任务正确，不能补成q=.8。
- **旧本地→新云池：本次60题没有该直接错误**，当时仍是medium/large/coder；但这些先验不得迁移GLM/DeepSeek/Qwen。
- **决策Gold泄漏：未发现本次policy读同任务Gold的调用链。**Gold用于终端评分；新云事件分支任务后silver更新是另一协议，部署时标签是否可得尚需审定，不能混作本轮预测依据。

保持Qmin=.8。把.6提高为.8或.95没有科学依据；调整λ也不改变硬过滤。下一步应先规定可部署信号和预测目标、明确样本支持范围与误差，不再以synthetic先验承诺高可靠性。

## 4. 三分支机制候选：只冻结可证明部分

[新任务输入](deadline_pair_admission_20261014/TASK_PUBLIC.json)来自MultiHiertt dev UID `87db6a9c0c874dc4ba00221006d105b1`。原问题不改，保留全部4表及文本；曾出现在开发流程，**不是独立测试样本**。三个设施各自authorized/drawn差额再求和，原材料支持三个语义分支；算术操作为3减2加。可重写单表达式，不能由三分支/8节点宣称不可替代复杂优化空间。

公开输入不含Gold/program；[独立参考](deadline_pair_admission_20261014/EVAL_ONLY_REFERENCE.json)单独保存，只用于最终评分。引用原表第三号索引3的六个单元格，见[SOURCE_AUDIT](deadline_pair_admission_20261014/SOURCE_AUDIT.json)。原问“withdrawn”和表“drawn”的对应含义须在真实前独立确定；全文保留不等于已证明全部语义覆盖。

[人工机制IR](deadline_pair_admission_20261014/MANUAL_MECHANISM_IR.json)→[Graph](deadline_pair_admission_20261014/MANUALLY_VALIDATED_GRAPH.json)离线编译通过，8节点12边：

|节点语义|输入/真实依赖|输出|执行性质|
|---|---|---|---|
|extract|原始ctx_table|六事实，设施/列身份/引用位置|LLM|
|三个form_expression|共享extract facts，各选本设施两事实|三个不同expression|LLM×3|
|三个calculate|各expression + extract facts|三个派生差额及血统|工具×3|
|aggregate_values|三个calculate value|求和目标|工具|

流程层宽3；TypedExecutor目前串行，**未测并发收益**。图来源明确MANUALLY_VALIDATED，不计自动生成成功。完整原始来源哈希见新manifest；没有运行本图。

### 4.1 恢复动作及在线反馈

[RECOVERY_ACTIONS](deadline_pair_admission_20261014/RECOVERY_ACTIONS.json)枚举NONE、LOCAL/FULL各两种目标模型。LOCAL后代闭包3节点（1LLM+2工具），FULL8节点（4LLM+4工具）。LOCAL复用上游extract和另外两分支必须校验图/输入/输出身份、完成状态与血统；FULL另建同图执行器并共享同一预算，不篡改已DONE输出。

**必须修正准入解释**：提议注入“表达式引用不存在事实”是可观测、无Gold的合同失败，但现有`TypedExecutor.recover_failed`明确禁止对FACT_MISSING/REFERENCE_CHANGED盲目reroute。因此文件中结构合法动作都标记`execution_adapter_ready:false`；[SCENARIO_ADMISSION](deadline_pair_admission_20261014/SCENARIO_ADMISSION.json)明确拒绝把它们当实际可执行恢复动作。下一版本可独立审定执行器允许的输出合同失效，或具备依据的上游修复动作，**不能绕过血统保护**。本轮不实施注入、更不伪称动态调度运行过。

其他接口缺口：旧scheduler闭包/动作菜单绑定e1/e2/r/v；Typed只支持失败目标显式有界reroute，不等于完整π向量进入通用联合调度。`heterogeneous_models.allocate`将工具仅识别为transformation，对aggregation查TYPE_BASELINE会缺键；它仍是本地三槽基线，不是新云registry。需最小可选适配而非复制调度器；本轮不扩展架构。

### 4.2 云模型及参数核对

这里只记录仓库实际请求构造，不宣称当前服务身份、计费或版本已经真实核验；本轮不读取密钥、不调用API。

|模型/地址|既有代码参数|本图准入|
|---|---|---|
|GLM-5.3 / GLM-5.3-Flash；open.bigmodel.cn/api/anthropic/v1/messages|temperature0，reasoning_effort low，8192输出，无thinking字段|未认证本图质量/时间/费用；未冻结进入主对照|
|deepseek-flash；api.deepseek.com/chat/completions|temperature0，2048，thinking disabled；旧real_call不支持response_format|历史格式参数证据，不是本图任务能力认证|
|qwen-plus；dashscope.aliyuncs.com/compatible-mode/v1/chat/completions|temperature0，2048；该旧real_call**没有显式enable_thinking或JSON response_format**|不能把旧函数默认等同已冻结非思考JSON适配|

因此必须冻结真实最终body、模型响应身份与参数差异，不可只拷TUNED_THETA当传输已一致。GLM现金函数UNKNOWN不得当免费。提议先qwen/DeepSeek两池机制候选，GLM不在未验证时硬塞入对照；这不是已完成四池冻结。

## 5. 公平配对与资源草案（未获执行授权）

Single直接接收同一完整原任务；静态恢复预先固定FULL和模型；反馈策略从合法候选中选(Z,R,π)，不读Gold/silver。两臂冷缓存隔离，同原始图、同失败位置和签名，保留注入前真实响应与费用。局部缓存节省应算在动作后增量，同时报告包含base的全过程Q/C/L。不同模型输出模式差异必须记录，不能把参数失败归为能力排名。

4个LLM节点正常双臂+Single为9请求；静态FULL8、反馈LOCAL5、Single1合计14；反馈也选FULL则最坏17。不自动派发17请求，协议尚未准入。费用、Token包括失败/注入前响应、未知usage预留；确定性工具不算LLM。无额外模型审查/重试。

[BUDGET_DRAFT](deadline_pair_admission_20261014/BUDGET_DRAFT.json)提议每请求输出2048，17请求输出参数总上限34816，输入总上界/现金仍未认证；不能称它为联合Token硬上界。客户端120秒/请求，2160秒全局（17×120+120保存），只是草案，不等于任务期限D。历史默认HTTP180秒也不能直接满足此草案，需要入口适配与独立审批。

**任务D没有冻结**：没有针对本图/云池的冷执行或指定post-fault条件的校准数据，不能随便取宽期限制造可行集。保持Qmin=.8；没有依据把本地合成质量或按时信念迁移。Q为执行后独立准确性及引用覆盖；在线反馈只用合同/血统错误，不用Gold。C报告实际usage及账单待核验，L同时报告节点API、调度/排队、完整端到端和实验墙钟。未来费用不确定探索须独立风险授权，不修改正式StrictMeter。

## 6. 七项门禁

|要求|结果|证据/最小下一步|
|---|---|---|
|时间口径一致、错误已归因|部分|133秒缓存切换根因确认；未来队列/切换分布仍无校准，统一deadline与settle时间锚|
|任务具备真实组合优化空间|部分|自然三设施汇合，闭包成本不同；单表达式可替代，实际模型边际收益未证|
|合法恢复动作可枚举|结构PASS，执行FAIL|LOCAL/FULL闭包可算；拟用缺fact失效被现有reroute保护拒绝|
|联合(Z,R,π)实际传入执行器|FAIL|旧四角色scheduler与新Graph不通用，Typed局部API非完整联合适配|
|质量/时间预测无不可部署信息且有依据|FAIL|手设synthetic非校准；新任务云池无支持，不能放宽Qmin|
|模型/参数/预算/停止冻结|部分|文件身份冻结；实际cloud body、D、输入/现金缺认证或探索授权|
|Single/静态/反馈公平配对|设计草案|cold与conditional分列，不同输出协议及失败资格未完成准入|

**唯一最重要的剩余阻塞：可部署、与实际执行口径一致的任务级质量和端到端时间预测依据缺失。**这不是说它是唯一工程缺口；联合动作和失效资格也需最小接线验证，不能绕过。当前NO-GO不以“不能保证成功”为理由，而以预测常数被当作真实门禁和动作未实际接入为依据。

## 7. 验证范围与最终裁决

本轮只做历史账本复算、人工机制Graph严格编译/validate、闭包和文件身份检查，结果见[OFFLINE_CHECKS](deadline_pair_admission_20261014/OFFLINE_CHECKS.json)。未增加生产功能或重复整套Mock来替代真实证据；没有新的生成、恢复或质量成功样本。

- **时间计量错误/执行编排：确认具体cache-before-switch顺序问题**，绝大多数决策前耗时为不必要加载；不是证明所有过去时延双计。
- **预测校准失配：确认**，真实启动60–73秒 vs合成2–3秒，真实FIT与synthetic service/q并存，争用非真实队列遥测。
- **真实截止不足：31次在原运行决策时必然不足；15次未来完成UNKNOWN。**无需制造宽D。
- **任务缺恢复机会：未证明。**候选非空，但合同修复是否改变正确率、自然三分支是否提供净收益还无实证。

最终：**NO-GO；0新请求，不启动GPU、不提交Git。**保留全部旧失败与UNKNOWN。下一步先限定最小支持范围，审核可部署预测和真实合法失效/联合动作接口；不能从去争用反事实或人工图编译通过直接跳到17次付费试验。
