# 统一SERVICE PREFLIGHT接线

NO-GO。统一预检控制器已开发，80项零调用测试通过；未启动GPU模型、HTTP或t2。

调用链：Preflight.execute授权布尔门禁→validate_package完整文件SHA/0生成协议→baseline GPU hook→OwnedService.start非阻塞独占锁/持久隔离/Popen新session→独立watchdog→GET白名单health/models→identity→finally自有进程组终止/退出核验→最终GPU hook/结果持久化。不导入旧启动器、StrictMeter或生成transport。无CLI自动执行路径；调用者必须明确提供有界metadata/GPU适配器，当前没有default真实适配。

正常加载检查最多240秒；控制器watchdog约280秒触发停止，OwnedService备份约290秒触发；预留10秒cleanup，最终GPU hook5秒。记录manager PID、service/group PID、启动命令、models响应、GPU基线/后测、UTC时间与单调墙钟、原始/清理错误。假设所有hook实际遵守timeout才可保证300秒；Python Timer/OS调度和driver stall没有可证明绝对上界。GPU最终确认仍是hook数据，不是物理资源证明。异常保留隔离标记，下一实例拒绝。

明确未完成：最终GPU复核位于OwnedService释放锁之后，可能有并发检查窗口；需将全部最终核验移入持锁清理临界区。现有session扫描不能完整追踪脱离session的worker。没有bounded metadata/GPU真实适配，因此不能将Mock成功等于真实预检入口可运行。

绕过审计：collect/runner.py直接Popen，typed_dag_v1多个real_generation入口调用engine.start_model；本目录kdx_local_single及底层节点adapter不检查隔离。统一控制器结构/白名单阻止它自己调用这些路径，但同账号仍可另起进程绕过锁。没有修改其他会话代码、用户权限或建立受限执行容器，故无法证明其他入口不会绕过隔离，依用户明确门槛保留NO-GO。authorization布尔仅防意外调用，不是恶意绕过安全边界。

冻结0模型请求/0推理Token/300秒。后续最小动作：持锁最终GPU核验、有界真实metadata/GPU适配、独立受限服务执行域/统一GPU启动权限约束。不能仅写不要使用旧入口代替这些约束。未修改A图、历史账本、评分，不提交推送。
