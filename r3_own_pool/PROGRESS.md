=== R3 5000x4 collection status  (15:40:51) ===
large (local):      4993/4999  [0.0/min]
medium (local):      4981/4999  [0.0/min]
small (local):      4948/4999  [0.0/min]
reasoning (R1 API): 4082/4999  [0.0/min]  ETA -
local driver: full driver done Wed Sep  9 12:56:56 CST 2026
gpu: 0 MiB, 0 %
pipeline: [18:59:33] pipeline watcher started
local line ETA: ~0h01m for all 3 slots

next after reasoning completes: v2 scoring/freeze/fit path (router_v2; legacy auto-pipeline retired)


## 2026-09-10 数据污染审计与修复

发现旧train矩阵633个服务故障零分（其中175个在客观任务）、tie-aware使用当前请求实际成本、repeat panel缺失标准答案绑定，以及真实750题test已开封。已修复训练标签门禁、折内成本决策与repeat评分协议，生成新的客观训练快照、相似题分组、97题repeat panel，完成Ridge同折/分组/排除pilot对照与3-seed MA排序消融。29项相关测试通过。原test全部作为开发历史，不再认证独立；没有在此次审计汇总validation/test质量。详细结果及后续输入见router_v2/contamination_audit_20260910b/REPORT.md与REMEDIATION.json。


2026-09-10 错误切换定位与锚定MA：在修复标签的相似题分组OOF上，完成3-seed嵌套选参，MA从旧固定60轮平均81.759%提升至87.014%，但仍未超过DatasetBest 87.126%，RidgeGuard消融为87.160%。新增3项隔离/决策测试通过。详细结果见router_v2/anchored_ma_clean_20260910/REPORT.md；不宣称MA独立增益或正式测试闭环。


## 本轮最新执行核查（2026-09-10）

权威状态：router_v2/execution_review_20260910/REPORT.md 与 STATUS.json。重新导出三分区clean矩阵并纳入全部750题test开封证据；仍缺650个开放题标签。修复历史clean train输入缺失后重跑分组基线，复现Ridge 87.193%、DatasetBest 87.126%。新折内面板113题，large已完成565/565（复用110、新采455），reasoning 0/565，因此stable pairs仍为0，不是实验通过。原winner和原pair三seed对照已完成，stable标签训练尚未执行。多目标为代理指标探索，尚无正式Pareto确认。本轮19项相关测试通过。DashScope数据外发被自动审批拒绝；待确认具体范围见同目录EXTERNAL_SCOPE.json。


实验A统计口径已冻结：router_v2/experiment_A_gap_20260910/REPORT.md；净Gap Recovery相对DatasetBest，分组配对bootstrap同步重算分子/分母，三seed均报告。新增4项统计测试通过，MA架构未改。reasoning补采本轮再次被自动审批拒绝，仍需明确DashScope目的地授权；未新增任何外部调用。


## 2026-09-10 晚间：DashScope外部执行（用户明示授权后）

用户对 EXTERNAL_SCOPE.json 范围给出明确授权后执行：arenahard 欠费窗口损失修复 + qwen-max 开放题补评 + reasoning 折内重复补采。

- 生成修复：9/10 ok（arenahard_0409 两次生成都 finish=stop 且正文为空，按2次上限保持显式缺失）；审计见 router_v2/generation_repair_20260910/REPAIR.json。
- qwen-max 补评：train 458 + validation 95 + test 96 = 649 次新调用，三分区 LABEL_COVERAGE_COMPLETE（2100/2100、448/448、452/452 终态）；inconsistent_components 749/141/154 按协议仅标记。
- clean matrix 重导出 data/clean_splits_verified_20260910c：19999/20000 单元有标签，REPAIR_QUEUE 仅剩 arenahard_0409。
- reasoning 重复采集：网络中断一次后断点续采，562/565；剩余3条均为 mbpp_0474（思考链7k-15k token，600s客户端超时，21试2成，成功样例最慢596s）。已挂自动重试循环（每轮6次新尝试，上限12轮），期间不得修改 run_repeat_stability.py（scorer_sha256 会作废全部记录）。
- 齐后依次执行 aggregate → train_repeat_pair_ma --mode stable → report_gap_recovery --stable（新目录 experiment_A_gap_20260910b）。


### 实验A闭环（18:2x）

reasoning 重复采集 565/565 完成（mbpp_0474 思考链超长，自动重试循环第3轮补齐）。stable 聚合：113/113，稳定对仅 8/113（reasoning>large 5、large>reasoning 3，平均平局率 73.7%）。MA(stable) 与 matched 对照在全部 fold×seed 触发预注册 fallback（每折监督 6-7 对、单方向 <5），实际未训练，等值 DatasetBest。最终 router_v2/experiment_A_gap_20260910b/REPORT.md：MA(raw) 87.317%（Recovery 3.33%，区间 [-3.73%, 9.73%] 仍覆盖 0）；MA(stable) 0%（fallback 所致，非标签失败结论）；MA(repeat mean) -0.20%。结论维持：无方法显著超过 DatasetBest；稳定监督在 temp .7 下过于稀疏是当前瓶颈。


