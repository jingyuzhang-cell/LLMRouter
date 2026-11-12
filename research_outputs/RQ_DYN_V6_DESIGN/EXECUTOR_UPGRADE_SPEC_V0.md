# V6执行器最小必要升级规格 V0（草案，待研究窗口+驾驶舱批准后实施）
原则: 不改变V6冻结实验设计(任务结构/配对数/随机化/统计计划均不动)，只增加过程留痕

## 1. 节点级执行日志（每次节点调用追加一条）
```json
{
  "exec_id": "T{n}_S{3|4}_P{pair}_R{rep}", "node_id": "A2",
  "agent_assigned": "glm-flash|glm-air|deepseek", "pi_reason": "initial|realloc",
  "attempt": 1, "t_start": 0.0, "t_end": 3.2, "cost_tokens": {"in":1200,"out":800},
  "status": "ok|anomaly_injected|anomaly_detected|recovered",
  "output_hash": "sha256:...", "parent_hashes": {"A1": "sha256:..."}
}
```

## 2. 决策留痕（PD每次调度决策；FC按固定策略记录对照）
```json
{
  "decision_id": "D17", "trigger": "node_anomaly|quality_feedback|budget|none",
  "decision_opportunity": true,          // 该节点是否真正需要动态判断
  "Z": {"action": "hold|recover|restructure", "scope": "node|closure|subgraph|dag"},
  "R": {"reexecute_set": ["B1","B2"], "cache_kept": ["A1","A3"]},
  "pi": {"changes": [{"node":"B1","from":"glm-flash","to":"glm-air"}]},
  "fc_would_do": {"Z":"full_retry","R":"all_downstream","pi":"fixed"}  // FC同局面对照动作
}
```

## 3. 派生指标（实验后自动计算，写入结果包）
| 指标 | 定义 |
|---|---|
| decision_opportunities | decision_opportunity=true 的决策点数 |
| Z_divergence | PD与fc_would_do的Z动作不同的决策点占比 |
| R_divergence | R集合不同的决策点占比(重执行节点差集/并集) |
| pi_divergence | π分配不同的决策点占比 |
| effective_recoveries | 恢复后受影响下游节点输出改善(对照Gold)的次数 |
| ineffective_recoveries | 恢复后无下游改善的次数 |
| wasted_calls | PD总调用数−有效产出调用数 |

## 4. 实施边界
- 日志为纯追加, 不影响执行路径与随机化序列
- FC侧只记录实际固定策略的等价字段(无决策,记baseline)
- 日志体积预估: 384次执行×~20节点×~300B ≈ 2.3MB, 可忽略
- 零新增模型调用类型; 恢复调用本身已在V5执行器语义内

## 5. V5遗留问题对照
- V5的69%平局含相同调用数 → 本规格的divergence指标可直接回答"PD收益来自联合调度还是调用数差异"
- V5.1零调用问题 → pi_reason字段强制记录分配理由,消除"未触发"歧义
