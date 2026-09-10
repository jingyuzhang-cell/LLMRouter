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
