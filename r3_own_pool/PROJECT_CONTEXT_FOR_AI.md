# PROJECT_CONTEXT_FOR_AI.md
# 快速认知文档 — 供后续 AI 会话使用
# 2026-10-26 | 只读审计生成，未修改任何代码

## 项目目标

**面向截止时间约束的反馈驱动异构多智能体 DAG 动态调度与质量—成本—时延联合优化。**

两条论文线：
- **Paper 1**（主线）：反馈感知 DAG 恢复调度（a=(Z,R,π) 联合动作）
- **Paper 2**（休眠）：状态条件化 Pareto 调度（SA-PGFS 代理辅助搜索）

## 当前核心代码入口

| 模块 | 路径 | 作用 |
|---|---|---|
| 调度核心 | `deadline_reward_v1/` | (Z,R,π) 联合决策算法，奖励函数，60题真实确认运行 |
| Typed DAG 引擎 | `collab_scheduler_v1/typed_dag_v1/` | 类型化 DAG 协议、执行器、(Z,R,π) 恢复适配器 |
| 故障测量 | `collab_scheduler_v1/fault30_run.py` | 真实本地 Qwen 执行 + 30%故障注入 + Z 恢复 |
| 联合搜索 | `collab_scheduler_v1/joint_search_v1/` | 48配置搜索空间，6种选择器（含 qNEHVI） |
| SA-PGFS | `sa_pgfs_v1/` | 代理辅助 Pareto 搜索原型（零调用回放） |
| 舆情合同 | `opinion_contract_v2/` | V2 语义合同（防答案泄漏） |
| 事实锚定 | `opinion_extract_grounding_fix_v1/` | 引用精确锚定验证 |
| 传输适配 | `opinion_extract_transport_adapter_v1/` | 数组→对象包装适配 |
| 三模型抽取 | `opinion_three_model_extract_v1/` | 当前前沿（READY-HOLD 待授权） |

## 真实模型接入状态

| 模型 | 执行 | 规划 | 端点 |
|---|---|---|---|
| Qwen2.5-7B/14B/Coder-7B | ✅ 本地 vLLM（主执行后端） | — | localhost:8128 |
| qwen-plus | ✅ 云端（舆情抽取 PASS） | ✅ DAG 规划 | DashScope |
| deepseek-flash | ❌ 合同拒绝（空 unit） | — | api.deepseek.com |
| GLM-5.3 | ❌ 从未调度 | — | open.bigmodel.cn |

## 关键数据结构

- `Graph/Node/Binding/Output`：Typed DAG 四元组（`protocol.py`）
- `FactCandidate`：{entity, field_role, value, unit, quote, source_ref}（`grounding.py`）
- `EvidenceRef`：{source_id, source_sha256, page, start, end, quote}
- `Claim/Relation/RiskAssessment/OpinionReport`：舆情节点输出类型
- 联合动作 `a=(Z, R, π)`：Z=恢复模式, R=恢复闭包, π=模型分配

## 已实现算法（真实验证 vs 离线）

| 算法 | 状态 |
|---|---|
| (Z,R,π) 联合恢复机制 | ✅ E2 真实探针 PASS（2 次云端调用均正确） |
| 60 题截止时间确认运行 | ✅ 已执行（诚实负结果：46/60 降级） |
| 缓存切换修复 | ✅ 离线验证通过 |
| SA-PGFS 搜索 | 零调用回放（非经验性能声明） |
| 舆情 V2 抽取合同 | ✅ Qwen 真实 PASS；DeepSeek 拒绝 |
| 舆情 assess/report 真实执行 | ❌ 从未用真实云端模型执行 |
| 任务级质量/时延预测 | ❌ 历史数据不足（Brier 0.24-0.27，NO-GO） |

## 当前阻塞项

1. `feedback_local_batch_v1`（4任务×2模型反馈数据收集）等待付费授权
2. `opinion_three_model_extract_v1`（三模型抽取批次）等待付费授权
3. 任务级质量预测先验为手工设定 stub 常数（DS q=0.6 < Qmin=0.8）

## 冻结资料（不可修改）

- `static_dag_v0/multidag_dynamic_120/` 及全部修正后结果
- `static_dag_v0/adaptive_benchmark/` 及 FINAL_AUDITED_RESULTS.md
- `static_dag_v0/frozen200/` 及修正后结果
- `collab_scheduler_v1/cube_clean/`（Reference Cube）
- `deadline_reward_v1/MAINLINE_FREEZE.md`
- 全部 `*_BUGGY/`、`*_CORRECTED*` 历史修正工件

## 历史数据修正记录（不可恢复旧数字）

1. **解析器 bug**：v 节点围栏 JSON 解析缺陷（2026-09-23 修复）
2. **故障治愈 bug**：(model,prompt) 去重缓存意外治愈故障（2026-09-24 修复）
3. **Single fault cost bug**：Frozen 200 Single 故障任务成本记 0（2026-09-26 后处理修正）
