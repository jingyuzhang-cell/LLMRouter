# PROJECT_CODEBASE_UNDERSTANDING_REPORT.md
# 全面代码架构与科研状态认知报告
# 2026-10-26 | 只读审计生成，未修改任何代码，未运行任何模型

---

## 1. 项目总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    研究目标（三层递进）                            │
│  Single LLM → Static DAG → Dynamic DAG → Pareto-aware Selection │
│  联合动作 a = (Z, R, π)                                          │
│  Z=恢复模式  R=恢复闭包  π=模型分配                               │
└─────────────────────────────────────────────────────────────────┘
```

### 真实代码架构图

```mermaid
graph TB
    subgraph "本地执行后端"
        A[static_dag_v0/run.py<br/>vLLM Server localhost:8128<br/>Qwen2.5-7B/14B/Coder-7B]
    end

    subgraph "Paper 1 主线 — 截止时间调度"
        B[deadline_reward_v1/<br/>83 py files<br/>(Z,R,π) 联合决策算法<br/>奖励函数 + 约束过滤]
        C[cache_switch_repair<br/>缓存切换 bug 修复]
        D[feedback_local_batch_v1<br/>反馈数据收集 READY-HOLD]
    end

    subgraph "测量引擎 — collab_scheduler_v1"
        E[fault30_protocol.py<br/>冻结配置表+故障池]
        F[fault30_run.py<br/>Executor+eval_config<br/>真实本地Qwen执行]
        G[cube_clean/<br/>Reference Cube 冻结测量]
    end

    subgraph "联合搜索 — joint_search_v1"
        H[evaluator.py<br/>48配置空间<br/>X×Z on DYNAMICDAG]
        I[selectors.py<br/>6种选择器<br/>random/BO/qNEHVI/SA-PGFS]
    end

    subgraph "Typed DAG 协议 — typed_dag_v1"
        J[protocol.py<br/>Graph/Node/Binding/validate]
        K[execution.py<br/>TypedExecutor<br/>拓扑层执行]
        L[joint_recovery.py<br/>(Z,R,π) 联合恢复适配器]
        M[generation.py<br/>LLM DAG 规划+程序侧编译]
    end

    subgraph "DAG 动态重构 — dag_patch_*"
        N[dag_patch_p0.py<br/>原子补丁操作<br/>split/insert/remove/rewire]
        O[dag_patch_p1b_v3.py<br/>4策略×故障任务<br/>真实执行适配]
    end

    subgraph "Paper 2 — SA-PGFS"
        P[sa_pgfs_v1/<br/>代理辅助 Pareto 搜索<br/>GP surrogate + EHVI]
    end

    subgraph "舆情 DAG 管线"
        Q[opinion_dag_dataset_v1/<br/>12个风险事件数据集]
        R[opinion_contract_v2/<br/>V2 语义合同<br/>防答案泄漏]
        S[opinion_extract_grounding_fix_v1/<br/>引用锚定验证]
        T[opinion_extract_transport_adapter_v1/<br/>数组→对象适配]
        U[opinion_three_model_extract_v1/<br/>三模型抽取 READY-HOLD]
    end

    subgraph "云端模型接入"
        V[qwen-plus<br/>DashScope ✅ PASS]
        W[deepseek-flash<br/>api.deepseek.com ❌ 合同拒绝]
        X[GLM-5.3<br/>open.bigmodel.cn ❌ 从未调度]
    end

    A --> F
    A --> O
    F --> G
    G --> I
    G --> P
    E --> F
    J --> K
    K --> L
    L --> B
    Q --> R
    R --> S
    S --> T
    T --> U
    V --> U
    W --> U
    X --> U
