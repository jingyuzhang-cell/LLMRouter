# Tool-aware Static DAG v1：同题执行器消融

| 方法 | 成功率 | 平均质量 | 逻辑tokens | 平均端到端latency |
|---|---:|---:|---:|---|
| Static DAG v0协议（同题重测） | 15% | 0.275 | 22883 | 历史未独立测量 |
| Local Repair | 20% | 0.350 | 38944 | 历史未独立测量 |
| Tool-aware v1 | 100% | 1.000 | 0 | 0.013ms |

Tool Node Accuracy=100%，LLM Node Accuracy=N/A（0个LLM节点）。满足质量高于Static且tokens不高于Repair的判据；这只是执行器消融，不是多模型路由证据。旧数据的服务累计时长不能充当端到端latency。

| Node Type | #Nodes | Small | Medium | Large | R1 | Tool | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---|
| Extraction | 0 | 0 | 0 | 0 | 0 | 0 | N/A |
| Semantic reasoning | 0 | 0 | 0 | 0 | 0 | 0 | 0 | N/A |
| Arithmetic / aggregation | 40 | 0 | 0 | 0 | 0 | 40 | 100% |
| Constraint check | 20 | 0 | 0 | 0 | 0 | 20 | 100% |
| Verification / ordering | 20 | 0 | 0 | 0 | 0 | 20 | 100% |
