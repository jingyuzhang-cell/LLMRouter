# Legacy Data Mapping（2026-10-31，零调用）

将 6 轮历史实验数据映射到 Feedback Schema V1。

---

## 1. Stage-B（124 调用，能力画像）

| Schema 字段 | 可映射 | 来源 | 缺失 |
|---|---|---|---|
| run_context.task_id | ✓ | FIVE_ARM_SUMMARY.task | — |
| run_context.dag_snapshot | ✗ | 无节点级数据 | **缺失：仅有 arm 级结果** |
| run_context.initial_pi | △ | arm 名暗示分配规则 | 非逐节点 |
| run_context.anomaly | ✓ | 无注入 → fault_layer=none | — |
| scheduling_actions | ✗ | 无决策记录 | **缺失** |
| execution_results.per_node | ✗ | 无节点级数据 | **缺失** |
| execution_results.terminal.Q_terminal | ✓ | FIVE_ARM_SUMMARY.Q | 口径各任务不同 |
| cost_latency.total_tokens | ✓ | FIVE_ARM_SUMMARY.tok | — |
| cost_latency.makespan_s | ✓ | FIVE_ARM_SUMMARY.wall | — |
| attribution | ✗ | 无配对归因设计 | **缺失** |

**结论：Stage-B 数据仅可用于画像更新，不可用于归因。**

---

## 2. R6（100 调用，恢复实验）

| Schema 字段 | 可映射 | 来源 | 缺失 |
|---|---|---|---|
| run_context.anomaly | ✓ | transport@timeline, transient | — |
| execution_results.per_node | ✓ | ledger purpose 含节点名 | quality_signal 缺失 |
| execution_results.terminal | ✓ | run 结果 | 部分评分口径不统一 |
| scheduling_actions | △ | 策略臂名暗示（R-only等） | 无状态快照 |
| attribution | △ | 恢复臂 vs Static | PRELIMINARY |

---

## 3. R9B（80 调用，持久合同故障）

| Schema 字段 | 可映射 | 来源 | 缺失 |
|---|---|---|---|
| run_context.anomaly | ✓ | contract@verification, persistent | fault_layer 需补充为 merge_interface |
| scheduling_actions | ✓ | rounds 含 z_op | 无 state_snapshot |
| execution_results.per_node | ✓ | calls 含节点/成功/失败 | quality_signal 部分缺失 |
| execution_results.terminal | ✓ | terminal_facts + terminal_stats | — |
| cost_latency | ✓ | tokens/makespan | — |
| attribution | ✓ | B(A含Z) vs A(不含Z) | PRELIMINARY, SINGLE_CELL |

---

## 4. DYNPI（61 调用，瞬态故障 π 对照）

| Schema 字段 | 可映射 | 来源 | 缺失 |
|---|---|---|---|
| run_context.anomaly | ✓ | transport@reasoning, transient | — |
| scheduling_actions | ✓ | rounds + 模型切换记录 | 无 state_snapshot |
| execution_results.per_node | ✓ | calls 含逐节点模型/成功 | quality_signal 部分有 |
| execution_results.terminal | ✓ | Q_adj + terminal_facts | — |
| cost_latency | ✓ | tokens/makespan | — |
| attribution | ✓ | π-only vs Static-π/R-only | PRELIMINARY, LOW_N |

**特有数据**：3/5 π-only runs 有模型切换记录（flash→glm53）——π 激活条件的唯一直接证据。

---

## 5. TGV（41 调用，Real-MCF 四臂）

| Schema 字段 | 可映射 | 来源 | 缺失 |
|---|---|---|---|
| run_context.anomaly | ✓ | 无注入 → Real-MCF（MCF-NOT-MANIFESTED） | fault_layer=unknown |
| run_context.reference_set | ✓ | TGV_REFERENCES_ADJUCATED | AI_ADJUDICATED |
| execution_results | ✓ | PAIRS.json | — |
| cost_latency | ✓ | tokens/makespan | — |
| attribution | △ | 四臂配对 | CROSS_SCORING 风险（Silver vs AI_ADJUDICATED） |

---

## 6. H1（79 调用，合并合同故障六组）

| Schema 字段 | 可映射 | 来源 | 缺失 |
|---|---|---|---|
| run_context.anomaly | ✓ | contract@verification, persistent | fault_layer=merge_interface ✓ |
| run_context.dag_snapshot | ✓ | 完整 DAG + split 后版本 | — |
| scheduling_actions | ✓ | rounds 含 z_op + rationale | 无完整 state_snapshot |
| execution_results.per_node | ✓ | calls 逐节点 | quality_signal 部分缺失 |
| execution_results.terminal | ✓ | Q_adj + key_fact_results | — |
| cost_latency | ✓ | tokens/makespan/wasted（可计算） | — |
| attribution | ✓ | 6组配对设计 | PRELIMINARY, SINGLE_CELL |
| prediction_errors | △ | 可从成本悖论推算 | 非直接记录 |

**H1 是最接近完整 Schema 的数据源。**

---

## 数据映射完整度汇总

| 实验 | run_context | scheduling_actions | execution_results | cost_latency | attribution |
|---|---|---|---|---|---|
| Stage-B | 40% | 0% | 30% | 80% | 0% |
| R6 | 70% | 30% | 70% | 80% | 40% |
| R9B | 80% | 60% | 80% | 90% | 60% |
| DYNPI | 80% | 60% | 80% | 90% | 50% |
| TGV | 80% | 40% | 80% | 90% | 40% |
| **H1** | **90%** | **70%** | **90%** | **95%** | **70%** |

**结论**：H1 数据最完整，R9B/DYNPI 次之，Stage-B 最不完整。后续实验应按 Schema V1 全字段采集。
