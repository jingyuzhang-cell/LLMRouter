# Qwen可信共享真实服务预检结果

PASS_METADATA_ONLY。北京时间2026-10-13 20:20:04.308至20:20:48.997，服务预检完整墙钟44.689秒；窗口内离线文件哈希准备在此之前完成，不计作模型加载时间。

0模型生成请求、0推理Token。仅localhost GET /health及/v1/models；未执行t2、DAG或调度搜索。

完整声明权重、配置与Tokenizer哈希通过。vLLM服务日志确认0.11.0，模型及Tokenizer路径均为/root/autodl-tmp/models/Qwen2.5-7B-Instruct，服务模型ID为Qwen/Qwen2.5-7B-Instruct，上下文16384。

服务PID4623，worker4785。清理在GPU协作锁释放之前检查自有session及GPU计算进程，confirmed=true。原始SERVICE_EVENTS记录等待采样。清理后只读复核session为空、GPU计算进程为空、协作锁无内核持有记录、无隔离标记。无初始错误及清理错误。

结束后105/105零调用回归通过。冻结Manifest SHA256：d3e4cc5f2f147620cef65aa614a0e9e8486be09a5ff76d6fd2cd1f824a081924。历史失败及超额账本未改写，未提交Git。

这是模型加载、身份、健康与清理的真实证据，不证明服务端输入Token计量一致、t2事实抽取正确或完整DAG执行成功。可信共享协作锁不提供不可绕过的宿主级隔离；不保证驱动故障时绝对按时释放。本授权已使用一次，后续业务抽取需独立授权。