```

---

## 2. 关键目录说明

| 目录 | 职责 | 状态 |
|---|---|---|
| `static_dag_v0/` | 基础 DAG 实验+路由+故障基准 | ✅ 冻结（Paper 1 数据） |
| `collab_scheduler_v1/` | 核心调度框架（250 py files） | ✅ 活跃 |
| `collab_scheduler_v1/typed_dag_v1/` | Typed DAG 协议+联合恢复 | ✅ 活跃 |
| `collab_scheduler_v1/joint_search_v1/` | 48配置联合搜索 | ✅ 活跃 |
| `deadline_reward_v1/` | 截止时间奖励调度核心 | ✅ 活跃（Paper 1 主线） |
| `sa_pgfs_v1/` | SA-PGFS 代理搜索 | 休眠（Paper 2） |
| `opinion_contract_v2/` | V2 语义合同 | ✅ 活跃 |
| `opinion_extract_grounding_fix_v1/` | 引用锚定 | ✅ 活跃 |
| `opinion_extract_transport_adapter_v1/` | 传输适配 | ✅ 活跃 |
| `opinion_three_model_extract_v1/` | 三模型抽取 | ✅ 当前前沿（READY-HOLD） |
| `feedback_local_batch_v1/` | 反馈数据收集 | READY-HOLD（待授权） |
| `dag_patch_*.py` | 运行时 DAG 重构 | 活跃（P2 准备） |
| `paper_method_feedback_aware_dag/` | 论文写作 | 活跃（Paper 1 写作） |
| `paper2_state_conditioned_scheduling/` | Paper 2 结果草稿 | 休眠 |

---

## 3. 核心代码调用链

### 3.1 截止时间调度主线（Paper 1）

```
用户任务 → deadline_reward_v1/policy.py:_score_and_pick()
  → 约束过滤 (q̂≥0.80, P̂(T≤D)≥0.90, ΔC≤B)
  → argmax Ê[R_task]
  → joint_recovery.py:prepare(Z, π) → R = descendant closure
  → apply(action) → TypedExecutor → 本地 vLLM 执行
```

关键文件：
- `deadline_reward_v1/reward.py`：R = 1(T≤D)·q − λc·C/C₀ − λt·(T−D)₊/D − λf·1(T>D)
- `deadline_reward_v1/predictor.py`：Normal-CDF 时延估计
- `collab_scheduler_v1/typed_dag_v1/joint_recovery.py`：(Z,R,π) 机制适配器
- `collab_scheduler_v1/typed_dag_v1/execution.py:TypedExecutor.run()`：拓扑层执行

### 3.2 舆情 DAG 管线（当前前沿）

```
事件数据集(opinion_dag_dataset_v1) → SOURCE_ENVELOPE 构建
  → 6-node DAG (extract_current/media/history → reconcile → assess → report)
  → V2 合同(opinion_contract_v2/validator.py:Guard)
  → 引用锚定(opinion_extract_grounding_fix_v1/grounding.py:QuoteValidator)
  → 传输适配(opinion_extract_transport_adapter_v1/adapter.py:receive)
  → 三模型抽取(opinion_three_model_extract_v1/RUN.py)
  → 云端 API (qwen-plus / deepseek-flash / GLM-5.3)
```

### 3.3 故障测量引擎

```
fault30_protocol.py (冻结配置) → fault30_run.py:eval_config()
  → 本地 vLLM 执行 → cube_clean/ (Reference Cube 冻结)
  → joint_search_v1 (搜索) → sa_pgfs_v1/replay_v2.py (零调用回放)
