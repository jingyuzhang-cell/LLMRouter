# 可信共享启动接线

REAL SERVICE PREFLIGHT HOLD。新入口kdx_preflight_launcher.Preflight.execute(authorized=...,coordination=...,history_records=...)支持独立TRUSTED_SHARED_PREFLIGHT；原强制模式START_ISOLATION_NOT_ENFORCED拒绝保持不变。授权不从本轮推断，缺协调记录就拒绝，模板不算同意。

复用冻结SHA、GPU协作flock、启动前持久活动/中断marker、原子run目录、自有新session、健康/models白名单、280提前watchdog、持锁最终退出核验、日志与failed quarantine。共享模式先检查窗口/所有操作者同意/lock可用确认/历史记录，再在启动前GPU基线重验；真正lock仍由OwnedService原子获取，非模板替代。

当前独占窗口和操作者同意均未确认，GPU及锁状态没有实际探测，不宣称可直接启动。真实版本/模型文件身份仍须加载前重新核验冻结配置；served alias/health不证明完整权重与计量。300秒计划而非driver绝对截止。基于当前代码，timeout后同权限其他进程仍可绕过，不称强制隔离。

99项零调用测试通过（本轮6项共享模式接线测试，原93项保留）；health超时、cleanup错误、缺窗口/同意/quarantine拒绝和共享正常流程用Mock。原锁占用/GPU残留/重复run/墙钟测试复用，不计真实GPU成功。历史派发防重依赖完整history_records，空列表不能被当作全局不存在证明；实际授权前需从保存目录核查。

新冻结不替换旧protocol；本轮未修改其预算/任务范围。0生成请求、0推理Token、300秒计划含清理，不执行t2/完整DAG/恢复/搜索。原A图、历史4096及评分未改，无Git提交推送。停止等待独立真实加载授权与协调证据。
