# 康得新t2最终离线准备

SINGLE NODE REAL EXECUTION NO-GO。未加载模型、发HTTP或执行DAG。

新输入V2冻结10片段，保留旧5片段版本；节点/依赖/合同不变。COVERAGE.json区分10项有限命题：COVERED为段落明确记载，利润2019/2020认定差异CONFLICT，全问询和禁入逐人员完整性UNKNOWN。原文定位不是全文完备证明；必要覆盖仍未全部通过。

完整整数prompt 8464 Token，输出768，预留9232；配置拟定context16384。服务源码冻结vLLM0.11.0整数prompt保留路径及usage长度统计，没有服务端chat模板添加。本地Tokenizer/chat template/特殊token身份冻结。此为已安装代码静态证据；拟启动服务真实输入token数、模型身份仍待最小验证，不宣称已真实核验。

新增OwnedService：独占锁、自有Popen新session、单请求与全局watchdog、取消失败可终止自有进程组、wait与finally关闭资源、持久日志、防重复run目录。只有本实例Popen返回的进程可被终止。Mock覆盖8项。OS调度、GPU driver和进程异常阻塞不能通过Mock证明GPU在硬截止前释放；SIGKILL不是GPU释放确认。当前不具真实GPU释放检查，不宣布READY。服务启动健康/模型身份HTTP未来应在资源授权内验证。

此前StrictMeter联合预留、unknown完整保留、fsync、重启不重发测试保留。新服务管理器与单节点传输为组合模块；尚无完成前述必要覆盖门禁的统一可运行验收入口，不允许绕过后直接执行。

全部68项相关零调用测试通过；旧回归另外运行。历史4096账本保留。阻塞收口为：必要事实覆盖UNKNOWN、部署真实身份/计数验证、GPU最终释放及整体硬截止可证明性。最小后续验证如授权应先无推理服务身份/资源检查；随后最多一个整数prompt抽取请求，预算按本V2重新冻结，不沿用5729。当前不建议执行真实t2、不申请调用。
