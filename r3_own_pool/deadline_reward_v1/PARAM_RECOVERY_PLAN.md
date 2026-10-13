# 最小参数恢复对照实验 — 冻结方案（阶段四，只准备不执行）

状态：**NO-GO（等待操作员独立付费授权）**。算法开发已 GO 并完成（阶段一至三，
`CONTRACT_FAULT_VALIDATION.json` v2 ALL PASS）。本文档冻结的是唯一待真实执行的实验。

## 目的（裁决原文）

证明两件事：(1) 参数恢复确实能修好失败节点（机制修复有效性）；(2) DD 能比固定恢复
规则更聪明地选择何时使用它（调度增益）。本实验只做 (1)；(2) 在 (1) 的观测进入
ReplayWorld 后由四策略对照重放完成，零额外调用。

## 样本（操作员指定）

FE3（元道退，17 条可评 Silver 事实）+ FE4（舜天，4 条可评）。选这两条因为：
有可评质量集；FE3 是最长证据的中等长度（in 3,482 tok），FE4 是最长证据（in 6,322 tok）
——预算压力最极端的两个样本。FE1/FE2 无可评集合，不进入。

## 细胞矩阵（8 次调用，全部同提示词——SHA 与原始 FE 台账逐一相等）

| # | 模型 | θ（唯一变更） | 样本 | 检验假设 |
|---|---|---|---|---|
| 1-2 | GLM-5.3 | reasoning_effort=low, max_tokens=2048 | FE3, FE4 | 推理强度单独修复（预算不变） |
| 3-4 | GLM-5.3 | reasoning_effort=low, max_tokens=8192 | FE3, FE4 | 强度+预算联合 |
| 5-6 | GLM-5.3-Flash | reasoning_effort=low, max_tokens=8192 | FE3, FE4 | 家族复现 |
| 7-8 | deepseek-flash | thinking=disabled, max_tokens=2048 | FE3, FE4 | 思考通道单独修复（其余逐字节同 FE 契约） |

qwen-plus 不重跑（5/5 已观测，作参照）。GLM 不发送 thinking 字段（合法性表禁止）。
deepseek 不加 response_format（保持与 FE 契约逐字节一致以归因思考通道）。

## 资源上限（四项硬顶）

| 项 | 上限 | 依据 |
|---|---|---|
| 尝试次数 | 8（无重试，fail-stop） | 细胞数；首个意外错误即 INCOMPLETE 停止 |
| token | 120,000 | 最坏 39,216 in + 53,248 out 预留 ≈ 92.5K，余 30% |
| 现金 | ¥0.50 | GLM 订阅 ¥0；DS 最坏 ¥0.056（现实 ~¥0.025），≥8× 余量 |
| 墙钟 | 900s | 8 × FE 观测延迟上界 35s + 余量 |

## 成功判据（现在冻结，防事后挪门柱）

1. **格式修复**：严格 JSON（去围栏）∧ 非空 ∧（finish_reason=stop，GLM 无此字段时
   以 completion < 0.98×cap 替代）。
2. **质量修复（关键，防"JSON 合法即胜利"）**：Silver 召回（FE3 n=17 / FE4 n=4）必须
   **超过截断文本的诊断性下界**（GLM-5.3：FE3 41.2% / FE4 50.0%）才算质量收益；
   仅格式过而召回不超下界 → 记"格式修复、无质量收益"。同时对照 qwen 已观测值
   （FE3 35.3% / FE4 50.0%）。
3. **成本/时延**：逐细胞真实 token/现金/延迟入账；修复效用 = 质量收益 − 增量成本。
4. **失败判据**：细胞 finish 仍顶格或 JSON 仍无效 → 该 θ 修复标记 REFUTED，写入
   机制注册表（负结果同样入表）。

## 判据之后的分析（零调用）

8 个细胞观测进入 ReplayWorld 后重放四策略：若 θ 修复观测召回 > qwen 参照，DD 应
选择修复而非回退切换（对比 Fixed 的固定规则浪费）；若修复被 REFUTED，DD 应与
Fixed 同收敛于切换。两种结果都是有效证据。

## 执行器要求

- 逐细胞记录：model, theta, prompt_sha256(=FE 原始), finish_reason, completion_tokens,
  max_tokens, 答案全文, 现金(CNY), 延迟, 时间戳；
- fail-stop：首个意外错误写 INCOMPLETE 并停止（401 教训已两次验证）；
- 凭据：/root/.env.modelpool 优先；凭据不入日志；
- GLM 端点发送 reasoning_effort 参数前先以最小请求验证端点接受该参数（一次
  预检也计入 8 次上限之外单独授权，或直接作为细胞 1 的执行结果处理——建议后者，
  不增加调用）。

## GO/NO-GO

**当前 NO-GO**（裁决：新增付费模型实验 HOLD）。方案 GO-ready：授权即执行，
预计 8 次调用 / ≤92.5K token / ≤¥0.06 现实（≤¥0.50 上限）/ ≤900s。

## 可选追加（未冻结，需单独授权）

引用契约修复（Phase-4b）：qwen-plus × FE3/FE4 × 提示词显式声明 doc_id
（新 prompt SHA，独立于 FE 配对）——验证 contract_unverifiable 的修复假设。
2 次调用 / ~¥0.01。
