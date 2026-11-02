# P1: LLM 自动 DAG 生成与结构优化方案设计

**日期**: 2026-11-01 | **状态**: 零调用设计稿 | **台账**: #108

## 一、科学问题

LLM 自动生成的任务 DAG，能否通过结构优化，在不损害终端质量的前提下，提高复杂任务的执行效率？

## 二、三组对照设计

| 组 | 方法 | 节点生成 | 结构处理 | 研究作用 |
|---|---|---|---|---|
| **A Raw DAG** | LLM 直接生成 DAG 后执行 | LLM | 无 | 原始基线 |
| **B Optimized DAG** | LLM 生成后经结构优化再执行 | LLM | 优化算法 | 核心研究对象 |
| **C Reference DAG** | 冻结的 E04 参考结构（人工定义） | 人工 | 无 | 诊断性参照（非理论最优、非 Gold，无独立证据不得称最优） |

三组使用相同任务、文档、模型分配、资源约束、终端评分。

## 三、DAG 生成协议

### 3.1 LLM DAG 生成提示词（组 A 和 B 共用）

```
你是任务分解专家。请将以下资本市场分析任务分解为一个 DAG（有向无环图）。

任务：{task_description}
可用文档：{doc_list}

要求：
1. 每个节点代表一个可独立执行的子任务
2. 节点之间用依赖关系连接（上游完成后下游才能执行）
3. 无依赖的节点可以并行执行
4. 不应过度拆分（简单步骤不需要单独节点）
5. 不应遗漏关键子任务
6. 最终必须有一个终端综合节点

输出JSON:
{
  "nodes": [
    {"id": "node_1", "task": "具体子任务描述", "doc_refs": ["doc_1"], "kind": "extracts|reasoning|verification|report"},
    ...
  ],
  "edges": [
    {"from": "node_1", "to": "node_2"},
    ...
  ]
}
```

### 3.2 LLM DAG 生成的已知风险

| 风险 | 表现 | 后果 |
|---|---|---|
| 过度拆分 | 简单步骤拆成多节点 | 调用增加、成本上升 |
| 拆分不足 | 多个分析方向塞进一个节点 | 并行能力丧失 |
| 虚假依赖 | 无真实依赖的节点被串行化 | Makespan 增加 |
| 遗漏依赖 | 下游未等待上游完成 | 信息不完整 |
| 重复节点 | 多个节点做相同工作 | 冗余调用 |
| 遗漏任务 | 关键分析方向缺失 | 终端质量下降 |

## 四、结构优化算法设计

### 4.1 优化动作空间

| 动作 | 描述 | 触发条件 | 预期收益 |
|---|---|---|---|
| **MERGE_NODES** | 合并功能重复的节点 | 两个节点任务描述高度相似 | 减少冗余调用 |
| **SPLIT_NODE** | 拆分承载过多功能的节点 | 一个节点包含多个独立子任务 | 提高并行能力 |
| **REMOVE_EDGE** | 删除虚假依赖 | 边的依赖关系无真实数据流支撑 | 缩短 Makespan |
| **ADD_EDGE** | 添加缺失依赖 | 下游确实需要上游结果但未连接 | 防止信息不完整 |
| **REMOVE_NODE** | 删除无效节点 | 节点输出不被任何下游消费 | 减少浪费 |
| **ADD_NODE** | 添加遗漏任务 | 关键分析方向缺失 | 提高终端覆盖 |

### 4.2 优化决策（程序化，非 LLM）

优化不依赖另一个 LLM 调用（避免 LLM 评估 LLM 的循环），而用程序化规则：

