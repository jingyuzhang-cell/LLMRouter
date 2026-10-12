# Stage 3 异构模型分配接线：零调用验收

## 1. 实际模型池审计

复用static_dag_v0.run.MODELS的三个配置，但未假定历史可用即当前可用。MODEL_POOL_AUDIT.json保存当前检查结果：全部配置/权重SHA对照各slot_MODEL_PROVENANCE.json逐文件一致，权重组合身份SHA不同；三个Tokenizer本地加载成功，审计用时52.45秒，无GPU模型加载、无真实请求。

| slot | 实际检查点 | 权重文件大小 | 配置上下文 | 本入口服务上下文/输出上限 |
|---|---|---:|---:|---|
| medium | /root/autodl-tmp/models/Qwen2.5-7B-Instruct | 14.185 GiB | 32768 | 8192 / 768 |
| large | /root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8 | 15.503 GiB | 32768 | 8192 / 768 |
| coder | /root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct | 14.185 GiB | 32768 | 8192 / 768 |

large配置为GPTQ 8bit；medium/coder非量化bfloat16。served名称分别Qwen/Qwen2.5-7B-Instruct、Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8、Qwen/Qwen2.5-Coder-7B-Instruct。路径、served名称和权重内容组合均不同，不是别名同模型。medium/coder tokenizer.json相同，但tokenizer_config/chat模板不同；large tokenizer.json也不同，各模型独立加载并计数，不能由同一Tokenizer代替。

目前证明的是本地资产及Tokenizer可读、身份匹配，不是本轮服务加载成功。端点当前未启动。GPTQ CUDA/vLLM后端及当前显存足够与否需以后获授权的加载验证；不伪造健康检查通过。

## 2. 分配规则与适用范围

历史static_dag_v0.core.route使用全局profile Q−0.05C−0.05L，profile源于MMLU迁移先验，未验证可估计任意新生成节点的能力。因此不把它移植为“学习最优分配”。新heterogeneous_models.allocate为声明的类型基线：extraction→medium，reasoning→large，verification→coder；transformation使用确定性工具，assignment中的medium为执行器接口占位而非一次模型调用。单模型对照single_medium_baseline另行标注。若具体图仅含一种LLM类型，heterogeneous=false，不宣称异构成功。

分配不改图或依赖，ALLOCATE前后graph.content_hash不变；真实入口分别写UID_GRAPH.json与UID_ASSIGNMENT.json，包含policy、assignment、LLM模型集合、learned=false、optimality_claim=false。原TypedExecutor复用此assignment，无另一套执行器。

## 3. 正式调用接线

fresh_acceptance.main → 三模型绑定/各Tokenizer → InitialDAGGenerator(medium) → allocate(graph) → TypedExecutor.run/recover_failed → PreparedExecutor.call → prepare_metered_request(实际selected slot) → MeteredExecutor.call → SerialModelService.activate(slot) → ScopedBudget.reserve → HTTP payload model=engine.MODELS[slot].served → check_provider(selected/active/返回model) → settle。

不再固定cfg=medium；执行恢复继续使用失败节点分配的模型，不偷偷降为medium。实际请求身份、权重组合SHA、Tokenizer SHA、provider_id、provider_model分别写REQUEST_PRECHECK、MODEL_DISPATCH_IDENTITY、TRAJECTORY和MODEL_LIFECYCLE。缓存身份复用既有(model_binding,prompt,task,node,scope)，不同模型缓存不混用。

SerialModelService仅管理自己创建的单服务：启动前检查GPU/端口空闲，CLI绑定实际path及served名，健康后GET /v1/models必须确认正确model ID；若不可用/未验证/启动失败/返回身份不一致，明确异常，无静默回退或HTTP重试。切换旧进程卸载完成后检查GPU释放再加载，遇到外部进程不强停。未改static_dag_v0原start_model，避免写其冻结输出目录。

## 4. 异构资源包络

请求/Token界保持原ResourceEnvelope：每题最多4生成侧调用+6执行/恢复调用=10，27392 Token；两题最多20请求/54784 Token，仍容纳于获批24请求/56000 Token，阶段最坏13568/13824均小于14000。生成768、审查384、普通执行256、验证160输出上限。完整prompt按所选Tokenizer聊天模板计数；生成2048/修复3072/审查3072/执行恢复2048输入硬界，超过就拒绝，不截断事实或依赖。

RTX4090实测24564MiB总显存、0MiB占用。三模型权重合计43.873GiB，不能同时常驻；单模型权重也不能等同于完整推理峰值，KV/运行图/量化工作区另占，GPTQ large仍存在OOM风险。入口单GPU串行、max_model_len8192、max_num_seqs1、gpu_memory_utilization0.90，是否启动成功尚未真实验证。

最坏生成阶段medium连续，执行/恢复每次均可切换：每题最多1+6=7次激活，两题14。沿用300秒加载硬顶、20秒卸载顶、20请求×30秒绝对请求顶和30秒终局清理：14×320+600+30=5110秒（85分10秒）。这是一组限额的保守资源包络，不是预计实际耗时。原20分钟不足，入口在模型启动前拒绝；不自动扩大预算。单模型对照允许一次激活，不借此将异构标成通过。

建议后续异构信封保持24请求/56000 Token/每题12请求和阶段各14000，墙钟如需覆盖当前最坏服务包络可考虑90分钟；90分钟仍非任务一定完成保证，文件审计、CPU、驱动异常受全局截止约束。SerialModelService.activate会再次检查剩余激活、HTTP槽与清理的墙钟保留。模型加载失败请求数可能为0，但加载时间仍计入墙钟与生命周期日志。

## 5. 零调用验收

原209项全部保留，新增17项，总226/226（typed208 + evaluator/runtime18）。覆盖三模型分别分配、3/5节点、多根及前向依赖、同图混合模型执行、assignment/实际provider对应、同模型对照标签、不可用/未验证模型拒绝、不同Tokenizer预留、真实SerialModelService的Popen/健康API均Mock时串行切换与失败清理、provider错配拒绝、路径别名拒绝、20分钟拒绝/90分钟包络、失败reasoning按large恢复及下游继续执行。

端到端Stub复用generic CTX=2/3，未将两道冻结新任务用于Stub。Stub只证明接线与预算路径，不证明模型能力或真实服务成功。本轮真实请求0、GPU模型服务启动0。

## 6. 修改与剩余阻塞

新增heterogeneous_models.py、test_heterogeneous_models.py；修改fresh_acceptance.py正式绑定、Tokenizer计量、allocation保存、实际模型dispatch、生命周期清理与墙钟准入。SOURCE_HASHES与资源/测试证据独立保存，旧任务UID/内容/评分文件及冻结48入口、评分协议未修改。此前next_fresh_acceptance_v2的源码哈希描述旧入口，须在下一轮获批前另行版本化冻结；本轮不覆盖该冻结包或其他会话改动，无Git提交/推送。

阻塞仍为原20分钟异构墙钟不足，以及三模型当前真实加载/健康/OOM未验证。准备阶段任务不重复仍需下一轮启动前复核。等待新的明确真实调用授权，不启动服务；不能依据226项Stub测试宣称异构算法优势。
