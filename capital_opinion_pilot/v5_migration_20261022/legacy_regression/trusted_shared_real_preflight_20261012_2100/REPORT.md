# Qwen可信共享真实服务预检

北京时间2026-10-12 21:00窗口内启动一次，完整控制器墙钟43.44秒，低于300秒。0生成请求、0推理Token，没有t2/DAG/评分。此前窗口授权和协调确认保留在AUTHORIZATION.json。

模型完整权重/配置/TokenizerSHA复核通过；真实启动日志确认vLLM0.11.0、Qwen2ForCausalLM、本地Qwen2.5-7B-Instruct与同目录Tokenizer、context16384、localhost8127及GPU利用率参数0.85。/health与/v1/models HTTP200，返回served_model和root权重路径符合冻结配置。健康/模型身份成功不证明推理Token计量一致。

原结果FAILED_OR_QUARANTINED：服务组SIGKILL后leader退出，立即核验时worker164587还在自有session，GPU占用21586MiB，清理守卫拒绝确认。保留原RuntimeError和GPU证据，不把延迟退出改写为首次清理PASS。其后只读核查worker/leader已不存在，GPU计算进程空、显存0MiB。POST_CLEANUP_READONLY.json是后续状态，不替代原核验时序。

manager退出后flock被OS释放，但RESOURCE_QUARANTINED持久标记继续阻断后续本项目启动，本轮不清除。最小后续离线修复是停止后的自有worker/GPU核验在剩余清理窗口内有界等待，而非单次立即采样；不得再加载模型来验证或自动重试。本轮未新增Mock测试。

服务日志及身份/启动参数/单调时间线/清理错误/后续GPU状态/运行wrapper完整保存。服务metadata健康检查为GET，无任何/v1/completions或chat生成请求。自有资源事后已释放，隔离标记仍保留，当前HOLD。没有证明硬实时GPU释放、推理输入计量、t2事实覆盖或完整执行成功。原A图、历史4096/4000、评分不改，无Git提交推送。
