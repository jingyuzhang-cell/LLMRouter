# DD_V74_PREADMISSION — n5 最小真实配对预执行审计（2026-10-30，零调用）

> 按 operator 裁决：仅针对 D_r1 n5 状态的两种物理动作，重新精确计算
> 最小请求数，核查全部硬门槛。零模型调用，不执行。

## 一、实验对象（固定）

| 项 | 值 |
|---|---|
| DAG | D_r1 原始 Planner 10 节点（指纹 f34478ebbad5） |
| 故障 | n5（penalties 节点，传输级故障注入） |
| Z | IDENTITY（两动作相同） |
| R | {n5}（两动作相同） |
| **Action A（Alternating）** | n6=**flash**, n7=**flash** |
| **Action B（Interaction Block）** | n6=**glm53**, n7=**glm53** |
| 其余全部节点 | 相同模型分配 |

## 二、精确调用数（经 DAG 依赖传播分析）

| 节点 | 调用数 | 共享原因 |
|---|---|---|
| n1-n4（前缀） | **1×4=4** | 故障前共享，全动作全重复 |
| n5（故障重执行） | **2** | 同模型但需独立采样×2重复 |
| n6（entity_graph） | **4** | 2模型×2重复（动作差异点） |
| n7（timeline_deep） | **4** | 2模型×2重复（动作差异点+输入变） |
| n8（amounts_check） | **1** | 仅依赖n4，跨动作跨重复共享 |
| n9（cross_check） | **4** | 输入因n7变化×2重复 |
| n10（synthesis） | **4** | 输入因n9变化×2重复 |
| **总计** | **23** | |

Token 估算：~25,200（按冻结账本各角色均值）

## 三、硬门槛核查

| 门槛 | 状态 | 详情 |
|---|---|---|
| n6 PROXY 风险 | **NOTED** | entity_graph 无实测——本轮同时收集校准数据，不预设优劣 |
| n7 有实测 | PASS | timeline_deep→timeline 类型有冻结测量 |
| 独立 Silver 评分 | READY | 文档锚定评分器可用 |
| 评分器隔离 | PASS | gold/ 不在运行时路径 |
| 共享/非共享正确性 | PASS | n8 仅依赖 n4→可共享；n6/n7/n9/n10 因模型或输入变化→不可共享 |
| 重复独立性 | PASS | purpose 标签含 rep 编号，不触发 dedup |
| 现金硬顶 ¥0 | PASS | 无按量模型；订阅费率需执行时确认 |
| DAG 结构完整性 | PASS | 指纹 f34478eb，无模板转换 |
| 合同执行 | PASS | 全部角色有 build_prompt 支持 |
| 故障注入 | PASS | n5 真实调用后替换为 garbage |

## 四、主终点

**ΔQ = Q(Action B) − Q(Action A)**

- 正值 → 联合块模型分配有真实质量收益
- 零 → 预测层优势未转化（可能因 PROXY 参数不准）
- 负值 → 联合升级过度分配

次终点：真实 Makespan、Token 消耗、合同通过率。
n6（PROXY）的节点级输出将单独保存供校准分析。

## 五、明确限制

1. **仅验证 π 块优化**——Z 和 R 维度为空
2. **2 次重复 = 探索性**——不宣称统计显著
3. **两个节点同时换模**——不能分别归因 n6 和 n7 的贡献
4. **单一 DAG 单一故障点**——不宣称跨任务泛化

## 六、授权申请（七字段）

```
batch_name: dd_v74_n5_paired
max_calls: 23
max_tokens: 35000  (25200 估计 + 39% 余量)
models: [glm53, glm53flash]
per_model_quota: {glm53: 20000, glm53flash: 15000}
tasks: [D_r1-n5-paired]
issued_by: operator
created: 2026-10-30
provenance: "operator DD-V7.4 pre-admission audit PASS"
```

**等待操作者完整字段授权。付费 HOLD 维持。**
