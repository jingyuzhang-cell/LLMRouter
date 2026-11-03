# 缓存切换顺序修复与截止时间口径专项

日期：2026-10-14。范围：最小生产修复及零调用验证。**0真实LLM请求、0GPU启动、未重跑60题、未执行17请求实验、未修改历史结果或提交Git。下一次真实配对：NO-GO。**

## 1. 最终回答

**原31次过期决策全部受到同一笔可避免的缓存切换开销影响。**历史DD决策前180次调用均cached，仍执行coder→large、large→medium两次切换，合计133.029351秒。它是整个共享阶段的一笔耗时，**不是每题各花133秒，不能乘31累计**。

只扣除此两次已观测切换、不改变旧截止时间，31/31条记录会重新拥有正剩余时间，范围67.766428–113.326266秒。但这是**条件时间反事实**：要求同模型/版本/合同/输入/参数的缓存仍经新协议核验有效；不含新身份核验CPU、真实后续调度及恢复时间。旧格式缓存不能被新入口直接信任，旧记录也不足以追溯认证全部新增身份字段。因此不能将31/31写为真实恢复成功、质量改善或新期限内完成。

修复消除了合法缓存命中的无效模型启动，以及将历史推理延迟作为本次缓存服务时间的记账缺陷；没有解决质量先验、争用/P90校准、通用联合恢复接线和云模型池数据缺失。

## 2. 精确调用链与切换原因

真实链路：`confirmatory_launch.main` → `joint_verification_runner.execute` → `arm_engine_from_snapshot(real=True)` → `supplementary_runner.RealEngine`工厂生成的`_Real(StubEngine)` → `run_cell/run_jobs/_run_stage` → `StubEngine._call` → `_Real._switch` → `ModelManager.stop_current/start` → `static_dag_v0.run.start_model`。

- 原切换位置：[StubEngine._call](deadline_reward_v1/stub_engine.py:265)先调用`self._switch`，再计算`input_signature`和检查`self._cache`。
- 真实切换实现：[RealEngine._switch](deadline_reward_v1/supplementary_runner.py:445)，调用真实manager并记录单调时钟耗时。
- 缓存拥有者是`StubEngine._cache`；`prepare_shared_base`复制到各臂，不存在独立的“必须启动服务才能查缓存”步骤。
- `dag_closure.input_signature`使用UID、节点、对应静态来源及实际父答案（v还含祖父事实）。它不直接绑定问题、模型权重版本、合同和请求参数。
- 旧键仅`(model槽位, input_sha)`，同一槽位权重/Tokenizer/Prompt改变、问题变化等不能由旧键充分识别。不能原样前移后就宣称安全。

### 缓存合法性核验不需要GPU

真实Prompt可以由冻结任务、已有父输出和构造器产生，模型/Tokenizer/权重可以读文件核验。当前本地服务不存在必须先模型加载才产生缓存身份的已知特殊情况。若将来是只在远端响应时才能获知动态模型版本的服务，则该provider不能借本修复提前复用；必须另行认证身份或禁用缓存。

## 3. 最小生产修改

|文件/函数|改动|
|---|---|
|[stub_engine.py](deadline_reward_v1/stub_engine.py:265) `_call`|先核验上下文、上游输入和provider identity，形成complete-cache-v2键；仅miss/失效/no_cache才切换；没有provider身份则不允许缓存复用|
|同文件 `StubModelServer.cache_identity`|显式合成版本、fixture、配置/参数与合同变体身份；不把Stub身份当真实模型认证|
|[supplementary_runner.py](deadline_reward_v1/supplementary_runner.py:314) `RealServer.cache_identity`|启动前核验实际模型配置和manifest权重哈希，计算Tokenizer文件哈希、完整Prompt哈希及构造器/传输源码哈希，绑定model配置、节点、kind和profile|
|[joint_verification_runner.py](deadline_reward_v1/joint_verification_runner.py:531) `execute`|每臂一个单调起点，决策与结算共用绝对deadline；新增deadline_anchor保存未舍入起点、偏移和期限；原D偏移、ε、Qmin及奖励不变|

新键包含模型槽位及实际配置/文件身份、问题、静态来源哈希、节点及父/祖父输入、拓扑/族、合同变体、实际Prompt、执行源码及参数身份。源码哈希同时绑定512输出、temperature/top_p等实际本地请求构造；不是用人工填写的版本字符串代替真实检查。

真实模型manifest内列出的全部权重/配置在首次使用时逐文件内容核验；Tokenizer文件实际内容哈希也加入身份。复用同一manager会话已验证结果时，核对文件路径、inode、大小、mtime/ctime及manifest哈希，变化则重新完整验证。**这是可信本地文件系统会话的检查，不是抗同权限恶意篡改/TOCTOU的强隔离保证**。未声称vLLM所有依赖字节均内容认证；真实调用miss仍由原服务启动与身份检查约束。

