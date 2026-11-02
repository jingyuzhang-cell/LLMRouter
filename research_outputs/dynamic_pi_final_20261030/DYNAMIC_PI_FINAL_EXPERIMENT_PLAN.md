# Dynamic-Pi 最小真实收益实验最终批次方案

**最终裁决：HOLD。日期：2026-10-30（北京时间）。允许真实请求：0。**

这是一次性准入结论和不可执行的机读设计，不是“全部冻结并可运行”的批次。未满足项保留空值，不伪造 Gold、模型画像、现金认证或运行命令。不自动衍生准备项目。

## 十项任务的最终状态

| 项目 | 核定结果 |
|---|---|
| 合格新任务 | 未取得。国恩—中氟能为新筛选候选；两份官方 PDF 与24项原包清单哈希一致，但独立性未签认，事件早于前瞻协议。不能称未来事件确认集。 |
| 六项独立裁决 | F1—F6 全部 PENDING；reviewer及decision均为空。机器候选参考不升级。 |
| 模型与版本 | 拟定北京 qwen-plus-2025-12-01 与 DeepSeek直连 deepseek-flash（文档映射V4.1-Flash-1017）；未认证账户可用性、别名不可变性。实际绑定池仍为空。 |
| 节点真实画像 | 不满足。旧画像是purchase/payables或单一14B capital.*，没有当前terms/observed/reconcile的匹配双模型数据。校准两项任务未选定。 |
| 两臂策略 | 比较语义已固定；部署实现绑定未完成，不冒称DD-V5.1认证版本。 |
| 同状态配对 | 方案规定同一真实前缀快照、相同R/Z、反馈及剩余约束；真实快照尚不存在。 |
| 矩阵与重复 | 一事件两次前缀，Static/Dynamic各两个续执行单元；校准12、前缀及续执行最多18，总30为条件上限。 |
| Token/现金 | 公开费率可算条件包络；完整请求、实际账户及计量口径未绑定，非认证账单上限。 |
| 独立评分与统计 | Q/E/K规则与描述性分析规定；独立参考和正式评分器映射未批准，终端数值Q不填。 |
| 命令/守卫 | 无已核实可执行的整批真实命令；run_command=null。不能将离线回放命令伪装成真实实验。 |

## 任务与审阅身份

任务问题、三节点浅分叉和六项参考沿用 `/root/research_outputs/dynamic_pi_new_task_20261030_v1`，不修改。两源分别提供合同条款与已披露进展。F1主体和总价、F2分期及定金、F3加总比例、F4交割状态、F5付款条件、F6全款是否已付，均待用户或指定研究者独立裁决。出处位置存在≠语义已独立确认。准备过参考不自动等于算法调参曝光，但不因此认证任务独立；限定目录无匹配也非无曝光证明。

严格未来事件要求当前不满足；本方案不擅自放宽成确认性研究。即使后来完成裁决，一事件两次运行也只能提供局部机制探索证据。

## 模型、价格与可复算预算

公开文档查询日期2026-10-30；仅查询网页，未调用模型或账户接口。

