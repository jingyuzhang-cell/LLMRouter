# SCREENING_READINESS_REPORT — CapitalEvent 节点筛选就绪状态

四项交付完成（`d6554ac`，零调用）。剩余阻塞点如下。

## 已交付

| # | 交付物 | 状态 |
|---|---|---|
| 1 | [CAPITAL_EVENT_NODE_SCREENING_FREEZE](deadline_reward_v1/CAPITAL_EVENT_NODE_SCREENING_FREEZE.json) | **完成** — 20 真实输入 × 4 类型 × 4 模型 = 80 计划调用；5 个真实事件；TAT-QA 面板保留未覆盖 |
| 2 | [HISTORICAL_NODE_CAPABILITY_MATRIX](deadline_reward_v1/HISTORICAL_NODE_CAPABILITY_MATRIX.json) | **完成** — 180 查询 × 6 本地槽；可比性判断：**不可比**（英文 MCQ/数学/代码 vs 中文金融文档）；互补性已算 |
| 3 | [GLM_REAL_COST_ANALYSIS](deadline_reward_v1/GLM_REAL_COST_ANALYSIS.json) | **完成** — 147 真实云端调用 tokens/时延；费率 UNKNOWN（台账无逐调用费用，不可反推） |
| 4 | 数据边界声明 | **完成** — TAT-QA e1/e2/r/v ≠ CapitalEvent 四类型；独立面板互不覆盖 |

## 剩余阻塞点

| 阻塞项 | 阻塞什么 | 需要什么 |
|---|---|---|
| **DeepSeek + Qwen 云端 model_id 与费率** | M3/M4 的 40 次调用 | 独立核实具体版本、价格、访问凭据 |
| **GLM 官方按量价格** | 现金费用核算 | 智谱 API 定价表（当前 UNKNOWN） |
| **元道退双人标注** | Gold 从 SILVER 升为 GOLD | 40 候选的两人独立审核（模板已有） |
| **操作员准备包 ZIP** | 工具合并 | 上传至 AutoDL `/root/r3_own_pool/deadline_reward_v1/offline_prep_operator/` |
| **本地 GPU** | Qwen 本地 + 嵌入检索 | GPU 硬件恢复（扩展候选，非筛选必需） |

## 关键发现

1. **可比性结论**：180 条历史筛选（本地模型 × 英文 MCQ/数学/代码）与 CapitalEvent 节点（云端模型 × 中文金融监管文档）**不直接可比**。历史数据只能作为模型池内部相对排序参考，不可冒充 CapitalEvent 节点的实测能力先验。**80 次云端筛选是必要投资，不可跳过。**

2. **GLM 费用现状**：147 次真实云端调用的 token 数和时延完整，但台账**未记录逐调用费用**。无法从总量反推 input/output 单价（操作员预判正确）。需要官方费率表 + 订阅状态确认。

3. **Gold 状态**：全部 20 输入为 SILVER_AUTO_VERIFIED（自动验证 + 跨模型 AI 交叉检查），零人工金标。元道退有 40 候选标注包但双人独立审核未执行——**不能自动升为 GOLD**。