旧缓存格式不自动升级，按miss处理。恢复显式`no_cache`保持优先；故障仍在计量之后作用于返回副本，不污染缓存。缓存存储/返回使用深拷贝，避免消费者反向改写usage或原响应。

### 成本和计时

- 缓存命中：不切换，不调用draw，不新增physical requests/Token；`latency_s=0`表示无本次模型服务，原推理时延另存`cached_response_latency_s`，历史usage仅留作来源记录。
- `cache_lookup_s`单独记录；任务总墙钟从身份检查起点算起，因此读取/哈希CPU开销不消失。不能把命中成本称为绝对0墙钟。
- miss：保持切换→真实派发，原预算reserve/settle、合同检查、调用次数与分配不变。真实provider在身份检查前后检查现有预算截止。
- 身份检查失败：记录`cache_identity_failed`并抛错，不启动服务、不退回旧缓存。
- 复用scope、R后代闭包、父输出签名和no_cache行为未放宽。主调方原finally清理仍负责异常退出，本补丁不创建第二套生命周期控制器。
- 原RealServer历史路径的重试设计未在本轮改写；新无重试实验不能直接把它当符合云端无重试入口，仍须独立准入。

## 4. 133.03秒的归属与31条反事实

原证据位于`deadline_reward_v1/confirmatory_runs/conf_20261012_214907/DD/TASK_LEDGER.jsonl`。

|事件|开始单调时间|结束单调时间|耗时(s)|
|---|---:|---:|---:|
|coder→large|32488996.268379893|32489068.874507885|72.606112957|
|large→medium|32489068.919700593|32489129.3429551|60.423238177|

两区间不重叠，均在首个动态决策前；记录的是stop/start整个调用墙钟，不能继续拆成权重读取、健康轮询等阶段。原日志不支持更细归因。这133.029351秒占panel_start到末次前置call结束的133.095302秒下界的99.9504%。第三次medium→coder位于决策之后，未扣除；其他间隙/文件写入/准备时间也未扣除。

[31条逐UID反事实](cache_switch_repair_20261014/DD31_TIME_COUNTERFACTUAL.jsonl)保留原release、原剩余时间、原D舍入记录、账本行号与观测时长。原剩余−65.262923至−19.703085；仅加共享133.029351后为正31条。见[汇总](cache_switch_repair_20261014/COUNTERFACTUAL_SUMMARY.json)。

不是将31题时间轴分别重演，也不是把回收133秒分配给每条修复；它们共用阶段，后续仍可能排队。历史绝对deadline未完整保存，使用原始已记录d_remain，不用舍入D假造精确时间；新版本deadline_anchor消除此后续可观测性缺口。

## 5. 剩余15次：时间预测证据缺口

其历史DD剩余93.479161–93.687170秒，均wide。不同成本来源必须分列：

|量|现有依据|能否作为可信任务级预测|
|---|---|---|
|前置缓存服务|180次cached、physical=0；历史响应latency为参考|不能当本轮新推理；已修复|
|前置切换|两次实测60–73秒|是本次运行观测，不是任意恢复路径的分布|
|实际服务|独立FIT包含各菜单服务均值及分位数|只支持特定本地菜单/条件，不含完整排队/切换|
|策略未来服务|实际入口仍传PRIORS_STUB_V1，r均值5/10、v7/14秒等|合成常数，非当前任务校准|
|策略切换|stop .5，start2/3/2.5秒|与实际60–73秒明显失配|
|未来争用|其他任务remaining_work_est，初始每任务10秒，合计140–590秒|启发式剩余工作，不是实际队列遥测|
|端到端排队与恢复|动态臂未派发相应恢复请求|无候选级实际完成证据，UNKNOWN|
|新云池服务/排队|零散旧调用、不同任务/参数|不支持此图此失败条件的质量/按时概率|

未发现过去切换被未来shift重复显式相加的直接证据；future shift在e1_on_time仅加一次。错误主要是执行顺序和预测量的适用条件，不是简单“删掉所有争用”。正态CDF的0来自极负z值的数值饱和，稳定CDF也远达不到1−ε；不能强制改成正概率。

### P90覆盖率

[RELIABILITY_ROUND_CLOSEOUT](deadline_reward_v1/RELIABILITY_ROUND_CLOSEOUT.md)已记录6/10格点覆盖率低于.90，其中r|large .821、r|medium .757、v|coder .875；部分SCREEN/VALIDATE为探索性，**不是端到端或云模型按时概率认证**。重复FIT同24题同身份只证明同条件稳定。争用阶段从未启动，无真实队列预测证据。旧可靠性路线已关闭，本轮不重启其校准任务。

### 最小真实测量需求（本轮不执行）

