# 独立run02真实诊断

本轮使用已批准4请求/31300 Token/664秒信封，冻结Prompt和Schema未变；上一轮账本独立保留。

A：1生成请求，HTTP200、JSON完整、严格Schema通过、finish_reason=stop，无截断。五节点候选：collection/usage抽取→total_collection表达式→remaining_liters表达式→answer计算。total_collection表达式被remaining_liters及answer的facts引用，PRODUCER_TYPE_MISMATCH；未完成合法DAG装配，来源与目标链完整性未建立，语义审查跳过，非回退接受=false。实际3462 Token。

B：1生成请求，60秒超时，无响应、JSON、Schema或DAG。具体服务端处理阶段UNKNOWN，未获可信usage，保留7629 Token。未审查，非回退接受=false。

全局请求2，已知3462 Token，未知预留7629，合计11091，完整墙钟206.49047秒。cleanup={"cleanup_start_monotonic_s": 32463528.863866854, "cleanup_end_monotonic_s": 32463531.03193283, "cleanup_wall_s": 2.1680659763514996, "total_wall_s": 206.49043527245522, "finish_unix_s": 1791788724.6722836, "service_stopped": true, "errors": []}。事后GPU无计算进程，非阻塞GPU锁可获取。结束后381+18=399测试全部通过。无重试、修复、节点执行或评分；无提交或推送。旧7592/7250和上一轮7629未知记录不改写、不混算。本轮按停止规则终止，不追加调用。

A与上一轮重复类型错误；B重复UNKNOWN_TIMEOUT。本结果不证明生成成功或语义完整，不能靠无限重复实验解决。原始响应、请求ID、时间线和账本均位于本execution目录。
