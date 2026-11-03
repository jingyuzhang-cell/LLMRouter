# MODEL_CONNECTIVITY_TEST_RESULT — 三模型连通性测试（第 2 轮，全部通过）

授权执行（第 2 轮）：≤3 次 / ≤5,000 token / ≤¥0.50 / 输出上限 32 / 失败不重试。
实际消耗：**3 次调用，累计 97 token，现金 ≈¥0.0004**。

## 预检（全部通过，密钥材料零输出）
- `/root/.env.modelpool` 存在、权限 600 ✓
- 三个变量（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / ZHIPUAI_API_KEY）均非空 ✓
- 环境加载正常 ✓
- GLM 按指令**沿用既有订阅通道**（pilot_common anthropic 兼容端点），未改认证方式 ✓
- 端点/模型 ID 与 THIRD_FAMILY_PROVIDER_AUDIT_V2.md 一致 ✓

## 结果表

| 模型 | 状态 | HTTP | 实际返回 ID | 响应内容 | in tok | out tok | 墙钟时延 | 费用 |
|---|---|---|---|---|---|---|---|---|
| glm-5.3 | **PASS** | 200 | GLM-5.3 | "OK" | 18 | 3 | 1.74s | 订阅 0 增量现金 |
| deepseek-flash | **PASS** | 200 | deepseek-flash | "好的" | 34 | 29 | 0.79s | ≈¥0.0003 |
| qwen-plus | **PASS** | 200 | qwen-plus | "OK" | 12 | 1 | 0.33s | ≈¥0.00001 |

**3/3 PASS——三家族全部打通。**

## 逐项记录
- HTTP 状态：全部 200（无认证/限流/模型不存在错误）。
- 实际模型 ID：glm-5.3→"GLM-5.3"；deepseek-flash→"deepseek-flash"；qwen-plus→"qwen-plus"。
- 输入/输出 Token：34/97 合计（远低于 5,000 上限）。
- 时延：qwen-plus 0.33s < deepseek-flash 0.79s < glm-5.3 1.74s（单次测量，非统计结论）。
- 费用：现金合计 ≈¥0.0004（远低于 ¥0.50 上限）；GLM 订阅内不产生增量现金。
- 错误：无认证、限流或模型不存在错误。

## HOLD 恢复声明
付费 HOLD 已恢复。未运行 JSON 契约测试、长输出测试、节点级筛选或任何 DAG 实验；
未推送 GitHub；历史冻结结果未改动。
