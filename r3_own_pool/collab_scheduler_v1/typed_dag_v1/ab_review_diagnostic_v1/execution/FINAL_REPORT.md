# A/B必需输入合同真实诊断终局

授权4请求/22730Token/544秒。实际2请求5517Token/105.23秒，无未知用量预留，无修复/HTTP重试/回退/节点执行/评分。两组medium Qwen/Qwen2.5-7B-Instruct，真实模型身份与冻结权重一致。服务停止，GPU终局无计算进程，前后325/325测试通过，冻结及历史文件哈希复核一致，无提交推送。

A：HTTP200、stop、JSON完整、严格Schema通过；每节点显式输入角色与生产者类型检查通过。但final_outputs指n4，n3、n5均不沿依赖进入n4，FINAL_OUTPUT_CONNECTIVITY在装配前拒绝。因此没有装配图，不应称结构成功；保存原响应和诊断用normalized plan，未人为改终端或删分支。生产来源检查尚未到达；另做不改变候选的离线来源路径审计：只有ctx_table被选入最终链，必需ctx_text缺失。这个诊断与真实停止阶段分列，不能替代生产已运行来源检查。语义审查未执行，非回退准入否。

B：HTTP200、stop、JSON完整、严格角色Schema通过。名为calculate_remaining_labels的步骤operation实际为form_expression，其输出expression_remaining_labels与前一form_expression相同→IR_AMBIGUOUS_PRODUCER。Schema按声明operation验证，无法证明description/name与操作语义一致；没有真实calculate节点，remaining_labels没有声明生产者（原始数据观察，非后续验证已通过）。严格编译在重复符号处拒绝，未继续结构装配或来源检查；语义审查未执行，非回退准入否。角色归一化内存副本仅作诊断，未改名、补节点、补边。

逐组Token与账本见LAYERED_RESULTS.json和A/B/DISPATCH.jsonl；墙钟105.23秒含单次共享模型加载及清理，不人为平分加载给两组。账本response.latency_s及MODEL_LIFECYCLE保留各阶段时间。

结论：真实HTTP与Schema兼容成立；角色Schema阻止声明操作缺必需键，但不能阻止模型选择错误操作或重复符号。A/B均0/1非回退准入，审查0次，不能计算审查通过率为0/2（无已审查分母，应NOT_TESTED），不证明端到端或泛化。该任务已暴露，不能用于确认性效果主张。

后续建议：停止同题反复追加Prompt诊断；先零调用分析目标符号是否有唯一生产者、终端选择与全部必要分支的一致性，以及错误operation为何仍匹配描述。保留保守拒绝，不自动改operation、补依赖或把Schema通过当任务正确。任何后续真实任务须独立冻结与授权，正式四题仍未启动。
