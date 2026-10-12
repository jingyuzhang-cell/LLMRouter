# Trace60 零调用审计与修复

本轮真实请求为0；未启动模型，未修改历史候选、账本、48配置或评分协议；未提交或推送。

## 清理根因与修复

历史 `execution/DRIVER_EXIT_TRACEBACK.log`：外层finally调用mark，mark仅在内层dispatch导入，NameError发生在service.close前。当前 ab_review_diagnostic.main 的finally调用 run_cleanup.finish，先记录停止请求，再调用自有服务close，独立记录日志/close错误，保留原abort，保存清理开始/结束单调时钟、结束UTC Unix时间和总墙钟。恢复原信号处理器后最终snapshot。SerialModelService.close仅停止自身Popen，不按模型名称杀其他会话。GPU文件上下文退出释放flock；清理重复调用安全。

测试10项新增：真实helper调用覆盖原mark作用域错误、日志NameError仍关闭、close失败独立记录、正常/异常退出标签、幂等、文件锁释放、全部来源审计、无数字规则、语义不确定、历史错误PASS重放。退出标签测试验证公共清理helper，未启动真实服务，不等于各HTTP异常真实集成实验。381 Typed +18固定回归 =399/399通过。

## A来源缺陷

任务表格186/249是收集量，文本17/28分别是泄漏与清洁消耗，均影响剩余目标。历史REQUIRED_SOURCES_2只列ctx_table。/tmp/freeze_bounded.py:31继承按任务索引的(i==1 or k==ctx_table)筛选，漏掉第二题文本需求；这是准备合同遗漏。A仅n0抽取ctx_table，n1表达式→n2计算→n3/n4验证，文本无绑定路径；这是规划遗漏。来源检查只验证已声明需求，所以按原冻结合同接受，不能证明完整需求。原审查PASS声称全部操作数存在且来源正确，是审查漏检；没有实际节点执行，不推断实际答案。

新task_source_audit.freeze_requirements要求每个公开来源独立作REQUIRED/IRRELEVANT/UNCERTAIN判断，留存精确原文、DATA/RULE/MIXED类别、理由、审阅者、版本及输入哈希；不根据是否含数字筛选，不接受Gold参数。产物不是语义正确性证明；一般规则与数据依赖的通用表示尚有限，UNCERTAIN保留语义审查需求。本新开发包冻结表格+文本需求，未改历史包。历史图在原要求下通过，在新要求下拒绝，原review PASS原样记录于HISTORICAL_REPLAY。

## B及计时证据

request_id typed-b9f621ada8d84b12acc65e0abd4d59db，dispatch Unix1791772922.3231635，客户端错误1791772982.323543，60.000333894秒。无响应头/usage/可关联服务端阶段；服务器仅聚合Waiting1，不足以确认B收到、Schema、prefill/decode或取消。仍UNKNOWN_TIMEOUT，7592未知预留保持不变；此前7250记录未改。历史末snapshot245.935943不是完整结束时延，完整结束UNKNOWN。历史模型ready加载67.09655秒；无正常stopped事件，事后释放不能补造清理结束时间。

## 新冻结与建议资源

新版本bounded_ab_water_cleanup_source_v1：开发回归水量任务，不是新独立泛化样本。A输入3191+输出4096=7287；B输入3533+输出4096=7629；各自审查最高8192（输入7936/输出256），未知失败留足全请求预留。A15479/B15821，全局31300 Token、4请求、664秒（CPU94+加载300+4×60+清理30）。这是建议而非授权，不能沿用31226信封执行修改后的Prompt。复用历史模型快照，当前文件配置/Tokenizer门禁重新核验；完整权重内容在真实加载前仍须audit_pool重查。Prompt、Schema、来源及全部源码均重新冻结。

离线完整性GO；真实调用尚未授权。无已知必修软件硬阻塞。GPU锁/服务身份/余量须在下次运行实时核验；清理进程wait有界但OS故障、不可中断I/O或磁盘失败无法绝对保证。当前finally已执行可用路径，但真实清理与超时取消尚需受限真实诊断验证。60秒是否足够及模型规划语义完整属于可测量失败，不能以保证成功作为门禁。本轮停止，不进行新增调用。
