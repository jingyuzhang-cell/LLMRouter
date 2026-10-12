# run04资源准入失败

启动前297/297测试通过，冻结哈希一致。执行入口在local_gpu.lock的非阻塞独占锁获取处抛出BlockingIOError，尚未到达模型核验、Budget创建或dispatch。控制流证据是LAUNCH_ERROR.log，非通过账本缺失推断零消耗。

本次0 HTTP请求尝试、0模型请求、0Token；A/B均未发送，HTTP/JSON/Schema/DAG真实结果为NOT_RUN。未启动己方服务，无己方GPU资源待释放。其他进程67567持锁，服务67688、GPU引擎67829正在运行，不属于本轮，不终止或清理。未重试。

历史文件哈希一致，未覆盖原证据或修改冻结源码，无提交推送。execution目录保留失败证据，原入口exist_ok=False禁止直接重复使用。后续需等待资源释放后准备新的独立输出版本，不追加或抢占调用。
