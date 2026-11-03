# 本地Qwen单节点准备

NO-GO / SINGLE NODE REAL EXECUTION NOT READY。0真实请求、0模型加载。

复用Qwen2.5-7B-Instruct；重新读取并校验全部4个权重分片及既有快照声明配置/Tokenizer文件完整SHA。Tokenizer离线加载Qwen2TokenizerFast，transformers4.57.1。身份见MODEL_IDENTITY.json；不把历史服务版本当成本轮实际服务版本。

选择原A图t2抽取节点，结构、依赖、合同不变。冻结输入含独立人工元数据index及五文档检索片段；人工index仅单节点fixture，不冒充t1执行。五片段不足以证明完整抽取目标覆盖，不能为通过门禁缩减原节点任务。所有片段位置/日期/哈希保留。

kdx_local_single.attach_local_transport必须StrictMeter，仅localhost、指定本地alias；完整system/user经同一Tokenizer chat template渲染，发送整数prompt IDs到/v1/completions，避免服务端chat包装差异。输入测量4961Token，最大输出768，预留5729Token。模型字段验证、context cap、原strict fsync预留/unknown/去重路径复用。当前独立adapter可用，但没有CLI真实启动器，禁止直接切换旧远程alias。

预算证明仅在整数prompt服务按冻结配置执行的前提下成立：服务端实际参数、Tokenizer/权重身份和prompt_tokens一致性尚须授权后检查。输出超界原StrictMeter记录并锁止，但不能撤销消耗。没有以估计值充当真实硬边界。

生命周期复用此前Mock锁/取消/清理门禁，没有新增实际启动/硬终止实现。加载180秒、请求60秒、清理30秒合计270秒仅建议可执行deadline草案，不是本轮实测加载耗时或已证明的释放界限；不能据此READY。

剩余：t2必要事实覆盖内容审定；冻结服务二进制/启动参数及整数prompt完整计量语义；自有进程组硬截止与GPU清理实现。未启动模型、HTTP或整个DAG，未修改A图、历史超额或评分，未提交推送。暂不申请真实预算；上述条件离线通过后才能提交1请求/5729Token及经证明墙钟的新独立信封。

60项相关零调用测试通过（新增本地传输3项）。日志见TESTS.log。
