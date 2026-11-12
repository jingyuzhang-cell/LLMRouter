# CAL5 V2 执行失败与根因：GLM-5.3 思考强度未按预期降低（2026-11-11）

状态：**父节点阶段再次停止；测量 0 次；等待 GO V3（thinking 控制修正）**

## 一、发生了什么

V2 首次父调用 `CAL5_01B / fe`：

| 输入 token | 输出 token | finish | 正文 | 时延 |
|---|---|---|---|---|
| 1,670 | 8,000（封顶） | max_tokens | **0 字符** | 188.2 秒 |

父输出有效性闸门按设计触发，立即停止：未写父缓存、未进入 SETUP、测量 0 次。证据：`runs_v2/PARENT_INVALID_CAL5_01B_fe.json`、`calib_ledger_v2.jsonl`。

## 二、根因（官方文档确认）

1. GLM-5.3 / GLM-5.3-Flash **始终思考，不能关闭**；`thinking.type=disabled` 会报错 1210。
2. 走 **Anthropic 兼容端点**（`/api/anthropic/v1/messages`）时，思考强度由 **`thinking.type` + `output_config.effort`** 控制（low/high/max，默认 max）；`reasoning_effort` 不是该端点的有效控制项，`budget_tokens` 也被忽略。
3. V2 请求只发了 `reasoning_effort='low'`，被端点忽略 → 思考按默认 max 运行 → 8,000 token 全部耗在思考，正文为空。V1 的 3,000 上限下也是同一原因（fe 0 字符）。

官方文档：
- https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3
- https://docs.bigmodel.cn/cn/guide/capabilities/thinking

## 三、拟采用的修正（最小改动）

在 Anthropic 请求体中增加：

```json
"thinking": {"type": "enabled"},
"output_config": {"effort": "low"}
```

保留 `reasoning_effort: "low"`（兼容），但有效控制项是 `output_config.effort`。不改提示词、任务、输入、注入值、评分；仅传输参数与校准器 SHA 变化。

## 四、预算

| 项 | 次数 |
|---|---|
| V1 已用（2 完成 + 1 中止） | 3 |
| V2 已用（fe 失败，闸门停止） | 1 |
| 剩余有效调用（15 父 + 30 测量） | 45 |
| **累计请求上限（申请）** | **49** |

token 已用约 17.4K（V1 7,751 + V2 9,670）；V3 上限仍为 300K、¥0.30 记账；按 0.6 token/字符预估 45 次有效调用约 269K，留约 14K 余量。若 effort=low 后思考仍过长，闸门会再次停止，不会烧完预算。

## 五、未受影响

- 5 个任务、12 条 Gold 事实、固定输入规则（D1 全文 / D2 前 4,000 字符）、注入候选、评分规则均未改；
- 测量 0 次，无机制结论；
- 正式 52 任务实验未启动。