先复用可对应实际body/节点/模型版本的既有调用记录；无法对应的字段标UNKNOWN。未来需独立批准的最小定位测量是：一条该图冷执行的节点完整时间线、缓存重复的lookup墙钟，以及一个合法恢复动作的真实后续时间线；同时记录请求派发/响应、父输入、预算、队列状态和模型参数，不加额外LLM审查。它只能验证分量和接线，**单轨迹不足以校准P90或q≥.8**。

若仍要以ε和Qmin作概率保证，必须在明确任务分布和参数下有独立的任务级正确性/按时覆盖评估及误差；不能把一次成功或旧本地先验当新云池校准。当前不能诚实冻结此图D或声称17请求可验证可靠性。本轮不提供自动重跑计划、不降低原约束。

## 6. 三分支图及联合恢复只读结论

沿用`deadline_pair_admission_20261014`已冻结8节点12边人工机制候选，本轮不改图。

- 结构层可枚举LOCAL和FULL，及不同目标模型π；LOCAL后代闭包3节点（1LLM+2工具），FULL8节点（4LLM+4工具）。这只是结构可枚举。
- `TypedExecutor.recover_failed`允许失败节点显式有界reroute，且受已消费输出、模型bindings、重试上限约束。格式/JSON/输出合同类失效原则上可进入该接口，必须先定位具体错误码和失败状态；HTTP/预算故障不能一概当适合模型恢复。
- FACT_MISSING、UNIT_MISMATCH、UNIT_SOURCE_MISMATCH、DERIVATION_UNTRACKED、REFERENCE_CHANGED被显式拒绝盲目重路由：这些可能是上游事实/来源失效，换下游模型不能凭空修复。现有拟议“缺fact引用”注入尚未通过恢复资格，不能为准入改保护。
- 通用(Z,R,π)完整向量尚未传入Typed；旧scheduler仍绑定e1/e2/r/v，Typed只替换失败目标的assignment。FULL需要新执行实例和原图、同一预算身份；当前没有统一闭环。
- 原type-baseline对aggregation工具处理不完整；本补丁不扩大到此模块。
- GLM/DeepSeek/Qwen身份、实际body及版本、输出模式、计费和此图时延/质量证据未共同冻结。旧静态本地池不是云池；GLM未知费用不等于0。既有传输参数差异仍需审定。

所以修复缓存并没有让此图突然具备两个**已接线可执行**的联合恢复动作。

## 7. 离线验证与兼容性

新增[test_cache_switch_order.py](deadline_reward_v1/test_cache_switch_order.py)15项：命中不切换/不收费/不重记服务，miss切换，模型/版本/问题/来源/参数/合同不误用，上游变化失效，no_cache恢复，注入不污染，旧snapshot拒绝，新snapshot合法复用，timeout不写成功缓存，提前停止，重复实例拒绝，以及带临时模型文件的RealEngine/RealServer facade验证（无GPU、无真实HTTP）。

12个受影响旧测试套件在复制的证据目录运行，网络及模型进程启动被阻断，仅允许只读git身份查询；结果见[REGRESSION_RESULTS](cache_switch_repair_20261014/REGRESSION_RESULTS.json)及[详细输出](cache_switch_repair_20261014/REGRESSION_OUTPUT.txt)。这是相关回归，不冒称全项目所有测试。

测试迁移均有具体理由：

1. 旧生产参考缓存不区分合同kind；参考Prompt键加入合同变体，保持原答案/恢复决策和独立参考执行器，其旧调用数不再充当新合同约束。
2. 混合计量样例显式重复同合同请求形成缓存命中，不再依赖跨kind复用。
3. 缺真实模型文件的FakeMod改为明确MockIdentityServer，实际checkpoint/Tokenizer匹配另由新fixture核验，生产入口不放宽。
4. stdlib白名单增加copy，仅用于缓存深拷贝；新增真实启动器deadline_anchor完整性断言。

所有测试输出写新目录，旧测试证据不被覆盖。新版本源码与原冻结源码不同，旧冻结协议应报告哈希漂移；不改写旧冻结哈希来允许直接重跑。未来实验须另冻结本补丁版本。

## 8. 已消除与仍未解决

|状态|事项|
|---|---|
|已修复并离线验证|完整身份命中时无效switch；旧键/不同版本/不同输入误复用；历史服务时间算成当前缓存服务；决策/结算双起点；新增身份/时间证据|
|未证明实际收益|新版本真实切换节省多少、31题恢复是否按时且正确、缓存核验CPU及实际调度反应|
|仍阻止配对准入|q=.6/.95等手设先验、未经校准争用与端到端概率、通用联合动作未接通、缺事实失效不可盲修、云池参数/成本/时延未认证|

**最终NO-GO，理由是仍缺实际合法联合动作与可信预测依据，而非要求模型保证成功。**可确认的执行顺序缺陷已经落实修复；不能用它洗掉原46次降级或将条件反事实计作真实动态收益。历史数据和A图均未修改。