```

---

## 4. 核心算法说明

### 4.1 DAG 生成
- **方式**：`generation.py:InitialDAGGenerator` 支持语义/目标IR/操作源/计算IR 五种规划模式
- **编译**：LLM 返回 JSON → 程序侧编译（`assembly.py`）→ `validate()` 结构校验
- **拓扑**：支持分叉（e1∥e2）与合流（r 依赖 e1+e2），节点类型必须端口匹配
- **限制**：当前舆情 DAG 用手工审核计划，非 LLM 自动生成

### 4.2 异构模型能力估计
- **本地池**：Qwen2.5-7B(medium)/14B(large)/Coder-7B(coder)，vLLM 权重哈希校验
- **云端池**：qwen-plus/deepseek-flash/GLM-5.3，`MODEL_POOL.json` 配置
- **估计方式**：类型基线分配（extraction→medium, reasoning→large, verification→coder）
- **校准**：历史数据审计（`p0_prediction_joint_20261014`）→ Brier 0.24-0.27 → **INSUFFICIENT_DATA**

### 4.3 动态调度
- **静态**：`heterogeneous_models.py:allocate()` 类型基线
- **动态**：`policy.py:_score_and_pick()` 两阶段（约束过滤→奖励最大化）
- **反馈**：检测→恢复→模型重分配，`joint_recovery.py:apply()` 幂等执行
- **约束**：硬预算（token reserve/settle）、SIGALRM 墙钟、现金上限

### 4.4 异常检测与恢复
- **检测信号**：facts 空/不可解析（e 节点）、表达式不可执行（r 节点）、值不一致（v 节点）
- **恢复范围**：`dag_closure.py` 后代闭包（LOCAL）或全图（FULL）
- **模型重分配**：`reassign.py`，π 绑定每个恢复+剩余节点
- **缓存复用**：`_cache_guard()` 重新验证缓存 facts/bindings/values

### 4.5 (Z, R, π) 联合决策
- **实现位置**：`deadline_reward_v1/policy.py` + `typed_dag_v1/joint_recovery.py`
- **决策**：约束过滤（q̂/时延/预算）→ 候选动作枚举 → argmax 奖励
- **执行**：`joint_recovery.apply()` 通过 TypedExecutor 真实执行
- **是否联合**：是——Z 决定 R 范围，π 在 R 上联合分配；但候选空间有限（48配置）

---

## 5. 数据结构与合同

| 类型 | 文件 | 关键字段 |
|---|---|---|
| `Graph/Node/Binding` | `protocol.py` | id, deps, contract, assignment |
| `FactCandidate` | `grounding.py` | entity, field_role, value, unit, quote, source_ref |
| `EvidenceRef` | `schema.py` | source_id, sha256, page, start, end, quote |
| `Claim` | `schema.py` | speaker, claim_text, claim_type |
| `Relation` | `schema.py` | relation_type (SUPPORTED/CONTRADICTED/UNKNOWN) |
| `RiskAssessment` | `schema.py` | risk_points[] |
| `OpinionReport` | `schema.py` | confirmed, differences, unresolved |

---

## 6. 真实模型执行链

| 模型 | 执行次数 | 状态 | 端点 |
|---|---|---|---|
| Qwen2.5-7B/14B/Coder | 数千次（主执行后端） | ✅ 稳定 | 本地 vLLM |
| qwen-plus | ~8次（规划+舆情抽取） | ✅ PASS（需数组包装） | DashScope |
| deepseek-flash | 1次（舆情抽取） | ❌ CONTRACT_REJECTED（空unit） | api.deepseek.com |
| GLM-5.3 | 0次 | ❌ 配置完成但从未调度 | open.bigmodel.cn |

---

## 7. 研究问题与代码映射

| RQ | 算法 | 实现模块 | 真实证据 | 缺失证据 |
|---|---|---|---|---|
| RQ1: 异构能力差异 | 类型基线分配 | typed_dag_v1/heterogeneous_models.py | 120题条件节点质量表 | 云端三模型节点能力矩阵 |
| RQ2: 分解+动态调度收益 | (Z,R,π)联合决策 | deadline_reward_v1 + joint_recovery.py | 60题真实确认（负结果）+ E2探针PASS | 足够数据量的正结果确认 |
| RQ3: 多目标优化空间 | SA-PGFS | sa_pgfs_v1 + joint_search_v1 | 零调用回放表 | 真实在线搜索实验 |

---

## 8. 已完成与未完成

### IMPLEMENTED_AND_REAL_TESTED
- 本地 vLLM 执行（数千次调用）
- 120 题故障基准（3 种子，修正后）
- Frozen 200 独立确认
- Exact Pareto 18 配置穷举
- E2 恢复机制探针（2 次云端调用，PASS）
- 舆情 V2 抽取合同（Qwen PASS）
- 60 题截止时间确认运行（诚实负结果）

### IMPLEMENTED_OFFLINE_ONLY
- SA-PGFS 搜索（零调用回放）
- DAG Patch 合法性验证（300 随机 DAG）
- 故障检测 F1 评估（真实轨迹回放）
- 预算/增量成本预测器

### IMPLEMENTED_NOT_CONNECTED
- GLM-5.3 端点（配置完成，从未调度）
- DeepSeek 执行适配器（仅费用估算分支）

### NOT_IMPLEMENTED
- 舆情 assess/report 节点的云端真实执行
- 任务级质量预测的部署级校准
- 通用 DAG 结构搜索（非固定 4 节点/6 节点）
- 完整截止时间 SLA（当前为墙钟/费用上限）

---

## 9. 关键问题

### P0（阻塞当前实验）
| 问题 | 影响 | 修复状态 |
|---|---|---|
| 任务级质量预测数据不足 | 动态调度先验不可部署 | `p0_prediction_joint` → NO-GO |
| DS 先验 q=0.6 为手工 stub | 60题确认运行 46/60 降级根因之一 | 需 `feedback_local_batch` 数据 |

### P1（影响论文质量）
| 问题 | 影响 |
|---|---|
| 缓存切换 bug（已修复但 60 题结果为负） | 需修复后重新运行确认 |
| 舆情 assess/report 未真实执行 | 完整 DAG 管线断链 |
| 云端三模型能力矩阵缺失 | RQ1 跨模型证据不完整 |

### P2（可后续处理）
| 问题 | 影响 |
|---|---|
| 论文两次数据修正的历史清理 | 写作时需严格区分 |
| SA-PGFS 休眠待激活 | Paper 2 时间线 |

---

## 10. 下一步研究建议（按价值排序）

### 建议 1：运行 `feedback_local_batch_v1`（最高优先级）
- **内容**：4 任务 × 2 模型（qwen-plus + deepseek-flash），≤8 请求，收集真实反馈数据
- **价值**：直接解决 P0 阻塞——为任务级质量预测提供第一批真实校准数据
- **前置条件**：付费授权（≤8 请求 ≈ ¥0.05）

### 建议 2：完成三模型舆情抽取批次
- **内容**：`opinion_three_model_extract_v1`（qwen-plus/deepseek-flash/GLM-5.3 各 1 次）
- **价值**：建立云端三模型节点能力矩阵的第一行；验证 DeepSeek 合同兼容性
- **前置条件**：付费授权（3 请求 ≈ ¥0.02）

### 建议 3：修复后重跑 60 题截止时间确认
- **内容**：缓存切换 bug 已修复，用修正后代码重跑 `deadline_reward_v1` 确认运行
- **价值**：将 46/60 降级的负结果转化为修复后正结果，直接支撑 Paper 1 核心贡献
- **前置条件**：建议 1 完成（校准预测先验）+ 付费授权

---

## 简明总结（回答七个问题）

**1. 项目在研究什么？**
面向截止时间约束的反馈驱动异构 LLM DAG 动态调度。核心是 (Z,R,π) 联合动作：选择恢复模式 Z、确定恢复范围 R、分配恢复及剩余节点的模型 π。

**2. 核心算法是什么？**
两阶段约束调度器：约束过滤（质量/时延/预算）→ argmax 期望奖励（R = 1(T≤D)·q − 成本/时延罚项）。底层是 Typed DAG 执行器 + 联合恢复适配器。

**3. 当前执行主线是哪套代码？**
本地 vLLM（Qwen2.5 系列）执行 DAG 节点；云端 qwen-plus 用于 DAG 规划和舆情抽取。`deadline_reward_v1` 是 Paper 1 调度核心，`collab_scheduler_v1/typed_dag_v1` 是 DAG 执行引擎。

**4. 已实现并真实验证？**
本地 DAG 执行（数千次）、故障注入+恢复（E2 探针 2 次云端调用 PASS）、舆情 V2 抽取合同（Qwen PASS）、60 题截止时间确认运行（负结果但有价值）。

**5. 看似完成但只是 Stub/离线？**
SA-PGFS 搜索（零调用回放）、DAG Patch 合法性（模拟执行）、预算/成本预测器（离线枚举）、舆情 assess/report 节点（Stub 模式从未真实执行）。

**6. 距离完整舆情 DAG 动态调度还有什么差距？**
- 舆情 assess/report 节点未用真实云端模型执行（管线断链）
- DeepSeek 合同拒绝、GLM 从未调度（三模型能力矩阵不完整）
- 任务级质量预测无部署级校准数据（预测先验为手工常数）
- 完整 6 节点 DAG 在真实云端从未端到端运行过

**7. 最应该先做哪一件事？**
运行 `feedback_local_batch_v1`（4 任务 × 2 模型，≤8 请求）——它同时解决两个 P0 阻塞：提供质量预测校准数据 + 验证修复后缓存/调度链路。
