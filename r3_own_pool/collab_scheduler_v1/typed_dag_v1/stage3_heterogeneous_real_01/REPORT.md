# Stage 3 异构模型加载与两题真实验收

## 结论
阶段A通过；阶段B两题均生成失败，未取得非回退图、真实节点执行或最终评分证据。所有调用来自本轮原冻结任务，未用Stub、旧图或固定回退冒充成功。完成后停止，未追加调用。

## 阶段A：真实加载与身份

| 模型 | 检查点/served | 加载及切换秒 | 健康结果 | 本轮观测显存峰值MiB |
|---|---|---:|---|---:|
| medium | Qwen/Qwen2.5-7B-Instruct | 38.205 | PASS | 22405 |
| large | Qwen/Qwen2.5-14B-Instruct-GPTQ-Int8 | 52.522 | PASS，GPTQ Marlin启动 | 22193 |
| coder | Qwen/Qwen2.5-Coder-7B-Instruct | 37.271 | PASS | 21997 |

三模型实际启动路径/权重组合SHA与离线来源绑定，实际服务GET /health与GET /v1/models均通过；Tokenizer从各自模型本地加载，SHA保存MODEL_POOL、STAGE_A_RESULTS。无模型别名替代。large日志记录gptq_marlin内核选择及服务启动；证明当前加载兼容，不足以验证真实业务推理性能。本轮large/coder未接受业务推理请求。GET不产生推理请求，阶段A请求和Token均0。

显存为0.5秒nvidia-smi采样、按当时active model归属的整个本轮观测峰值（medium含阶段B重新加载），不是保证捕获所有瞬态的硬件绝对峰值。GPU_MEMORY_SAMPLES与MODEL_LIFECYCLE保留原始记录。三模型串行卸载加载，无同时常驻，无OOM。

阶段A结束后剩余5214.914秒，高于阶段B最坏5110秒；STAGE_B_ADMISSION明确允许，且全局仍为0请求/0Token，预算槽未重置。整个运行共4次模型激活（三次加载验收+阶段B重新加载medium），总启动等待162.394秒。MODEL_LIFECYCLE分别记录所有ready/stopped；加载切换也包含在总墙钟内。

## 两题生成结果

| 任务 | 初始结构合法 | 修复后结构合法 | 语义审查 | 回退 | 节点执行/评分 | 请求 | Token |
|---|---|---|---|---|---|---:|---:|
| 太阳能净抵扣额 | 否 | 否 | 未到达 | 是，未执行 | 未执行/未评分 | 2 | 4015 |
| 两段行程平均速度 | 否 | 否 | 未到达 | 是，未执行 | 未执行/未评分 | 2 | 3705 |

首次完整结构合法率0/2，一次修复后完整结构合法率0/2，非回退图接受率0/2，真实完整执行率0/2，回退率2/2。语义审查调用0，因此通过率不可计算（不是语义拒绝率100%）；评分任务0，答案正确率不可计算。没有真实节点assignment/执行记录，不能宣称本轮实际异构节点执行一致性通过；实际验证仅4个planner medium请求选中/返回身份一致。

### 太阳能题
初始原件RESPONSE_01_RAW.txt，修复RESPONSE_02_RAW.txt；两者逐字节相同。五节点ref为nodes.0.ref至nodes.4.ref，这些是模型定义的字面引用句柄，本身不是悬空引用。关键错误是节点1/2/3均声明reasoning，输出expression，却被后续当作facts，以及节点3被verify-value当作number来源。compile_producer_plan报PRODUCER_TYPE_MISMATCH，在合同装配前拒绝。subtask/type并不一致（subtask写transformation但type仍reasoning），不能依据自然语言name/subtask自动改类型。唯一抽取节点ctx_table未包含ctx_text固定费，另有潜在语义覆盖缺口，但未运行语义审查，不将此记成已判定的审查结果。

生成1676 Token，修复2339 Token；两次finish_reason=stop，无截断。生成阶段墙钟48.535秒，含medium重新加载。

### 行程题
RESPONSE_03_RAW.txt与RESPONSE_04_RAW.txt。五节点全部type=extraction、input_producers={}、来源均ctx_text。初始final_output为n4，修复只改为n5；其他根节点仍不通向最终输出，装配/图验证报Dead branch does not reach final output。最末name虽calculate_average_speed、subtask虽transformation，type仍extraction，程序不能猜测补依赖或改类型。结构错误签名比较显示NO_PROGRESS仅指语义依赖预检查的空错误集；后续完整Graph校验确实连续失败，该标签不证明修复有效。

生成1651 Token，修复2054 Token；finish_reason=stop，无截断。该题生成阶段墙钟8.641秒。ctx_text不含第一段信息是潜在覆盖风险，未实际进入审查。

## 计量与清理

真实4请求、7720 Token（输入6692、输出1028），全部结算，未知pending为0；生成/修复7720，语义审查/执行/验证/恢复/模型评分各0。两题分别4015、3705，小于各生成14000；执行14000预留未被挪用。总墙钟243.671秒，含模型来源核验、加载、健康、生成和清理；没有超任何获批限制或HTTP重试。没有真实工作流答案、部署Q/C/L或节点Token可报告。未冻结本地货币计价，货币费用不可计算，不能写成0美元。

服务已停止，GPU结束后0 MiB。前后226项零调用测试通过；冻结源码哈希结束复核全部一致，任务内容/评分文件未改变。本轮新增Stage A闸门与采样在启动前完成源码冻结，未运行中改代码。旧冻结实验、48配置入口、评分协议未修改，无Git提交/推送。

## 原始证据与后续

PROTOCOL/获批packet保存哈希与信封；MODEL_POOL/STAGE_A_RESULTS/MODEL_LIFECYCLE/GPU_MEMORY_SAMPLES保存加载证据；HTTP_INPUTS/OUTPUTS和RESPONSE原件保存四候选；GENERATION_EVENTS保存具体类型/图错误；DISPATCH/PHASE_BUDGET/ENVELOPE_PREFLIGHT保存调用预留、用量和未来槽；GENERATED_GRAPHS中的两图是固定回退，不能计生成成功；RESULTS为终局。

当前阻塞已从模型加载转为真实规划的节点类型/生产者输出一致性与最终输出可达性。下一步宜零调用重放这四份候选，给修复器精确的类型输出及dead-branch节点反馈；不得为本轮成功自动改类型、补边或追加生成。真实端到端第三阶段仍未验收，等待下一步指示。
