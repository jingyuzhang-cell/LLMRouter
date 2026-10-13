# 故障感知参数恢复 — 本轮交付总览（裁决四阶段全部完成）

裁决依据：2026-10-13 操作员裁决（算法开发 GO / 付费实验 HOLD）。本轮零真实模型调用。
验证：`CONTRACT_FAULT_VALIDATION.json` v2 **ALL PASS**。

## 交付 1：故障分类与动作支持表

**六类故障**（`contract_fault.py` v2，识别与动作分离）：

| 类型 | 签名 | 真实样本 |
|---|---|---|
| F_TRUNCATED | finish∈{length,max_tokens} 或 completion≥98%×cap | GLM 10 条（3 空变体）+ deepseek 5 条（全部空，finish=length） |
| F_EMPTY_RESPONSE | 空可见输出 ∧ 自然停止 | ——（GLM/DS 的空响应全部归入截断空变体） |
| F_JSON_INVALID | 自然停止 ∧ 解析失败 | 历史 TL5/qwen、ER3/glm-flash |
| F_EVIDENCE_CITATION | JSON 合法 ∧ 引用∉期望集 | qwen FE 5/5；**新发现：台账 doc_id 从未入提示词 → cause=contract_unverifiable（契约设计缺陷，非模型过错）** |
| F_MODEL_UNAVAILABLE | 传输/5xx/超时 | ——（无真实样本，类型在册） |
| F_PRE_DISPATCH | 客户端错误（代码/凭据/构造） | ModuleNotFoundError×10、401×2（两次 fail-stop 审计记录） |

诊断维度：finish_reason、completion/max 比值、可见输出长度、引用可满足性。
分类器在 **100 条真实记录上 100% 准确**（真值构成：66 OK / 15 F_TRUNCATED /
12 F_PRE_DISPATCH / 5 F_CITATION / 2 F_JSON_INVALID）。

**θ 动作支持表**（`theta_actions.py`，裁决合法性硬约束）：

| 模型 | reasoning_effort | thinking=disabled | max_tokens | 真实先验 |
|---|---|---|---|---|
| GLM-5.3 / Flash | low/high/max ✓ | **禁止** | ≤65536 | 默认 θ 下 0/15（FE） |
| deepseek-flash | 无此参数 | ✓ | ≤8192 | disabled+json_object 下 17/17 合法（历史，**仅作先验**——提示词不同） |
| qwen-plus | 无此参数 | ✓（默认即关） | ≤8192 | 5/5 格式通过（FE） |

枚举器内嵌合法性断言：任何模型都不会收到不支持的组合（验证 Part 2 全绿）。

## 交付 2：DD-Enhanced 实现及零调用验证（a = Z,R,π,θ）

`recovery_strategies.py`：联合动作扩展为 **(Z, R, π, θ)**——Z=恢复范围（含 M5 闭包
规则：R ⊇ 失败节点 ∪ 已执行下游）、π=模型、θ=合法执行参数。DD 候选评估免费
（台账查询/先验），仅被执行动作计费；参数变更按全额预留计入预算。

零调用重放结果（`FOUR_STRATEGY_REPLAY.json`，质量信用只来自真实观测）：

| 策略 | 质量 | 尝试 | token | 未观测动作 |
|---|---|---|---|---|
| SS-Original | 0.000（真实失败重放） | 5 | 26,821 | 0 |
| SS-Tuned | 0.000（θ 调优全部未观测，零信用） | 5 | 53,987 | 5 |
| Fixed-Recovery | 1.853 | 15 | 72,352 | 5（盲重试浪费） |
| **DD-Enhanced** | **1.853** | **10** | **49,085** | **0** |

机制演示：DD 利用认识状态（观测/未观测）**用 10 次尝试达到 Fixed 15 次的同等质量**
——省下 5 次盲目未观测重试。这是"DD 比固定规则聪明"的机制性证据；质量增益的
最终证明需阶段四真实参数观测（若 GLM+low 修复召回超过 qwen 参照，DD 将选择修复
而非回退切换，届时质量差显现）。

诚实性硬规则：UNOBSERVED 结果零质量信用（验证 Part 3：违规 0）；历史不同提示词
的调用只作先验、绝不结算为 FE 质量。

## 交付 3：四策略公平对照协议

共享：同一模型池 / 同一 θ 合法性表 / 同一预算守卫 / 同一评分器 / 同一计划模型
（GLM-5.3）。SS-Tuned 消除"故意保留 SS 错误配置制造 DD 收益"的混淆（裁决 Phase 2
要求）；Fixed-Recovery 规则**事先冻结**（先盲重试同模型首个合法 θ 修复，失败切
qwen）；DD 基于运行时故障反馈决策。闭包/预算/审计断言内嵌执行路径。

## 交付 4：最小真实参数实验冻结 + GO/NO-GO

`PARAM_RECOVERY_FREEZE.json`（sha 51818835…）+ `PARAM_RECOVERY_PLAN.md`：
8 细胞（GLM-5.3×{low@2048, low@8192}、Flash×{low@8192}、deepseek×{disabled@2048}
× FE3/FE4），同提示词 SHA 配对，上限 8 尝试/120K tok/¥0.50/900s，fail-stop，
**质量判据预先冻结**：召回必须超过截断文本诊断下界（FE3 41.2%/FE4 50.0%）才算
质量收益——防止"JSON 合法即宣布 DD 获益"。

**GO/NO-GO：NO-GO（HOLD 遵守）。** 授权即执行，预计现实成本 ≤¥0.06。

## 更正记录（裁决要求）

- FE_PAIRED_REPORT.md / GLM_FE_QUALITY_ANALYSIS.md 已追加更正节：根因表述收紧
  （参数配置是高度可疑的共同原因，修复效果待同模型对照）；qwen 5/5 仅格式层成立
  （引用层 5/5 契约不可满足）；四件事（质量/契约/推理模式/模型身份）分离评价。

## 文件清单

| 文件 | 内容 |
|---|---|
| theta_actions.py | θ 支持表 + 合法性 + 修复阶梯 + 预算预留 + 真实先验锚点 |
| contract_fault.py | 六类故障分类 + 引用可满足性 + 机制注册表 + 合法恢复动作 |
| recovery_strategies.py | 四策略 + ReplayWorld + 共享预算/评分器 + 闭包规则 |
| contract_fault_validation.py | 阶段三验证（100 记录 + 合法性 + 诚实性 + S1-S4） |
| CONTRACT_FAULT_VALIDATION.json | v2 ALL PASS 记录 |
| FOUR_STRATEGY_REPLAY.json | 四策略重放结果 |
| PARAM_RECOVERY_FREEZE.json / PLAN.md | 阶段四冻结方案（NO-GO 待授权） |
