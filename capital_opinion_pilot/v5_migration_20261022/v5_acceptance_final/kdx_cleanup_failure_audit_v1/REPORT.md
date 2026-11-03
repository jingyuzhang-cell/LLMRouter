# 康得新预检清理失败审计（零真实调用）

历史目录 trusted_shared_real_preflight_20261012_2100 保持不变。本轮未加载模型、发送HTTP或解除隔离。

## 时间线（北京时间2026-10-12）

|事件|时间/状态|证据|
|---|---|---|
|服务启动尝试|21:00:00.150839|SERVICE_EVENTS.jsonl START_ATTEMPT|
|自有服务PID登记|21:00:00.151764；164509|OWNED_PROCESS|
|身份/健康通过|21:00:43.225952|IDENTITY_CONFIRMED及PREFLIGHT_RESULT|
|停止信号实际派发/送达|UNKNOWN|旧代码无独立信号时间日志；代码为killpg(SIGKILL)后wait|
|主服务wait完成|21:00:43.392313|OWNED_PROCESS_STOPPED|
|worker最后仍存活|首次最终核验观察到164587；采样时间UNKNOWN|final_gpu_verification：live_session_pids=[164587]，GPU21586 MiB|
|清理失败记录|21:00:43.479657|CLEANUP_FAILED|
|完整实验结束|21:00:43.481367；43.43961秒|PREFLIGHT_RESULT time_ended/wall_seconds|
|worker实际退出、GPU释放|UNKNOWN|无连续历史采样|
|清理截止|独立墙钟记录UNKNOWN|旧代码主进程wait最多5秒，后续仅一次GPU核验；无worker轮询截止日志|
|隔离创建/保留|启动前创建；失败后保留，独立时间UNKNOWN|持久化RESOURCE_QUARANTINED及代码路径|

## 根因与证据边界

确定的实现缺陷：仅等待主进程，随后一次性检查worker/GPU，失败即隔离；主服务wait完成至清理失败仅87.345毫秒。未给worker/GPU后续确认窗口。这支持修改过早的一次性判定策略，但不证明worker属于正常退出延迟。信号是否送达worker、GPU释放延迟及worker退出原因均UNKNOWN；session成员观察不等同于信号送达证据。

历史POST_CLEANUP_READONLY.json的ps参数错误（PID未合并为逗号列表），该条记录不能证明PID退出。保留原件；本报告另存正确的当前只读快照，不反推历史退出时间。

## 最小修复

- kdx_owned_service.OwnedService.stop：在既有10秒清理窗口内等待并记录每次确认，仍仅对本实验新session发送既有SIGKILL。持锁完成退出核验；超时/核验失败保留隔离。
- kdx_cleanup_wait.wait_for_exit：0.2秒采样间隔，为每次核验保留5秒；核验超出界限拒绝成功。
- kdx_preflight_launcher.execute.locked_probe：移除重复GPU探测；原final_exit_probe已同时检查自有session和GPU。
- 新增STOP_SIGNAL_SENT（信号发送意图，非送达证明）和EXIT_CONFIRMATION_SAMPLE，保留墙钟/单调持续时间。

未增加300秒预算。预检控制器原290秒服务预算与10秒清理余量保留。该界限依赖系统调用正常返回；驱动/进程异常仍可能越界，可信共享模式不保证绝对GPU释放。核验失败继续隔离，不因后续GPU空闲自动解除。

## 测试

105/105零调用测试通过（原99项+6项）：延迟worker、永不退出、延迟GPU、多worker、清理余量不足、探测越界；原隔离持久化、启动拒绝、异常清理及锁相关测试保留。手动解除仅列审计条件，不执行或新增自动解除入口。

命令：python3 -m unittest test_kdx_cleanup_wait test_kdx_shared_launcher test_kdx_trusted_shared test_kdx_preflight_adapters test_kdx_preflight_launcher test_kdx_service_preflight test_kdx_owned_service test_kdx_local_single test_kdx_lineage_chain test_kdx_admission test_kdx_execution_adapter test_strict_meter test_merge_contract_v2

## 当前门禁及人工解除条件

当前快照未发现PID164509/164587或GPU计算进程；隔离标记仍为RESOURCE_QUARANTINED。历史FAILED_OR_QUARANTINED保持有效，无人工解除授权，下一次真实预检为HOLD。

人工解除前需：核对历史运行身份及其全部自有进程/session；重新确认GPU进程/设备状态及资源协调；保存只读核验与事故证据；操作者明确授权解除指定标记并记录解除动作。之后另行冻结修复源码与配置、确认新独占窗口及新的预检授权。不得将当前GPU空闲作为自动解除依据。

本轮不执行t2/DAG，不修改A图、历史Token账本或评分协议，不提交/推送Git。
