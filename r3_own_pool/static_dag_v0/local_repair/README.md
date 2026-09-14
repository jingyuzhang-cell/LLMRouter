# Static DAG + Local Repair v1

基于 v0 失败证据，保持模型分配和 DAG 不变，只增加当前节点的一次有界修复。用20个新、调用前冻结的同模板采购任务比较 static、local_repair、tool_only。最多240次实际本地请求，无 API 费用，不自动增加实验。

```bash
python -m unittest static_dag_v0.test_core static_dag_v0.test_repair -v
python -m static_dag_v0.repair prepare
python -m static_dag_v0.repair execute
python -m static_dag_v0.validate_repair
```

已启动的目录不能自动重放生成。协议和代码 hash 在 prepare 后冻结。审计、原始请求/响应、每节点修复轨迹、每任务配对结果和报告写在 `run_v1/`。

局部检查器可执行公开节点契约，不看最终评测答案；但它已经拥有解决这个算术任务族的能力。因此 tool_only 基线是必要对照，不能把修复效果宣称为一般路由或规划增益。Static 与 Local Repair 对相同输入共享初始回答，按各自实际应承担的逻辑用量比较成本；物理唯一调用另报。没有等预算无反馈重试组，所以不能把提升单独归因于反馈内容。
