# A5 A′ 预注册修订 V2.1（请求协议修正；GO）

**状态：FROZEN / GO（仅修正请求协议与调用上限，不改科学设计）。**
**日期：2026-11-03。**
**上位文件**：`A5_PRIME_PREREGISTRATION_V2_DRAFT.md`（V2，sha `00ea8601…`）。
**修订范围**：**仅**请求参数、max_tokens、正式执行序列与预算口径；V4 仪器、旧/V3/评分器、提示词、E 冻结输出、B/C 配对、A5 规则全部不变。

---

## 一、触发事件

2026-11-03 按 V2 冻结协议执行 C0-P（真实 run3-SINK 提示词，max_tokens=4000）：

```
HTTP 400 / code 1210
"该模型始终思考，不支持关闭思考；请使用 low、high 或 max"
0.52s，0 token，request_id 2026110309244373b78f9ee13847d5
```

- 请求体使用了 `thinking={"type":"low"}`；
- 该请求未产生任何模型输出、未产生实验数据；
- 因此**不能据此否定 A5 结构假设**；这是一次请求协议错误，不是模型/额度失败。

---

## 二、修正后的请求协议（唯一变更）

| 项 | 旧（错误） | 新（修正） |
|---|---|---|
| thinking 字段 | `{"type":"low"}` | **不发送 thinking** |
| 推理档位 | 未正确传递 | **`reasoning_effort="low"`** |
| max_tokens | 4000 | **8192** |
| 模型 | GLM-5.3-Flash | 不变 |
| 端点 | `https://open.bigmodel.cn/api/anthropic/v1/messages` | 不变 |
| temperature | 0 | 不变 |
| system/user 划分 | 顶层 system + user | 不变（保持 prompt hash） |

依据（零调用，本地历史）：

1. `r3_own_pool/deadline_reward_v1/full_dag_executor.py` 的 GLM 分支构造 `reasoning_effort`，并 `assert 'thinking' not in body`；
2. `param_recovery` cells 7/8：GLM-5.3-Flash、`reasoning_effort=low`、`max_tokens=8192`、thinking=None → **2/2 end_turn**；
3. 178 条 GLM-5.3 `low@8192` 记录：**138 end_turn / 40 max_tokens**；GLM-5.3-Flash `low@8192` **3/3 end_turn**（小样本）；
4. low@2048：2/2 截断；low@4000：无本地记录。

**8192 已被本地真实调用接受，但不保证长提示词一定不截断。** 真实 SINK 调用是最终裁决；若 SINK 截断，停止，不提高到更高档位。

---

## 三、正式执行序列（formal 模式）

| # | 顺序 | 节点 | 调用 |
|---|---|---|---|
| 1 | C 先 | run1-C-J1 | 1 |
| 2 | C 先 | run1-C-J2 | 1 |
| 3 | C 先 | run1-C-SINK | 1 |
| 4 | B 后 | run1-B-J1 | 1 |
| 5 | B 后 | run1-B-J2 | 1 |
| 6 | B 后 | run1-B-SINK | 1 |
| 合计 | 一个完整 B/C 配对 | | **6** |

- C 先、B 后，与 run1 预登记随机化一致。
- 预算：已耗 14；失败 C0-P +1 = **15**；本次最多 6 次 → **累计上限 21/32**，不提高总上限。
- **失败位置说明**：C 臂 3 次先执行；若 B 臂后续失败，实际可能消耗 4–6 次，而非固定 3 次。总新增仍以 6 次为硬上限。
- 不再执行单独的 C0-P；首个 C-J1 验证 schema，run1-C-SINK 是真实验预算 sentinel。

---

## 四、执行纪律

1. `reasoning_effort="low"`，请求体不出现 `thinking`；
2. max_tokens=8192，不自动增加；
3. C 臂先执行，B 臂后执行；
4. 任意节点截断（`max_tokens`/`length`）、HTTP 错误（含 429/401/1210）、JSON 解析失败 → 立即停止；
5. 不重试、不换模型、不换端点、不修改提示词；
6. 保留全部原始响应、usage、耗时、请求记录；
7. V4 白名单在 GO 前冻结；**结果出来后不得追加**；
8. 失败现场 `runs_a5_planAPrime/c0p/C0P_SINK.json` 只读；新数据写入 `runs_a5_planAPrime_v2/`。

---

## 五、保持不变的科学设计

- V4 仅作并行仪器：sha `c3133267…`；旧合同 `f92090b0…`、V3 `ebca2492…`、评分器 `136b2e1b…`、A5 规则 `e25d9bf2…` 未改。
- B/C 唯一干预仍为 J1 的 `positions_relay`（154 字符）。
- E1P/E2P/E3/E4 冻结复用；J1 user、J2/SINK 模板两臂一致。
- 评分三口径并列：旧合同 / V3 / V4；A5 规则仅辅助。
- 3 次重复仍为先导；本次只有 1 个配对，**不作统计确认**。
- V4 分差 = 交付编码修正，**不称模型/调度能力提升**；Evidence 仅在 citation 合法时报告。

---

## 六、预注册预测（不变）

| # | 预测 |
|---|---|
| P1 | C 臂 J1 含 positions_relay 3/3；B 0/3 |
| P2 | A5 规则：B 0/3、C 3/3 |
| P3 | 旧/V3 官方 A5：两臂 0/6 |
| P4 | V4 A5 Fact：B 0/3；C 3/3 若命中白名单，否则如实报告新短语不可见 |
| P5 | V4 A5 Evidence：0–3/3，取决于 citation 是否合法 |
| P6 | 终端 Q_raw：若 V4 Fact 通过，约 +0.02；否则 0 |
| P7 | C 臂 token/时延 ≥ B |
| P8 | 8192 下 run1 C/B 零截断 |

---

## 七、修订记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| V2 | 2026-11-03 | 配对/随机化/C0/4000/V4 | DRAFT |
| **V2.1** | **2026-11-03** | **thinking→reasoning_effort；4000→8192；formal 6 次；跳过单独 C0-P** | **FROZEN / GO** |

**本修订只允许以下真实调用：`a5_aprime_runner_v2.py formal --go`，最多 6 次；其他模式/参数/端点一律不执行。**
