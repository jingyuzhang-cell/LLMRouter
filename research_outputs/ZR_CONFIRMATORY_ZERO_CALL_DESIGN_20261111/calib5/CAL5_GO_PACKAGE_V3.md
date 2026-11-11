# CAL5 GO V3（thinking 控制修正；零调用，等待操作员批准）

状态：**AWAITING_OPERATOR_GO_V3**　基线：V2 已按 GO 执行，但父节点第一次调用即被有效性闸门拦下。

## 1. 为什么需要 V3

V2 的 `CAL5_01B/fe`：输入 1,670 token，输出 8,000 token（封顶），finish=max_tokens，正文 0 字符，188 秒。闸门按设计停止，测量 0 次。

官方文档确认：**GLM-5.3 / GLM-5.3-Flash 始终思考，不能关闭**（`thinking.type=disabled` 报错 1210）；Anthropic 兼容端点的思考强度由 **`thinking.type` + `output_config.effort`** 控制（low/high/max，默认 **max**），`reasoning_effort` 在该端点不是有效控制项。V2 只发了 `reasoning_effort='low'`，被忽略 → 默认 max 思考吃满 8,000 token。

- https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3
- https://docs.bigmodel.cn/cn/guide/capabilities/thinking

## 2. V3 唯一改动（传输层）

在 Anthropic 请求体中增加：

```json
"thinking": {"type": "enabled"},
"output_config": {"effort": "low"}
```

保留 `reasoning_effort: "low"` 作为兼容字段。**提示词、任务集、输入规则、Gold、注入值、评分规则全部不变。**

## 3. 预算

| 项 | 次数 |
|---|---|
| V1 已用（2 完成 + 1 中止） | 3 |
| V2 已用（fe 失败，闸门停止） | 1 |
| 剩余有效调用 | 45（15 父 + 30 测量） |
| **累计请求上限（申请）** | **49** |

token 已用约 17.4K；V3 仍为 300K token / ¥0.30 记账上限；按 0.6 token/字符估计 45 次有效调用约 269K，余量约 14K。若 `effort=low` 后仍被思考吃满，闸门会再次停止，不会烧完预算。

## 4. 冻结 SHA

| 资产 | SHA256 |
|---|---|
| 任务集 V2（未改） | `52f702c0fd62d534…` |
| 提示词（未改） | `f2b13bc09059f437…` |
| 校准器 V3 | `446ae7bb9d1ffb9b…` |
| 判定器 | `901a2271a001219e…` |

V2 校准器 `a3929d60…` 保留审计，不再使用。

## 5. 零调用检查

- V3 自测通过：10 个配对单元全链路、5 任务注入选择与 loc/ver/xc 评分逐任务断言、父输出闸门单元测试；
- 任务输入、事实跨度、注入错误值检查与 V2 完全一致（未改任务集/输入）；
- 唯一差异是请求体中的 thinking 控制字段。

## 6. 批准后的执行顺序

1. 15 次父节点生成（有效性闸门开启）；
2. 逐任务 SETUP 检查：目标事实必须同时出现在 tl 与 er；
3. 全部通过后 30 次测量；
4. 按冻结判据出报告：Z1 ≥8/10；Z0 ≤6/10 且至少一个任务两次重复均失败；Z0 ≥7/10 停止确认性实验；异常 >2 次不结论。

任一闸门失败：停止并报告，不替换任务、不改提示词、不人工补父输出、不缩小分母。

## 7. 不在本 GO 内

正式 52 任务实验、36 个正式任务补采、π/L 实验；校准结果不构成 Z×R 效应证据。
