# 两请求HTTP诊断：派发前接线错误中止

本轮已启动独立诊断，不使用四道冻结任务。新的公开诊断输入为标签包计数与预留问题，未提供或计算gold。没有DAG节点执行或答案评分。

## 前置检查

ab_preparation_v2源码、任务、Schema、模型配置及后端hash通过；284/284零调用测试通过；GPU空闲。完整权重审计通过，本地medium Tokenizer读取通过。A/B初始Prompt独立保存，完整/服务Schema经实际后端离线检查通过；每组最多1请求/5000Token，总2请求/10000Token。medium真实加载、GET健康检查和served身份通过，加载36.066393778秒。A/B设计使用同一模型、独立MeteredExecutor/Budget目录。

## 中止原因与零请求证据

诊断脚本向MeteredExecutor传入 `plan-only-A`。原smoke_runner.py make_executor_class.call在构造缓存身份时读取 `key.split(':')[3]`，键缺少该段而抛IndexError。该语句先于 self.prepare、budget.reserve 和dispatch，所以尚未发送HTTP。是新诊断入口的调用键接线错误，不是服务Schema HTTP错误，也不是LLM生成非法图。

RESULTS.json原样保存abort及两个Budget计数：attempts=0、actual_tokens=0、charged_tokens=0、A/B pending={}。结合实际代码顺序和无派发记录，确认本轮真实请求0；不是仅由账本文件缺失推断零消费。A实际HTTP状态NOT_SENT；B因中止未启动。无响应结束原因、JSON、完整Schema响应验证或Graph构造结果；全部NOT_EVALUATED，而不是合法率0%。

总墙钟90.941914964秒，包含文件核验、medium加载及清理。服务已停止，nvidia-smi无计算进程、GPU0 MiB。

## 修正与测试边界

已将调用键修正为 `typed:generate:v1:generate:0:<diagnostic_task_uid>`，只进行独立Stub MeteredExecutor验证：1次模拟尝试、7个模拟Token，身份解析与计量通过。这些不计为真实请求，不证明HTTP兼容。原执行脚本保存在EXECUTED_SCRIPT.py；修改后run.py的哈希和原脚本哈希见FINAL_EVIDENCE.json。没有再次加载模型或重新派发。

原284项回归结束后全部通过，日志见PRE_TESTS.log/POST_TESTS.log。原stage3_ab_real_01 29文件逐字节核验不变，历史1请求/2496未知Token预留保持原样；本轮零请求与历史未结算请求分列，未合并清零。没有修改冻结实验、固定48配置或评分协议，未提交或推送Git。

## 结论

真实HTTP兼容诊断尚未完成。本轮按遇错停止规则结束；修正入口具备Stub计量证据，但必须下一步指示后再执行真实两请求验证。未启动96请求正式A/B实验，未追加请求或自动重试。A/B Schema哈希在FINAL_EVIDENCE.json；响应Schema/响应字节哈希不存在，因为没有HTTP响应，不能虚构。
