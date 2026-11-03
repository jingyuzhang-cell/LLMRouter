# TRUSTED_SHARED_PREFLIGHT协议冻结

TRUSTED_SHARED_PREFLIGHT READY（仅协议设计/离线门禁与冻结就绪）；REAL START NOT AUTHORIZED。尚未确认独占窗口/其他操作者同意，没有声称当下运行准入通过。强制隔离原协议及NO-GO完整保留。

边界：同权限进程仍可直接访问GPU；flock仅协作互斥，不是设备权限隔离；watchdog不能保证driver异常下按时释放GPU；仅协调后有限开发预检，不能用于声称强制隔离的正式实验。

范围：Qwen2.5-7B加载、vLLM0.11/Tokenizer文件与实际command身份、localhost GET /health及/v1/models、自有进程停止、GPU/session核验、成功后删marker释放lock。0生成请求/0推理Token/300秒计划上限含加载清理。不运行t2、完整DAG或搜索，health PASS不证明计量一致。

启动门禁：独占窗口覆盖完整300秒、相关操作者同意并有协调记录、GPU无占用且协作锁可获取、无未解除quarantine、同协议ID无历史或当前实例、冻结SHA一致。start_admission为独立离线函数，不启动或发HTTP。协调模板默认为未同意；不会把空模板当实际确认。锁可用检查存在TOCTOU，实际启动必须再次原子flock。

失败时只终止本实例owned session，保存原始/清理错误与完整时间线；未知GPU退出保持RESOURCE_QUARANTINED及阻断后续本项目启动。不删除锁、不自动清除marker、不终止其他实验。

旧强制入口仍拒绝isolation_enforced=false：本轮不把它偷偷放宽或把此协议伪装为强隔离。后续真实授权需接入独立可信共享模式，使用该模式的协调门禁和既有生命周期，不绕过旧协议。本轮只获设计/离线冻结授权，故未写可自动运行新模式的CLI。协议READY不等于已有可直接调用的真实启动器。

93项相关零调用测试通过，新增7项覆盖协调/窗口/占用/marker/重复与锁。现有生命周期测试保留；无真实GPU验证。源文件/配置/资源/输入V3历史身份哈希随包冻结。不修改A图和历史4096证据，不提交推送。
