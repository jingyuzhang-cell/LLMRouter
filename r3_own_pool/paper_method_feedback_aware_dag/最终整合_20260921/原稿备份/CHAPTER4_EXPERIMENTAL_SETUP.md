# 4 Experimental Setup

主要数据来自 MultiHiertt。节点路由开发面板包含 201 个任务、372 个节点；独立确认从有标签 train split 中审计未参与当前开发的任务，按固定规则选取 100 个任务（193 extraction、100 reasoning、200 verification 主节点，4 个 transformation 仅作探索记录）。官方 test split 缺少答案与程序标注，未用作有监督确认集。审计排除已知任务标识与标准化重复问题；结论限定于已检查的工作区使用记录，不涉及预训练数据。

模型池固定为 medium（Qwen2.5-7B-Instruct）、large（14B-Instruct-GPTQ-Int8）与 coder（Qwen2.5-Coder-7B）；R1（DeepSeek-R1-distill）仅作 shadow 诊断，不进入路由候选。问题表示来自冻结 GTE-Qwen2-7B-instruct；节点特征为问题编码、类型 one-hot 与问题长度对数，各模型分别训练 Ridge 质量头（正则 1）。成本与延迟先验取开发数据均值。确认前封存全部参数；确认数据只用于推断与评价。

基础采集温度 0、输出上限 512 tokens、并发 4、无自动重试；确认集每模型 404 次请求、共 1212 次。Live 综合评价（5.7）在 50 个确认任务上真实执行三臂策略并另采单模型基线，全部调用按缓存去重计费。配对统计以任务为聚类单位 bootstrap（10,000 次重采样，种子 20260915）。

本章为第 5 章各实验的统一设置声明；各实验的专用设置（如 Live 三臂的调用缓存与预算口径）在对应小节中另行说明。
