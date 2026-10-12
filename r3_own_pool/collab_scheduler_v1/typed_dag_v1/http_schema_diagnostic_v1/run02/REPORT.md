# 最小HTTP诊断第二轮：仅准备，未授权执行

run02已建立，实际HTTP请求0、模型加载0。290/290零调用测试通过（原284项+新增6项，typed272 + evaluator/runtime18）。原run01与stage3_ab_real_01文件逐字节SHA核验通过，旧HTTP400的2496未知Token预留保持原样。

## 原IndexError回归

新增test_http_diagnostic.py.test_original_short_key_before_reserve：向原MeteredExecutor传入plan-only-A，稳定复现IndexError；验证dispatch未调用、Budget.attempts=0、pending={}。修正通过http_diagnostic.call_key生成typed:generate:v1:generate:0:<UID>，禁止空UID或含冒号；与原执行器task/node缓存身份解析一致。

A/B各自Stub完整走build_request -> MeteredExecutor/Budget.reserve -> decode_response -> Budget.settle -> full_validate -> 原producer/IR编译器 -> assemble_semantic -> 原validate。两种计划均成功构图；只是人工Stub样例，不是LLM成功。另覆盖错误UID、provider身份错误、JSON不完整、finish_reason=length及网络失败未知用量预留。

## 真实接口参数核验（零HTTP）

HTTP_REQUEST_A/B.json是准备发送的实际参数：同一medium served ID；user消息；temperature0/top_p1/max_tokens768/stream=false；response_format=json_schema、strict=true、name=diagnostic_plan、确定性转换后的Schema。以部署vLLM 0.11.0的真实ChatCompletionRequest.model_validate分别解析通过；xgrammar后端纯预检与编译通过。REQUEST_PRECHECK记录完整/服务Schema hash、后端源码hash及调用键。

该核验会导入vLLM请求类型并检测CUDA平台，但没有创建模型引擎、加载权重或HTTP请求。DTO解析不保证服务round-trip成功。原完整Schema仍用于响应严格校验，服务层只省略已确认不支持的uniqueItems；类型、引用、环及连通性校验未放松。

## 新入口与冻结

新增http_diagnostic.py纯函数：call_key、build_request、decode_response、assess_plan。decode_response验证served身份、单个choice、非空content及非负整型usage和总量一致；异常由计量器保留未知预留，不自动重复请求。assess_plan分别标记JSON完整、截断、完整Schema、语义/合同及合法Graph，不执行节点或评分。

新增http_schema_diagnostic_v1/run02_entry.py：默认只核验run02冻结源/输入hash后退出。--execute（未来明确授权后）才创建run02/execution目录并走真实medium加载与两请求路径。每组1请求/5000Token、全球2请求/10000Token/1200秒（含30秒清理预留），请求绝对超时30秒，最多一次模型加载、无修复或重试。A基础设施异常立即中止，不启动B；A通信成功但规划不合法可保存原因后发B，仅在剩余资源预检通过时派发。

PUBLIC_INPUT.json复制独立标签包诊断输入，不使用四道正式A/B任务。该诊断输入已有过离线序列化与上一轮零HTTP中止接触，不能作为全新独立任务泛化样本。没有Gold文件、没有最终评分。

PROTOCOL.json保存本轮源码、Schema/Prompt、请求参数、输入hash及资源建议，状态PREPARED_NOT_AUTHORIZED。新增入口复用原MeteredExecutor和Budget，各组独立文件目录；源码/输入变更触发冻结失败。原run.py和run01结果未修改；新真实产物只写run02/execution。

## 真实目标与停止边界

未来每组报告实际HTTP状态、finish_reason、JSON完整、完整Schema是否通过、Graph是否合法及完整错误反馈；服务端并不回传Schema，所以记录请求服务Schema/本地完整Schema hash与响应原始字节hash，不虚构“响应Schema”。

HTTP400/网络异常/provider结构异常属于通信或服务错误；完整Schema拒绝属于响应协议错误；compile/assemble拒绝属于语义生产者或合同结构错误。结构合法也不证明任务语义正确，且本次禁止额外LLM语义审查、DAG节点执行和评分。

默认准备命令（已零调用执行）：

```bash
/root/autodl-tmp/r3_venv/bin/python -m collab_scheduler_v1.typed_dag_v1.http_schema_diagnostic_v1.run02_entry
```

仅取得新的明确两请求授权后才可使用同命令加--execute。此文档命令和“建议预算”不构成授权。没有启动96请求正式A/B，不借历史额度，不把未知2496Token释放。

本轮未修改冻结实验、48配置或评分协议，未提交或推送Git。准备完成后停止，等待真实调用授权。
