# 真实A/B受限运行：服务Schema准入失败，按协议停止

用户“继续跑，直到跑通”后，在上一轮冻结独立A/B资源包中启动，没有追加预算。A先运行；三模型真实加载和身份/Tokenizer检查全部通过，Stage B资源准入通过。A第一题第一次规划派发后HTTP400，原服务响应为：`The provided JSON schema contains features not supported by xgrammar.`。这是服务Schema准入错误，不是模型生成了非法图；尚无候选响应。入口无HTTP重试，退出码2，未启动B。

## 计量与状态

- 真实请求尝试：1（A慈善净款首次规划）。B未启动。
- 已知响应Token：0；实际总Token未知，不能报告“零消费”。失败预留2496 Token保留在pending，charged_tokens=2496。DISPATCH只有reserved，没有response；预留未清零。
- A墙钟236.297607645秒；总编排墙钟237.710037056秒。
- A加载时间累计176.301960412秒（三模型Stage A + 切回medium）。GET健康检查没有推理请求。
- 无真实生成候选、无图准入、无节点执行、无评分。不计算首次/修复结构合法率或答案正确率；均NOT_EVALUATED。不能将HTTP400计为有效模型候选合法率0/1。
- 服务已停止；nvidia-smi无计算进程、显存0 MiB。结束后275/275零调用测试通过，冻结输入和源码哈希再次核验通过。未修改冻结协议、Schema或数据，未提交/推送Git。

## 具体根因：本地编译通过不等于vLLM HTTP准入通过

真实使用的vLLM `v1/structured_output/backend_xgrammar.py:206` 的 `has_xgrammar_unsupported_json_features` 对array的uniqueItems关键字直接拒绝（约219行）；validate在约291行调用此检查并抛出本次一致错误。A的producer_schema包含uniqueItems（重复依赖拒绝要求）。

零调用定位分两步：

1. 已安装xgrammar.Grammar.from_json_schema对冻结A/B均能编译，所以不能单凭语法编译验证HTTP兼容。
2. 读取实际vLLM源码，仅提取并执行上述纯函数AST：冻结A被拒绝，冻结B不被该特性检查拒绝；对诊断副本仅移除uniqueItems后A不再被拒绝。没有向真实服务发送诊断副本，原Schema未改。

完整证据SCHEMA_COMPATIBILITY_DIAGNOSTIC.json包含实际后端路径和SHA；A/HTTP_INPUTS.jsonl保留原请求，A/GENERATION_EVENTS.jsonl保留HTTP错误，A/DISPATCH.jsonl及PHASE_BUDGET.jsonl保留预留。

## 后续处理边界

需要下一次零调用修复将“模型约束输出Schema”与“程序完整校验要求”分开：仅采用实际服务支持的输出Schema特性，重复producer/ref仍由原严格程序校验拒绝。不可静默切换JSON模式或在当前冻结包中删uniqueItems后继续派发；这会改变已冻结Prompt/Schema/hash。服务兼容测试必须调用实际vLLM检查，而非只调用xgrammar编译。

应先修复、重跑零调用、版本化新A/B包并重新冻结，再明确下一次真实调用授权。本轮保留失败尝试和未知用量，不无限重试，不为了完成实验绕过服务检查。原4题在本轮已冻结，第一题产生过失败HTTP输入，其后重测不能描述为首次零暴露任务。