```python
def optimize_dag(dag, doc_info):
    """Programmatic DAG structure optimization. Zero model calls."""
    changes = []
    
    # Rule 1: Detect duplicate nodes (same doc_refs + similar task)
    for i, n1 in enumerate(dag.nodes):
        for j, n2 in enumerate(dag.nodes[i+1:], i+1):
            if (set(n1.doc_refs) == set(n2.doc_refs) and 
                task_similarity(n1.task, n2.task) > 0.8):
                changes.append(('MERGE_NODES', n1.id, n2.id))
    
    # Rule 2: Detect false dependencies (no data flow)
    for edge in dag.edges:
        if not has_real_data_flow(edge.from, edge.to, doc_info):
            changes.append(('REMOVE_EDGE', edge.from, edge.to))
    
    # Rule 3: Detect missing dependencies (downstream uses upstream output)
    for node in dag.nodes:
        required_docs = set(node.doc_refs)
        upstream_docs = get_upstream_docs(node, dag)
        missing = required_docs - upstream_docs - set(node.doc_refs)
        if missing:
            changes.append(('ADD_EDGE', find_provider(missing, dag), node.id))
    
    # Rule 4: Detect orphan nodes (no downstream consumer, not terminal)
    for node in dag.nodes:
        if (not is_terminal(node, dag) and 
            not get_consumers(node, dag)):
            changes.append(('REMOVE_NODE', node.id))
    
    # Rule 5: Detect overloaded nodes (multiple distinct sub-tasks)
    for node in dag.nodes:
        subtasks = detect_distinct_subtasks(node.task)
        if len(subtasks) > 1:
            changes.append(('SPLIT_NODE', node.id, subtasks))
    
    return changes
```

### 4.3 Reference DAG（组 C，冻结）

E04 专家参考结构（操作员审定，台账 #108）：

```
Layer 1:  A(财务数据提取/doc2) ∥ C(监管时间线/doc1+doc2) ∥ D(经营风险/doc3)
Layer 2:  B(财务异常计算/依赖A)
Layer 3:  E(交叉核验/消费A+B+C)
Layer 4:  F(终端报告/消费E+D)
```

节点数 6 / 边数 6 / 深度 4 / 最大并行宽度 3。
（勘误 2026-11-01：原文误记边数 7；按文字结构列举 A→B, A→E, B→E, C→E, E→F, D→F 共 6 条。已同步 E04_reference_dag.json。）

## 五、终端评价指标

| 维度 | 指标 | 方法 |
|---|---|---|
| **DAG 结构** | 节点数/边数/深度/并行宽度 | 程序化图分析 |
| **结构变化** | 拆分/合并/加边/删边计数 | 优化日志 |
| **Q 终端质量** | 事实覆盖率/证据正确率/关键事实 | 确定性评分 |
| **C 成本** | 总调用/总 Token/费用 | 账本 |
| **L 时延** | Makespan/关键路径/按期完成 | 时间戳 |
| **效率** | Q/调用比、Q/Token比 | 计算 |

**防止虚假成功**：优化后 Q 提高但 C/L 也大幅增加 = 不可认定为成功。
必须同时报告 Q/C/L 变化方向。

## 六、历史实验隔离

| 项 | 处理 |
|---|---|
| E04 文档 | 复用（内容不变） |
| 参考事实 | 本轮独立冻结（与 M7-3D 参考事实分开） |
| 模型分配 | 固定（flash 提取 / glm53 核验+报告） |
| 信息合同 | 使用 Extract V2（date_role） |
| 异常注入 | 无 |
| 动态调度 | 无（本轮纯结构研究） |

## 七、P2 实验协议（待 P1 审查后冻结）

| 项 | 预设 |
|---|---|
| 重复 | 每组 × E04 × 3 重复 = 9 run |
| 调用 | Raw DAG 约 6-10 节点 × ~500 tok = ~3-5K/run |
| 总调用 | ~9 × 5 = ~45 + 优化算法调用 = ~50 |
| Token | ~50K |
| 现金 | ¥0 |
| 统计 | 探索性（n=3/组），描述统计 + 配对方向 |

## 八、P1 交付物

| 文件 | 内容 |
|---|---|
| 本设计文档 | 三组对照 + 生成协议 + 优化算法 + 评价指标 |
| dag_optimizer.py（待实现） | 程序化 DAG 结构优化器 |
| E04_reference_dag.json（待冻结） | 专家参考 DAG |
