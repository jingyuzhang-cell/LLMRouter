# MODEL_INTEGRATION_TEST_V1_RESULT — 6 次结构化输出与长度预检（已授权执行）

授权执行：≤6 次 / ≤15K token / ≤¥0.25。实际消耗：**6 次调用，累计 7,180 token，现金 ≈¥0.00953**——
远低于全部上限。GLM 不测（生产已验证）。

## 结果总表

| 测试项 | deepseek-flash | qwen-plus | 说明 |
|---|---|---|---|
| **T1 JSON 契约**（2,048 上限） | **PASS**（9 facts，stop=stop） | **PASS**（9 facts，stop=stop） | 两模型首试即产出合法 facts JSON——契约能力初步确认 |
| **T2 长输出**（目标 30-40 条） | **TRUNCATED**（stop=length，输出满 2,048） | **PASS**（39 facts，1,895 tok，stop=stop） | **deepseek-flash 在 2,048 上限内无法完成 30-40 条富提取**——输出比 qwen 冗长（推理过程占大量输出） |
| **T3 截断恢复**（256 上限故意截断） | **FAIL**（截断确认，但 JSON 打捞失败——reasoning 破坏结构） | **PASS**（4 facts 打捞成功） | deepseek 的推理输出使截断后 JSON 不可程序恢复 |

## 逐调用计量

| # | 模型 | 测试 | in | out | stop | 时延 | 费用 |
|---|---|---|---|---|---|---|---|
| 1 | deepseek-flash | json_contract | 225 | 1,081 | stop | 5.46s | ¥0.00136 |
| 2 | deepseek-flash | long_extraction | 252 | 2,048 | **length** | 19.33s | ¥0.00253 |
| 3 | deepseek-flash | truncation_recovery | 252 | 256 | **length** | 2.29s | ¥0.00038 |
| 4 | qwen-plus | json_contract | 225 | 178 | stop | 4.32s | ¥0.00054 |
| 5 | qwen-plus | long_extraction | 256 | 1,895 | stop | 42.09s | ¥0.00399 |
| 6 | qwen-plus | truncation_recovery | 256 | 256 | **length** | 8.41s | ¥0.00072 |

## 发现（如实）

1. **两模型 JSON 契约首试通过**——连通性问题已解决，格式能力初步确认。
2. **deepseek-flash 的关键问题：输出密度**——同一任务 qwen 用 1,895 tok 完成 39 条，
   deepseek 2,048 tok 仍未完成（推理过程冗长）。**筛选前必须为其调整契约**
   （减少目标条数至 ~15-20，或改用非思考模式），否则 80 次筛选将重蹈截断覆辙。
3. **qwen-plus 表现全面**：契约/长输出/打捞三测全过，时延最长（42s 富输出）但完整。
4. **成本信号**：deepseek-flash 输出单价高（$1.20/M 峰值）——同等输出量成本约为 qwen 的
   4-5 倍（qwen ¥2/M 出），但输入端 deepseek 便宜（$0.30 谷 vs ¥0.8）。**成本结构互补的初步证据**。

## 对 80 次筛选的前置条件

1. deepseek-flash：调整契约（目标 15-20 条 或 禁用思考/缩减 quote 要求）→ 单模型 1 次验证
   （≤1K token，待授权）；
2. qwen-plus：就绪，可直接入筛选；
3. glm-5.3 / glm-5.3-flash：就绪（生产验证过）；
4. 筛选协议 V2 冻结版不变。

## HOLD 恢复声明
付费 HOLD 已恢复。未运行 80 次筛选或任何 DAG 实验；未推送 GitHub。
