# ADDENDUM v1.1 — 统一指标口径、三层归因与统计注意事项（集成层；不修改冻结 v1）

v1 冻结件（PROTOCOL_EVAL_V1.md、qe_k_scorer.py、任务/silver/证据）**哈希不变**；本附录与其
实现 `scoring/metric_mapping_v1_1.py` 为追加版本层，所有跨系统报告以统一口径出具。

## 1. 统一指标口径与字段映射（裁决表）

| 统一名 | 含义 | 来源（v1 冻结字段 → 统一字段） |
|---|---|---|
| Q | 终端内容质量及分项 | Q.value / Q.sub.coverage / unknown_compliance / hallucination_penalty |
| **E_evidence** | 来源定位与**证据充分性**（支持性核验） | 新增派生：evidence_support_rate（被覆盖事实的支持证据确实出现在**本 run 实际检索到的块**中）、citation_support_rate（被引用文档确实包含支持证据）、retrieval_self_sufficiency（本 run 检索块对 silver 引文的自给率——**单独报告**，检索优势不得记为调度优势） |
| K | 输出契约与合法性 | K.first_attempt_contract_rate / repair_count / attempts_total / missing_fields |
| C | 完整成本 | C.model_first / model_repair / planning / retrieval_chars / retrieval_calls / program_ms / total_tokens / reuse_events；价格口径 UNKNOWN 政策不变 |
| L | 实际端到端墙钟 | L.service_s（服务时延合计）/ L.wall_s（单调钟实测，跨会话仅描述性） |
| Reliability | 执行可靠性、完成率、按期率 | Reliability.schema_conformance / verdict / deadline_compliance |

v1 的 `Q.citation_accuracy` 更名为 `citation_presence_rate_v1` 保留（引用位置正确），其"证据真正
支持结论"的强化语义由 E_evidence 两个支持性指标承担；两者并列报告，不互相覆盖。

## 2. 三层归因对照（收益来源识别；批次布局规范）

批次目录：`<batch_id>/<arm>/<task_id>/run_k/{trace.jsonl, deliverable.json}`；arm 取值注册表：

**层 A（结构收益）**：`fixed_graph`（冻结基准图）→ `auto_graph`（Planner 自主图）→
`optimized_graph`（结构优化图）。三臂共用同一模型分配策略 ⇒ 差异归因于规划/结构。

**层 B（静态分配收益；同一张图内）**：`alloc_homogeneous` / `alloc_router` / `alloc_rule` /
`alloc_static_opt`。共用同一初始图 ⇒ 差异归因于模型分配。

**层 C（动态联合调度收益；同一初始图+同一异常注入状态）**：`dyn_Static` / `dyn_R_only` /
`dyn_pi_only` / `dyn_Joint_R_pi` / `dyn_Joint_Z_R_pi`。异常注入协议由窗口1冻结（故障类型、
绑定节点、种子），本模块只按 run 记录对账。

基线臂：`single_model`、`fixed_homogeneous`（全局对照，跨三层引用）。
归因规则：任何总分差异必须落到上表某层的配对比较；三层交叉时先报层内配对再报总表。

## 3. 统计注意事项（冻结为报告纪律）

1. 8 任务 = 机制验证样本；同任务多 run 相关，不得当独立样本计算显著性；
2. 协议 §5 的"≥6/8 任务且 ≥20% 改善"是**事前工程判定门槛**，不是统计功效证明；
3. 正式论文需扩充独立、未曝光事件并按事件配对统计（扩样前保持 HOLD，不提前消耗）；
4. 单事件多 run 只报中位数与逐任务方向；跨批次只作描述性比较并声明会话/负载条件。

## 4. 集成验收（零付费，见 integration/integration_acceptance.py）

任一付费批次开跑前必须通过：schema 校验（全部注册 arm 的合成轨迹）、v1 评分→v1.1 统一映射、
检索对账（trace vs retrieval_log，不一致即 INVALID）、隔离门 CLEAN、冻结清单校验。

## 5. 集成约束（裁决保留，冻结）

1. **效用合成禁止双重加权**：冻结 V1 的 Q 已含 citation_presence_rate 分项；后续将 Q 与
   E_evidence 组合为效用函数时，必须二选一（剔除 Q 中 citation 项或不对 E_evidence 再加权），
   且只允许在报告层合成——原始评分与分项永久保留，**禁止追溯修改 V1**。
2. **评测产物单向流动**：retrieval_self_sufficiency 及一切 E_evidence 指标依赖私有 silver 计算，
   只存在于评测侧输出；**任何被评系统（Planner/检索策略/模型选择器/动态控制器）不得将其作为
   输入**（联调验收 proof-3 已含 no_eval_metric_feedback 检查，持续生效）。

## 6. Phase-2 公平条款（承 PHASE-1 复盘；详见 PHASE2_PROTOCOL.md）

- F1 统一终端交付合同：所有臂经 canonical_assembler（Silver 盲、臂无差）装配；
- F2 输出预算配平：最终合成/单模型 768、中间节点 448–576，截断逐 run 记录，Q 为预算下观测值；
- F3–F5 检索/模型/成本配平与全成本归属（规划检索执行修复合成全计入对应臂）；
- F6 终局可达性检查进入规划合同校验（窗口 2 交付项；仅未来批次生效，不追溯 Phase-1）；
- F7 动态臂 NONE/DECLINE 合法性边界（仅终端合同允许或如实记败时合法）。
