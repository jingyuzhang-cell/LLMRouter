# 真实A/B诊断结果

启动前冻结哈希、来源审计和399项测试通过，GPU空闲、锁可获取。真实medium身份与冻结权重一致，健康检查通过；加载39.06秒。

A：1请求，HTTP200、JSON完整、严格Schema通过，finish_reason=stop，无截断。用时53.53046秒，输入3191/输出271，共3462 Token。候选节点及生产者依赖原件见FINAL_EVIDENCE及T2_A/generate_HTTP_RESPONSE.json。total_collection_node输出expression，却被remaining_liters_node和answer_node引用为facts；PRODUCER_TYPE_MISMATCH。合同装配拒绝，无合法执行图，目标链/来源完整性未建立，语义审查跳过，非回退接受=false。不能将检查尚未到达报告为来源通过。

B：1请求，60秒超时，无响应/JSON/Schema/DAG，审查未执行，非回退接受=false。请求ID typed-ab31f46cf3354d699c1e7dd2b7920d20。无可靠usage，保留7629 Token（3533输入+4096输出）。具体服务端接收、Schema、Prefill、Decode及取消阶段UNKNOWN；聚合日志不作为该请求阶段证明。未重试。

总2请求，已知3462 Token，未知预留7629，合计计费保留11091；均低于4请求/31300上限，各组未转移预算。完整墙钟209.16611秒，结束时间见FINAL_EVIDENCE.end_utc，非中间快照。finally清理1.21701秒，service_stopped=true、errors=[]，有MODEL_LIFECYCLE stopped记录。事后nvidia-smi无计算进程，非阻塞flock成功。清理修复得到本轮真实超时退出证据；不能据此证明所有潜在异常路径。

结束后381 Typed +18固定回归=399/399通过。没有DAG节点执行、最终评分、修复、回退或额外调用。历史7592与7250未知预留及旧冻结记录未改；本轮7629为独立新预留。未提交或推送。仍存在A类型规划错误和B不可定位超时，实验停止，不自动新增诊断。