20%–30%目标审查：router_v2/gap_capacity_20260910/REPORT.md。目标需净救回34–51题；pair经验上界120题。硬stable只有8对且此前所有stable MA均fallback。新增三seed软pair回放与学科特征对照均未达到目标，最佳该软实验平均Recovery 3.33%，区间覆盖0。下一优先级为折内MMLU针对性监督与题干/选项表示验证，不保证20%–30%，本轮无新增API调用。


Expected Utility Difference新阶段：400题MMLU折内面板已冻结，见router_v2/mmlu_utility_panel_400/README.md。每模型复用135条，本地large新增1865条运行中；reasoning新增1865次因扩大到400题超出此前113题授权，被自动审批拒绝。均值/方差/资源差标签和回归入口已实现，6项测试通过，标签不足时禁止训练。当前还没有该新实验的效果结果。


## 2026-09-10：按用户优先级先做400题可学习性分析

P0采集中，当前记录快照：{"large": 1406, "reasoning": 135}。large本地进程仍在运行；reasoning新增1865次外发等待扩展范围授权，未重试被拒请求。新增mmlu_learnability.py：完整pair/资源/来源检查，ΔQ分布与后验区间、重复一致性、随机/任务/学科/GTE Ridge及学科内置换对照；4项测试通过。MA入口加入P1结果与来源门禁，本轮未训练。README已替换旧的直接训练顺序。


## 400题扩展授权已收到
用户回复“是”，确认剩余1865次DashScope/R1生成及费用。reasoning采集已启动并收到首批结果；准备后台自动完成分布检查和P1分析，MA不自动训练。

P1按最新要求补充非零ΔQ辅助AUC、20组全局Shuffle和20组学科内Shuffle的完整回归/排序指标，所有tie继续参与回归。修正学科遍历为排序以使置换跨进程可复现。6项单测通过；尚无真实P1结果。


### 20:12 采集提速修订（用户授权）

mmlu_utility_repeats_400 reasoning 线并发 8→24：纯吞吐参数，温度/模型/重复数/传输预算均未动；协议文件同步更新并留 data/mmlu_utility_repeats_400/PROTOCOL_AMENDMENT.json 审计。停止/重启经尾部完整性校验（389 行无损，续采 1611 目标）。效果 2.6→4.9-7.5/min（DashScope 软流控下单流变慢，收益次线性），错误 0。新增 router_v2/watch_utility_panel.py 实时视图（终端 --interval / 网页 --http 8899，只读）。


## 400题进度与污染复核
见 router_v2/panel_audit_20260911/REPORT.md。有效large2000、reasoning1441，完整283pair；41条reasoning失败保留null，涉及14题，普通重启不会修复已耗尽位置。冻结哈希、原train来源和三折ID/已知近重复组隔离通过。并发变更影响延迟可比性；原test仍属已暴露历史。P1尚未启动。


## 执行失败修复准备与诊断
用户要求直接执行下一步。43条当前失败（19超时、24 HTTP400），已冻结独立修复批次，每位置最多新增一次，含已发送的单次诊断。诊断仍等待响应；修复守护进程先等诊断成功，再等原采集锁，遇新失败停止。原始日志不修改；齐全后在独立合并目录执行P1，不训练MA。见data/mmlu_utility_repair_20260911/README.md。


## 低并发恢复已安排
12并发原采集连续3次失败，已自然熔断退出，无强杀在途请求。独立修复持有API锁串行运行。新增resume_mmlu_low_concurrency等待修复结束再以2并发补未落盘位置；保留原43位置修复预算，不再重试它们；冻结后的新增失败位置最多补1次，普通未落盘位置沿用最多2次。所有请求先记预算，再发送。若修复再次服务失败则续采也停，不反复自动重启。完整后输出独立recovered矩阵并运行P1，不启动MA。状态data/mmlu_utility_resume_20260911/STATUS.json。


## 2026-09-11 恢复批次B
检查确认原修复与续采均已停止，看板进程也不在。用户要求未完成就继续，已启动独立恢复B：冻结558个当前缺失位置，每处最多新增1次，2并发，读取超时1200秒，保留原始/修复日志及独立预算。新进程已发出前2次请求；连续3失败停止；400pair齐全后自动合并来源验证及P1，不训练MA。看板8900已恢复并纳入B记录。


