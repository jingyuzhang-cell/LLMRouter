# SERVICE PREFLIGHT最终离线审计

NO-GO（冻结配置齐备，但真实执行入口尚未完整）。未启动模型、HTTP或t2，0模型请求。

重大缺口已修复：此前只在cleanup失败后写隔离标记，管理进程直接崩溃仍有漏保护窗口；现在fsync活动/中断标记先于Popen，成功核验后才删除。Mock模拟flock因进程退出释放后，新manager仍由持久标记拒绝。锁表示当前互斥，标记表示未确认安全的持久状态，两者不可互代。

75项相关零调用测试通过。仅本实例Popen新session可被killpg。进程session与nvidia-smi核验失败保持隔离。不是全仓库统一防绕过：kdx_local_single/KDXNodeAdapter及旧入口均为底层模块，不检查隔离标记；禁止作为预检入口使用。没有自动CLI加载代码，未授权导入不会发起HTTP。package validator只接受GET /health及/v1/models，生成接口禁止。

协议预算0模型请求/0推理Token/300秒；240加载准入+10清理+50余量。300应从首次启动动作计时，290前必须触发cleanup；现OwnedService若直接设wall_seconds=300会把清理时间额外加在其后，故不能把默认调用当作本协议已接通。尚需有界metadata poll/身份记录/部署版本核验与290秒清理触发的统一预检编排。此为真正硬门禁，而非模型质量失败。

冻结文件包括模型完整分片/Tokenizer离线核验快照（历史生成、真实启动前仍需重核）、vLLM0.11源码/拟用命令、启动参数、禁止生成的协议、时间线日志格式、隔离实现和测试。真实服务健康/身份/计量/GPU释放未验证；无推理预检不能证明真实prompt usage，后者需独立推理授权。

若cleanup超时或driver资源无法确认，记录RESOURCE_QUARANTINED、保留锁/持久标记并禁止后续启动。只看session无成员与leader不在compute PID列表不足以证明设备物理资源全部释放；真实验证应增加owned GPU PID追踪与基线对照。当前不消除标记、不终止其他会话。不修改A图/历史4096证据/评分、不提交推送。
