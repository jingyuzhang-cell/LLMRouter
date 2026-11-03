# STAGE_D GLM 资源/端点审计（零调用，2026-11-02）

**决定**：选择 A——恢复原 Anthropic 兼容调用路径；192 继续 HOLD；不再发起诊断性真实调用；V1.3.2（A）、R1、冻结执行器 `b0d7a589`、统计方案全部不变。

## 一、已观测事实（仅来自配置与既有调用记录，无新增调用）

| providerId | key_last4 | 端点 | 观测结果 | 推断 |
|---|---|---|---|---|
| bigmodel-api（×4 重复） | FSAK | Anthropic `/api/anthropic/v1/messages` | 429 | 原路径不可用；套餐/额度/绑定待查 |
| bigmodel-api（×4 重复） | FSAK | 标准 `/api/paas/v4/chat/completions` | 429，code 1113："余额不足或无可用资源包,请充值" | 该 key 无标准 token 资源包 |
| bigmodel-api-5 | oXxW | Anthropic / 标准 | 429 / 429 | 无可用资源/限流 |
| bigmodel-api-6 | kOSw | 标准 `/api/paas/v4/chat/completions` | **200**（`glm-5.3-flash`，usage 正常） | 新套餐在此 key + 标准端点 |
| bigmodel-api-6 | kOSw | Anthropic | 400 | 该 key/套餐不支持 Anthropic 端点或模型映射不符 |
| bigmodel-standard-api | 60b3 | 标准 / Anthropic | 401（令牌已过期或验证不正确） | key 失效 |
| deepseek | f6fc | OpenAI 兼容 | **200** | DS 正常 |

**关键错误体**：标准端点对 `thinking: {"type":"disabled"}` 返回 **HTTP 400 / code 1210："该模型始终思考，不支持关闭思考；请使用 low、high 或 max。"**  
**结论**：`glm-5.3-flash` 标准端点是"始终推理"模型，**无法复现预注册 Anthropic 端点的 `thinking: disabled` 模式**；标准套餐与冻结协议不兼容。

## 二、对已有真实执行记录的定性

- 53 次 Anthropic 端点 429（`runs_final_real/`，3 个 S4）与 14 次标准端点调用（`runs_final_real_standard/`，1 个 S4，245.6s / 14 调用 / TP=0 / INCOMPLETE_DEADLINE）**全部为基础设施/端点不兼容诊断，不是科学样本**。
- 不能据此判定原 S4 基线失败；不得进入正式确认性统计。
- 记录保留、不删除；总调用远低于 2,688 / 9.5M / ¥34.56。

## 三、需要在智谱控制台核实的四项（不消耗模型调用）

1. **套餐类型与绑定**：5000 万 `glm-5.3-flash` + 1982 万 `glm-5.3` 资源包属于**标准 API token 包**，还是支持 Anthropic 兼容端点的订阅？绑定到哪个 API Key/账户？
2. **Anthropic 端点支持**：该套餐是否覆盖 `https://open.bigmodel.cn/api/anthropic/v1/messages`？若不覆盖，原 D2 路径需要哪种产品（订阅/Coding Plan/专用 Key）？
3. **FSAK 429 的真实原因**：是额度未恢复、套餐不覆盖该端点、账户资源包未绑定，还是并发/速率限制？该 key 是否为原 D2 使用的订阅 key？
4. **同账户合法 Key**：是否存在同时满足"Anthropic 端点 + 余额/套餐 + `thinking: disabled`"的 key；若有，更新 `provider_config.json` 或通过安全的运行时注入提供，**不要贴到对话里**。

## 四、恢复后的唯一受控预检（只 1 次，通过才启动 192）

一次调用，使用**原 transport + Anthropic 端点 + 正确 key**，同时断言：

1. HTTP 200；
2. `thinking: {"type":"disabled"}` 被接受且生效（响应无 reasoning 通道/时延符合 D2）；
3. 模型名与预注册 `glm53flash` 映射一致；
4. 输出合同（E/J1/J2/SINK JSON schema）可解析；
5. Token 与成本正确入账（不超单执行/全局预算）。

任一不满足 → 停止，不进入 192；不通过换 key/端点反复试错消耗资源。

## 五、明确不做

- 不修改 V1.3.2、R1、冻结执行器 `b0d7a589`、统计方案；
- 不把标准推理模型塞进冻结协议；
- 不把 53+14 次诊断记录混入正式样本；
- 不再发起真实调用，直到原路径资源权限核实并恢复。

**当前状态：192 HOLD；真实调用暂停；冻结 11/11、核心 19/19 原样保留。**
