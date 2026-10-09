# 固定 DAG 的 X/Z 联合搜索评估接入

本轮仅实现与零调用验证，没有启动真实模型。旧 Smoke 及其他窗口的 unified_space.py / closed_loop_test.py 均未修改。

## 已实现

- evaluator.py 的 space() 精确对应原 proposal_v2 的 48 个唯一配置：e1/e2/r 各 medium 或 large，v 为 coder 或 large，Z=NONE/LOCAL/FULL。
- JointEvaluator 接受已选择的 config_id 和冻结状态故障面板，调用已验证的四节点执行逻辑。使用函数私有 globals 注入独立的 e1/e2/r/v 分配，不修改原 planned_models，也不更改共享全局变量。
- MeteredExecutor 复用 Smoke 的持久化 Budget 与 dispatch/prepare 接口。SearchSession 提供 select → evaluate → observation 的在线接口，不向 select 暴露未执行候选的 Q/C/L。它不是六个算法的实现；不能把传入 random callback 称为 GP/EHVI。
- FULL 新语义：输出中出现空提取、推理解析失败、验证失败/不一致时，四节点完整重跑一次，large→coder，medium/coder→large；不得依据 gold 或 ok 触发。LOCAL 保留原执行语义。两者的模型替换规则不同，不能把二者直接作为“仅重跑范围不同”的纯消融。

## 两种费用，两个账本

| 字段 | 定义 |
|---|---|
| objectives.Q | 冻结任务面板的最终准确率，仅末端评分访问 gold |
| objectives.C | 冷工作流每个逻辑调用的来源 Token 之和，含恢复/重跑；搜索缓存别名仍贡献部署 Token |
| objectives.L | 上述逻辑调用的来源服务时延之和，即串行服务需求的轨迹重建值 |
| search_spend | 本次新增物理请求、Token、服务时延及观察墙钟；缓存命中新增费用为零 |

L 不是本次观察的部署端到端时延，不是并行 DAG 关键路径，也不含模型启动；正式主张必须使用“重建串行服务需求”。同一缓存证据得到相同 Q/C/L，但跨独立运行的服务时延含测量噪声，不能承诺不同调用顺序下 L 数值完全一致。后续若要求 observed deployment latency，需要独立、固定部署策略下的冷执行确认。

故障收费方式有意更新：先取得并计量有效底层响应，再替换其答案以注入故障，保留底层响应 Token/时延作为对应部署费用。物理原始账本不被覆盖，损坏答案只出现在 WORKFLOW.jsonl。这样不把故障当免费模型调用，也不拿旧 LR 轨迹补费用。这与旧 Smoke 的纯零费用注入不同，必须做新的小规模真实验证，不可用旧 Smoke 为新增语义背书。

## 冻结资源上限

SEARCH_BUDGET_V1.json 是不可静默覆盖的资源上限版本，不是执行授权或正式统计协议。

- 六方法 × 三个搜索种子，共最多 18 会话；三个搜索种子不是三个独立任务集。
- 每会话最多选择 12 个配置，含两个公共随机初始配置；评估 clean/fault30。
- 每会话 400 次新请求、3,276,800 Token、7200 秒工作时限、零重试。
- 总上限 7200 请求、58,982,400 Token、36 GPU 小时。它们是保守停止上限，不是预期消耗，也未获批准。
- 资源计算单位为实测的 8 题面板。若只是将旧四配置工作量乘三，得到 330 请求、123,573 Token、约 36.7 分钟/会话；这只是透明的参考情景，不能当新 48 配置/FULL 的预测。
- Smoke 的九次切换平均 67.18 秒，最大 87.66 秒，占总墙钟 82.41%；不能只按 127 秒服务总时延估算预算。
- 遇到任何资源上限，允许不足 12 次完成评估；部分候选不写入完整目标，实际已花费用仍计入。比较公共预算范围，不为补齐曲线自动增加预算。

独立开发/校准/测试 UID、确认性任务样本量尚未冻结，8 只是资源测量单位。现有暴露任务不能重命名成独立测试集。因此当前不能声称“正式搜索已获准入”，也不能给出一个可直接启动十八会话的命令。

## 验证与使用接口

```bash
cd /root/r3_own_pool
python -m unittest collab_scheduler_v1.joint_search_v1.test_evaluator -v
```

8 项新增零调用测试通过，包括全部 48 配置、FULL 重跑、缓存后的部署费用不变、故障源费用、无 gold 检测和选择预算；与旧计量/Smoke 测试合计 26 项通过。

接口组合是 Budget → MeteredExecutor(directory,budget,dispatch,prepare,bindings) → JointEvaluator(executor,ledger,tasks) → SearchSession。生产 dispatch/prepare 必须由持有 GPU 锁、执行墙钟中断、检查批准协议哈希的生命周期管理器提供；不得直接裸传 engine.call_model 绕过准入。当前本目录不提供真实执行 CLI。

## 下一道准入

六个 selector 的实际实现与状态/增量成本信息边界审查；独立任务清单和任务层面的样本量依据；FULL/新故障收费真实验证；会话 GPU 生命周期与全局持久化配额管理接线。以上完成后再请求正式预算审批。原 Smoke 的批准只覆盖已完成的 smoke8_metering_01。

## 执行准入层补充（2026-10-09）

runtime.py 现已接入 CampaignQuota → Budget → MeteredExecutor → JointEvaluator → SearchSession。此前“会话生命周期/总配额未接线”这一工程缺口已解决；SEARCH_BUDGET_V1.json 保持冻结，更新状态记录在 ADMISSION_V1.json。

- 会话全程持有 campaign 锁及 GPU 锁；每个方法/种子会话先持久化预留完整资源上限，结束后才释放未使用部分。
- 崩溃后的未结算预留不会因重新启动而消失。失败也占用一个会话槽；同一方法/种子不能自动重跑。
- SIGALRM/SIGTERM 中断工作并进入清理；7200 秒会话上限内留 60 秒清理余量。后端清理失败则保留整笔 campaign 预留，等待人工核对。
- 缺失 usage 保留8192 Token预留，不重试。会话分别保存任务、状态、协议、模型来源快照和 STATUS。
- 每个方法/种子创建空缓存，避免跨方法物理缓存补贴。各方法按相同 seed 生成两项公共初始配置，计入12配置上限。
- require_admission 校验明确批准的协议哈希、环境开关、准入结果与绑定输入。低层 run_session 用于 Stub 和准入后的生产组装；当前不提供绕过缺失研究条件的真实搜索 CLI。

新增10项运行层测试通过，与原有测试合计36项。包含全会话 Stub、总配额跨进程恢复、独占锁、失败结算、超时、清理失败以及未批准拒绝。没有新增真实模型调用。

```bash
cd /root/r3_own_pool
python -m collab_scheduler_v1.joint_search_v1.preflight
python -m unittest collab_scheduler_v1.joint_search_v1.test_runtime collab_scheduler_v1.joint_search_v1.test_evaluator -v
```

默认预检会诚实报告 NOT_READY：还缺六算法审查、独立任务清单/样本量、新增语义的真实验证和正式预算批准。代码绑定不匹配则退出码2；研究条件未满足但绑定正确时正常输出待办，不启动任何计算。
