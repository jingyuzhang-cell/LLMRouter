# G2 逐节点审计：π 作用域与依赖失效

**性质**：离线 Mock（`simulated=true`），非真实模型结果。

## S1（异常节点 = E2，臂 = Joint）

- dag_version: 1；calls: 9；stop: completed
- 最终 U（R₀ 与 Z 之后重算）: `['E2_pos', 'E2_rest', 'E3', 'E4', 'J1', 'J2', 'SINK']`
- pi_scope: `['E2_pos', 'E2_rest', 'E3', 'E4', 'J1', 'J2', 'SINK']`

| 节点 | init | detect | R₀ 后 | Z 后 | 进入 U | 进入 π | 未进入 U 的原因 |
|---|---|---|---|---|---|---|---|
| E1 | PENDING | COMPLETED | COMPLETED | COMPLETED | ✗ | ✗ | completed before anomaly |
| E2 | PENDING | COMPLETED | READY | DELETED | ✗ | ✗ | deleted by Z (topology changed) |
| E2_pos | — | — | — | PENDING | ✓ | ✓ |  |
| E2_rest | — | — | — | PENDING | ✓ | ✓ |  |
| E2_merge | — | — | — | PENDING | ✗ | ✗ | code node (no model) |
| J1 | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |
| J2 | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |
| SINK | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |

- 后代 J1/J2/SINK 最终状态: [('J1', 'COMPLETED'), ('J2', 'COMPLETED'), ('SINK', 'COMPLETED')]
- 异常节点: ('E2', 'E2_pos', 'E2_rest', 'E2_merge') 状态: {'E2': 'DELETED', 'E2_pos': 'COMPLETED', 'E2_rest': 'COMPLETED', 'E2_merge': 'COMPLETED'}

## S1b（异常节点 = E1，臂 = Joint）

- dag_version: 1；calls: 9；stop: completed
- 最终 U（R₀ 与 Z 之后重算）: `['E1_pos', 'E1_rest', 'E2', 'E3', 'E4', 'J1', 'J2', 'SINK']`
- pi_scope: `['E1_pos', 'E1_rest', 'E2', 'E3', 'E4', 'J1', 'J2', 'SINK']`

| 节点 | init | detect | R₀ 后 | Z 后 | 进入 U | 进入 π | 未进入 U 的原因 |
|---|---|---|---|---|---|---|---|
| E1 | PENDING | COMPLETED | READY | DELETED | ✗ | ✗ | deleted by Z (topology changed) |
| E2 | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |
| E1_pos | — | — | — | PENDING | ✓ | ✓ |  |
| E1_rest | — | — | — | PENDING | ✓ | ✓ |  |
| E1_merge | — | — | — | PENDING | ✗ | ✗ | code node (no model) |
| J1 | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |
| J2 | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |
| SINK | PENDING | PENDING | PENDING | PENDING | ✓ | ✓ |  |

- 后代 J1/J2/SINK 最终状态: [('J1', 'COMPLETED'), ('J2', 'COMPLETED'), ('SINK', 'COMPLETED')]
- 异常节点: ('E1', 'E1_pos', 'E1_rest', 'E1_merge') 状态: {'E1': 'DELETED', 'E1_pos': 'COMPLETED', 'E1_rest': 'COMPLETED', 'E1_merge': 'COMPLETED'}

## Running 节点保护

- `compute_U` 仅接受 `PENDING`/`READY`；`RUNNING` 永不进入 U。
- 在本实验的 S1/S1b/S4′ 中，异常检测发生在节点调用返回之后（同步），
  而异常节点的后代因依赖门控**尚未派发**（J1 需 E1,E2 均 Completed），
  因此**不存在 Running 后代**；该情形由单元测试 U-RUNNING 覆盖。
- 若运行时真的观察到 Running 后代，引擎**不发明语义**：其上游版本变化会导致结果过期，
  本方案**不定义**过期结果处理，标记为 BLOCKED 待裁定（见报告 §未解决）。
