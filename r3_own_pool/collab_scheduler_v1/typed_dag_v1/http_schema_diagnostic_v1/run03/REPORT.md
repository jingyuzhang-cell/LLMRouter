# run03零调用准备

状态PREPARED_NOT_AUTHORIZED。使用此前暴露的标签诊断输入，定位为Prompt修复诊断，不作为独立任务或正式四题结果。

A输入1759Token，最大输出768，单请求预留2527；B输入1679Token，最大输出768，预留2447；总预留4974。建议独立上限仍为2请求/10000Token/20分钟，两臂各1请求/5000Token，无修复或HTTP重试，不执行节点或评分。

实际medium Tokenizer本地计量；实际vLLM请求DTO和xgrammar编译两组通过。未加载权重或发送HTTP。源码、Prompt、Schema、输入、历史证据哈希冻结。run03独立预检不沿用旧四题源码绑定；默认入口仅校验哈希。历史run02及HTTP400不修改。

入口：python -m collab_scheduler_v1.typed_dag_v1.http_schema_diagnostic_v1.run03_entry；--execute仅在新明确授权后使用。本次不执行。Prompt修复后已有293项测试通过，未宣称真实合法率提升。
