# D-contract 故障类：FE 发现 → 可执行机制（零调用）

状态：**已实现并通过 88 条真实调用的零调用验证**（`CONTRACT_FAULT_VALIDATION.json`，accuracy 100%，ALL PASS）。
上游证据：`FE_PAIRED_REPORT.md`（20 次同提示词配对真实调用）。

## 机制内容

代码：`contract_fault.py`（分类器 + 机制注册表 + 参数修正型恢复动作空间 + 故障定向决策规则）；验证：`contract_fault_validation.py`。

### 1. 故障签名分类（仅用可观测信号）

| 类别 | 签名 | 语义 |
|---|---|---|
| `D_CONTRACT` | `finish_reason ∈ {length, max_tokens}`，或 `completion_tokens ≥ 0.98×cap ∧ 解析失败` | 思考型模型的思考 token 与可见输出共享预算，紧输出契约下被切断（GLM 端点未回传 finish_reason 时由顶格签名兜底——FE 实证 10/10 恰好=2048） |
| `D_CONTENT` | 自然停止（stop/end_turn）∧ 解析失败 | 能力/格式问题，与预算无关 |
| `OK` | 解析成功 | 无故障 |

### 2. 机制注册表（证据绑定，2026-10-13）

GLM-5.3 / GLM-5.3-Flash / deepseek-flash：`thinking_default=True`，2048 JSON 契约下通过率 **0/15**（FE 实测）；qwen-plus：直接输出型，**5/5**。deepseek-flash 的 5/5 空响应（思考吃光预算、零可见输出）是最极端证据。

### 3. 恢复动作空间扩展：π(n) = (model, call_params)

`R` 的动作不再只有换模型——`PARAM_FIX`（同模型修契约：max_tokens×4 / thinking=disabled / 两者）与 `MODEL_SWITCH`（换模型保契约）、`MODEL_SWITCH_PARAMS`（组合）并列。

### 4. 故障定向决策规则

- **D_CONTRACT → PARAM_FIX 优先**：换到另一个思考型模型只会复购同样失败（FE 实测：deepseek 侧 ¥0.1220 买了 5 条空响应）。盲切换陷阱在动作列表中显式可见：GLM→deepseek-flash 的切换项携带 `contract_pass_prior=0.0` 且必须附带组合修复项。
- **D_CONTENT → MODEL_SWITCH 优先**（按已知契约通过率排序）；无切换目标时回退参数修复。

### 5. 验证结果（零调用）

- 分类器：88 条真实调用（FE 原始 10 + FE 恢复 10 + 历史 68）**100% 准确，0 误判**；真值构成 D_CONTRACT 15 / D_CONTENT 2 / OK 71。历史 68 条全部自然停止（0 契约故障）构成干净负样本；2 条 json_valid=false 且低完成数（118/152 tok）正确判为 D_CONTENT 而非 D_CONTRACT。
- 决策场景：S1 GLM 顶格截断→PARAM_FIX（不换模型）✓；S2 qwen 自然停垃圾→MODEL_SWITCH ✓；S3 deepseek 空响应 length-cut→PARAM_FIX 且 thinking=disabled 修复在列 ✓；盲切换陷阱结构可见 ✓。

## 对主研究（feedback-aware DAG scheduling）的接入点

1. 故障分类学：D1–D6 之外新增 D_CONTRACT（CapitalEvent 轨道已实现；TAT-QA 轨道 e/r/v 节点的输出短，未观察到该类，但机制通用）。
2. 联合动作 a_t=(Z,R,π)：π 的维度从"模型选择"扩展为"模型 × 调用参数"，恢复集 R 增加"带参数修正的重执行"。
3. 质量先验：completion/max 比值与 finish_reason 进入质量信念输入（机制特征，不只是解析成败）。
4. 成本先验：思考型 × 紧输出预算组合在约束过滤阶段即标记低通过率（本批实证 0/15）。

## 待操作员裁决的后续（均需 GO，未执行）

- PARAM_FIX 的真实有效性验证：同一 FE 提示词 × thinking=disabled / max_tokens=8192 的对照调用（预计 ≤20 次、≤¥0.5）——验证"调参数确实能救回"这一决策规则的核心假设。
- 接入 DD-V2 候选枚举（`reassign.enumerate_candidates`）与 CapitalEvent 执行器。