## 400题采集与P1完成
两侧2000条，400完整pair。完成后来源/折隔离审计通过。P1结果mmlu_learnability_400_recovered_b：Ridge1 R²0.022、Spearman0.145、AUC0.603，优于学科内20/20打乱对照，开发门禁通过；仅弱信号，未训练MA。补充分布与审计见该目录DISTRIBUTION_AUDIT_REPORT.md。


## 实验B简单MA已实跑
query GTE3584+learned model8，共享64-ReLU-1-sigmoid，连续质量MSE；固定50epochs，三折三seed，无外折调参。400题repeat面板RidgeDelta恢复14.29%，MA平均0.37%；2975题历史迁移Ridge6.47%，MA0%。MA基本固定选reasoning，未证明优于DatasetBest或Ridge。输入来源、预测argmax、折隔离和质量指标复算通过。见router_v2/experiment_B_simple_quality_ma/REPORT.md。


## 实验C：固定ΔQ损失对照完成
模型、50epochs、三折三seed与B相同，仅loss改为quality MSE+1×delta MSE。面板MA平均Gap Recovery8.97%，历史2975题迁移1.57%，均低于Ridge的14.29%/6.47%，恢复区间均覆盖0。未挑最佳seed或继续外折搜索权重。输入哈希、B/C相同折名单、argmax验证与配对差异已保存PAIRED_VALIDATION.json。


## Experiment D完成
B/C检查既有checkpoint训练及折外ΔQ拟合；C训练R²0.743、折外−0.067，过拟合。直接pairwise回归及固定0.1ranking各三折三seed完成，未超过Ridge。全结果与拟合诊断见experiment_D_fit_diagnosis/REPORT.md。


## Residual uncertainty gating完成
固定100次group bootstrap残差头、2.5/97.5分位门禁，3seeds全部回退Ridge，面板14.29%、历史6.47%。未门禁残差面板15.20%、历史6.86%。错误切换为0同时正确切换为0，Switch Accuracy未定义而非100%。E2交叉拟合Ridge误差纠正已包含在Residual中。见experiment_F_residual_gating/SWITCH_REPORT.md。


## GLM 120题筛查完成
采集120/120；修复分析器对旧quality.final与新标量quality的格式兼容，失败标签仍拒绝。三组预定分析完成且来源与指标复算通过。GLM43/120、独有正确1题；三/四模型Ridge均未选GLM。旧双模型Ridge101/120、拟议三模型99/120、四模型100/120。保留7条截断，不追加生成；下一优先级为部署/代码输出适配诊断，再决定是否扩展重复。详见router_v2/pool4_pilot_results/SCREENING_REPORT.md。


## GLM评测提取修复与120题离线重评分
用户要求不扩大实验，仅重评分GLM。保留原文与Qwen/R1标签，新增rescore_glm_pilot.py及逐条审计，提取规则测试、隔离执行运行时检查、原始哈希与折/指标复算通过。GLM43→53/120。结果见router_v2/pool4_rescore_results_v1/RESCORE_REPORT.md；模型本体能力判断仍受部署异常未排除的限制。


## Coder下一阶段启动
用户指定Qwen2.5-Coder-7B→同120题pilot→accuracy/unique wins/winner distribution/oracle gap→模型池→400题utility→MA。使用官方Qwen2.5-Coder-7B-Instruct固定revision c03e6d358207e414f1eca0bb1891e29f1db0e242，下载进程与自动pilot流程已启动。保留所有原始生成，沿用修正提取与官方测试。400题混合面板草案仅按ID/任务类型预选，未发起生成，等待面板选择及pilot结果决定模型池。


## Coder120题完成与模型池决策
120/120，来源哈希和路由指标独立复算通过。Coder82/120，代码30/40，全五模型独有正确1题；四模型增加Coder时Oracle106→107/120，Ridge100/120不变。按用户此前独有正确>10%的筛选标准，不将Coder/GLM推进扩大utility；保留历史三模型作为参考池，不能宣称学得路由优越。400/MA尚未启动，当前候选未通过进入条件。详见coder_pilot_results/VALIDATION_AND_DECISION.json。


## Baseline归档与单模型替换结论
按用户最新指示保留全部旧结果，归档router_v2/model_pool_baseline_20260911，清单哈希复核通过。GLM→Coder单替换pilot已完成，无需重跑；四模型gap均4.17pp、Ridge均83.33%、候选unique均1/120。满足情况B，暂停400/repeat/MA，下一方向为benchmark覆盖与更大能力差异审查。


## 路由可行性诊断完成
现四模型分任务折外Oracle−DatasetBest：代码2.5pp、数学0、知识10pp（4/40）。知识独有赢家6/40、归一化严格赢家熵0.959，代码严格赢家全部R1；总体低gap掩盖知识子集空间。下一优先级知识/MMLU-Pro，更大样本验证后再决定MA，不整体更换benchmark。详见router_v2/pool_routability_diagnosis/REPORT.md。