- [Qwen官方文档](https://help.aliyun.com/zh/model-studio/qwen-plus)：北京快照qwen-plus-2025-12-01，输入≤128k、非思考，输入¥0.8/百万Token，输出¥2/百万Token。
- [DeepSeek官方文档](https://api-docs.deepseek.com/quick_start/pricing/)：deepseek-flash当前对应DeepSeek-V4.1-Flash-1017；用峰时缓存未命中输入$0.3/百万、输出$1.2/百万作条件估费。不使用折扣或缓存节省。

默认拟用非思考、无联网/工具/显式缓存收费功能。官方价格不能证明用户实际账户地域、可用版本和最终账单适用性。

每请求输入16,384、输出3,072为拟议限额，未认证真实请求Token，不能裁掉必要证据来适配。校准2任务×2模型×3节点=12，每模型6次；评测1事件×2重复×(前缀≤3+2臂×剩余≤3)=18。因此总≤30、每模型≤24；每币种极值不同时达到。

| 口径 | 数值 |
|---|---:|
| 总输入计划上限 | 491,520 Token |
| 总输出计划上限 | 92,160 Token |
| 总Token计划上限 | 583,680 Token |
| Qwen单请求条件估费 | ¥0.0192512 |
| DeepSeek单请求条件估费 | $0.0086016 |
| Qwen最多24次条件包络 | ¥0.4620288 |
| DeepSeek最多24次条件包络 | $0.2064384 |
| 拟议程序估费停止阈值（未批准） | ¥0.50／$0.22 |

这不是已核定预算或绝对现金封顶。没有把价格已知误写为计费已认证，也不恢复此前绝对现金封顶门槛。新增Planner、评分模型、额外校准、重试均不在30次内，不准隐性追加。P50/P95缺少匹配真实数据，不伪造。拟单请求180秒、批次5400秒；任务deadline拟按独立校准的初始预测makespan×1.5事前确定，具体秒数未知，不能用评测结果调整。

## 两臂与同状态配对规则

共享初始分配、DAG、Prompt、证据、节点合同、模型池和校准数据。Static保持原pi；Dynamic根据同一反馈重新比较全部未完成节点，可保持原方案。两臂同样复用健康缓存、相同必要R，Z=KEEP。模型槽各1，不混跑两臂造成资源干扰。

共同前缀在第一次自然合同失败后停止新派发，等在途响应完成再冻结状态；剩余时间/费用在两臂相同。不发明故障，不筛掉无反馈样本。若无反馈，记录无触发及共享结果，不能充作两个独立执行。续执行每个必要节点最多一次，失败不再次重规划或重试。不合法结果不得进入下游。

重复1按Static→Dynamic，重复2反序；这是事前平衡顺序，不称随机化。真实API随机性不可完全配对。日历时段差异保留。共同前缀成本实付一次；部署比较给两臂相同归属，同时报告边际成本和全成本。规划、检测、等待和失败开销均纳入；另一臂的等待不扣本臂剩余时限，整批墙钟另报。

### 不能隐藏的实现差距

`/root/.worktrees/codex-dd-v51-six-arm/dd_v51_six_arm/engine.py` 的choose目标为预测makespan、CNY、USD、模型ID字典序，不是已验证质量优化；反馈为观察时长/预测时长。固定臂的剩余可行性用空scale，动态臂用更新scale，尚不能声称同口径约束评估；不在本轮改代码。

`/root/.worktrees/planner/r3_own_pool/joint_execution_prep_20261028_v1/window2_joint_executor.py` 能消费pi_full，但输出轨迹将终端答案截为text_head；目前不能直接交独立全文评分。只读核对不是运行验收。离线entry没有HTTP真实模式。没有新增模块填补差距。

## 终端评分与分析

审阅者先独立核定事实与UNKNOWN边界，评分时屏蔽策略/模型标签，读完整答案。Q记录事实正确/错误/未知；E记录来源真实性、唯一定位、充分支持；K记录Schema。UNKNOWN不填0或1，错误附加断言也需评价。

拟主要指标为六项必要交付满足已批准Q/E/K要求且按期完成。拒绝、无交付及失败阻断属于任务未成功，但不能把其未知Q写为事实全错。参考本身未决时，独立质量结论不可出。这个聚合需参考裁决认可，当前不擅自修改既有评分器。

报告两次配对的成功差、Q/E/K向量、CNY/USD、真实墙钟、拒绝率、失败成本与动作差异；不把两次重复当两个事件，不做总体显著性、等价或0.95可靠性声称。质量相同下的成本/时延改善只叫样本观测；不同指标冲突报告权衡，不事后改变权重。失败不删分母；批次系统中断标INCOMPLETE，未启动单元单列，不冒充模型错误。自然反馈未出现或动作一致也是结果，不补采到出现正收益。

## 运行命令、预算守卫和停止规则

**真实运行命令：不存在已核实绑定的命令，故不提供虚构命令。配置execution_enabled=false、authorized_requests=0、run_command=null。** JSON可读取不代表任何旧runner能消费。

计划要求原子预留全批/模型/单元请求与双币种预算，实际usage回填，未结算保持预留。计费不明、API/传输异常、评分器系统异常或源/版本/参考变化停止新派发；普通模型Q/E/K失败作为结果保留并阻断依赖，不能因此删除样本。无重试、补跑或自动扩容。预算不足、截止期及资源约束同样禁止派发。当前这些不是已验证本批实现。

## HOLD 的不可满足条件

- **B1**：No qualified independent task: candidate history independence unsigned; event precedes prospective protocol; prepared sources alone do not certify independence.
- **B2**：All six references have null reviewer/decision; no independent accepted reference or executable scoring mapping.
- **B3**：No two-model measured profiles matching terms/observed/reconcile contracts; separate calibration task identities absent.
- **B4**：Production same-state fork, authoritative frozen policy binding and full-terminal independent scoring not bound. Offline adapter has no live backend; joint executor returns truncated report summary.
- **B5**：Actual account region, model access/version stability, complete tokenized prompts and applicable billing not certified; operational cash limits cannot be finalized.
- **B6**：One event/two repeats cannot establish cross-event reproducible or confirmatory benefit. No natural feedback observed; absence must be retained, not repaired with synthetic faults.

真实反馈尚未出现不是要求预先制造异常；此处HOLD主要来自任务/参考、匹配数据、执行评分绑定及预算未就绪。付费授权是后续单独关口，不拿“本轮零付费”本身当科学准入失败。

机读配置：`DYNAMIC_PI_FINAL_EXPERIMENT_CONFIG.json`；SHA256 `974e2aebcf312b09a6466ab13ccc142fc6ba236b4894d1d8faa888dc037f8b92`。所有已检查依赖哈希写入配置。本轮只新增这两个交付文件；未跑旧实验、未改冻结算法、未访问ZCode测试池、无新模型/API推理调用或付费。交付后停止。
