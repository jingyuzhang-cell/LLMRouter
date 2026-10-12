# run02真实HTTP诊断结果

仅执行授权的两次medium规划请求，未执行DAG节点、未语义审查、未最终评分。

|组|HTTP|结束原因|JSON完整|严格Schema|DAG装配|Token|请求墙钟|
|---|---|---|---|---|---|---|---|
|A input_producers|200|stop|是|通过|合法4节点|1920（输入1714/输出206）|7.15秒|
|B goal_ir|200|stop|是|通过|拒绝|2048（输入1585/输出463）|9.73秒|

B错误：IR_AMBIGUOUS_PRODUCER，calculate_remaining_labels与verify_remaining_labels均输出remaining_labels（分别calculated_value和verified_value），违反符号唯一生产者约束。保留原响应，未自动改名或修复。此错误属于语义规划/符号约束，不属于HTTP或Schema服务错误；后续错误未据此推断。

总计2请求尝试、3968实际Token，未知待结算预留为0；含模型核验、加载、请求与清理墙钟104.07秒。实际模型Qwen/Qwen2.5-7B-Instruct。RESULTS记录service_stopped=true，终局nvidia-smi无计算进程。前后290/290测试均通过。历史输入哈希复核保持不变，旧2496未知预留未结算或修改。未提交或推送Git。

通信兼容性：两组通过本次真实HTTP诊断。A结构合法不代表语义正确或执行正确；B仍有符号规划失败。已具备请求发送的技术条件，尚未形成正式四任务A/B准入或成功证据；该实验需要独立授权，不自动启动。

原始证据：RESULTS.json、A/B/HTTP_INPUT.json、HTTP_RESPONSE.json、RAW_CANDIDATE.txt、A/GRAPH.json以及各组计量账本。
