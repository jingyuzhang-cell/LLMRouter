# 可直接交给另一窗口：CPU 零调用搜索机制审查

请只审查，不修改搜索器、评估器、协议和现有结果，不启动模型/GPU，不跑真实实验。允许 CPU Stub 测试，临时产物放 /tmp。输出一个独立 Markdown 审查报告，放 r3_own_pool/collab_scheduler_v1/joint_search_v1/review/ 下，避免与主窗口文件冲突。

唯一任务：判断六组真实搜索方法是否具备可归因的实现与信息边界。

1. 查阅 sa_pgfs_v1/ 的 acquisition.py、surrogate.py、external_baselines.py、replay_v2.py、ablation_mechanisms.py，以及 joint_search_smoke/unified_space.py / closed_loop_test.py。
2. 核实 Proposed 与去状态、去增量成本之间是否仅改变对应因素；状态特征是否来源于搜索时可见信息；增量成本预测是否偷看真实未执行费用。
3. qNEHVI 是否确实调用对应算法，或只是边际高斯/EHVI 近似。只依据本地代码/安装包，不因名称作认定。
4. 检查选点是否真的使用拟合后的模型/采集函数；修改观测后是否影响选点（CPU 定向测试）。预先生成全表然后随机选点不能证明在线 GP 更新。
5. 检查配置实际唯一性、每个节点模型分配是否真正可达；新主窗口的 joint_search_v1/evaluator.py 是48配置接口，其他文件可能仍有旧空间。

交付：每个发现给出文件/函数/证据、是否阻断正式比较、最小修复建议。不要提供合成数据性能排名，不把多个搜索种子当独立任务，不重新执行已完成的真实 Smoke。

与主窗口互不写同一文件；本项不占GPU，适合同时进行。不要自行修改正式资源上限或授权实验。
