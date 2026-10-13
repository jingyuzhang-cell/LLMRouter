# FE 配对筛选最终报告：4 模型 × FE1–FE5（20 次真实调用，同提示词配对）

原始运行：`fe_screening_runs/fe_20261013_211741`（GLM 10 条 delivered；已标记 INCOMPLETE）
恢复运行：`fe_screening_runs/fe_recovery_20261013_213713`（DS/Qwen 10 条 delivered，COMPLETE）
配对保证：逐样本 prompt SHA256 与原始运行台账逐一相等（恢复执行器 gate 断言通过）。
契约：完全相同的请求体——同提示词、`max_tokens=2048`、`temperature=0.0`，无 thinking 控制、无 response_format（四模型同契约）。

## 1. 配对质量矩阵（20 格全满）

格式层（严格 JSON，去 Markdown 围栏后解析）：

| 模型 | 严格JSON | finish_reason | 机制 |
|---|---|---|---|
| GLM-5.3 | **0/5** | （未记录；token 全顶格） | 思考+输出合计撞 2048：4 条截断半文、1 条空 |
| GLM-5.3-Flash | **0/5** | （未记录；token 全顶格） | 同上：3 条截断半文、2 条空 |
| deepseek-flash | **0/5** | **length 5/5** | **5 条全部空响应**：思考吃光 2048 token，零可见输出 |
| qwen-plus | **5/5** | **stop 5/5** | 直接输出，自然收束（339–1372 tok，全部低于上限） |

Silver 召回（仅 FE3/4/5 可评；FE1/FE2 = NA；截断文本的召回为诊断性下界）：

| 样本(可评数) | GLM-5.3 | GLM-5.3-Flash | deepseek-flash | qwen-plus |
|---|---|---|---|---|
| FE3 (17) | 7/17=41.2%* | 9/17=52.9%* | 0/17（空） | **6/17=35.3%（完整输出）** |
| FE4 (4) | 2/4=50.0%* | 0/4（空） | 0/4（空） | **2/4=50.0%（完整输出）** |
| FE5 (1) | 1/1* | 1/1* | 0/1（空） | **1/1（完整输出）** |

\* 来自被截断文本的诊断性抽取（下界，非能力结论）。qwen 是唯一基于完整合法 JSON 的可评召回。

## 2. 核心发现：失败机制是"思考型模型 × 输出契约"错配，跨厂商可复现

三个思考默认开启的模型（GLM-5.3、GLM-5.3-Flash、deepseek-flash）**15/15 全部撞 2048 上限**，completion_tokens 全部顶格（2047–2048）；唯一直接输出型 qwen-plus **5/5 自然停止**。deepseek-flash 最极端：5/5 空响应——思考阶段独占全部输出预算，连一个可见字符都不剩。

**结论：在 max_tokens=2048 的 JSON 事实抽取契约下，节点执行失败由模型机制（思考 token 与输出 token 共享预算）决定，与厂商无关，与事实抽取能力无关。** 这正是操作员预判的"输出长度与格式契约不匹配导致节点执行失败"的跨厂商实证。

## 3. 互补性分析

- **格式能力与抽取能力解耦**：qwen 格式 100% 但 FE3 召回 35.3%，低于 GLM 截断文本的诊断召回（41–53%）——GLM 可能抽取更多，但输出不可解析，对下游节点等价于零产出。
- **真实互补轴不是"能力高/低"而是"契约相容/不相容"**：思考型模型在这个契约下产出的信息（截断文本里确实有 9–33 条事实片段）无法被下游 v/解析节点消费；直接输出型可以。对 DAG 而言，前者的失败是**可检测的**（finish_reason=length / completion_tokens=max / 空 content），后者根本不触发失败。
- 对调度的含义：**故障签名可分类**——`finish_reason=length ∧ completion_tokens≈max` 是契约错配签名，正确补救是"调契约"（提高 max_tokens、禁用 thinking、或改契约要求），盲目切换到另一个思考型模型（GLM→deepseek）只会以 ¥0.12 的代价复购同样的空响应。

## 4. 真实 Q/C/L（恢复 10 次）

| 模型 | 现金 | token(in+out) | 延迟 |
|---|---|---|---|
| deepseek-flash | ¥0.1220 | 39,474 | 10.5–11.8s（思考后被切） |
| qwen-plus | ¥0.0225 | 9,342 | 7.8–31.1s |
| 合计 | **¥0.1445** | 48,816 | — |

预算遵守：10/10 尝试（=上限内）、48,816 ≤ 120K token、¥0.1445 ≤ ¥1、墙钟 144.1s ≤ 1800s。全部四项上限满足。
对比：deepseek 的 ¥0.1220 全部用于购买零可见输出——"付费买空响应"是思考型模型在紧输出契约下的最差成本形态。

## 5. DD 建议（进入故障模型/策略设计）

1. **故障分类学增加"契约错配"故障类（D-contract）**：签名 = `finish_reason=length` 或（completion_tokens ≥ 0.98×max_tokens ∧ 解析失败）。与 D1(空内容)/D3(不可解析)不同类：D-contract 的正确恢复动作是修改重发参数（π 的扩展维度：不只是换模型，还包括 per-call 参数：max_tokens、thinking 开关），而非重执行同配置。
2. **恢复集 R 的动作空间扩展**：当前 R 只含"重执行节点"，建议增加"带参数修正的重执行"（同模型、max_tokens↑ 或 thinking=disabled）。历史基建已验证 deepseek-flash `thinking disabled + response_format=json_object + max_tokens=2048` 三参数可共存。
3. **质量先验（V2QualityPredictor）输入增加机制特征**：completion_tokens/max_tokens 比值与 finish_reason 应进入质量信念，而非只看解析成败——解析失败在思考型模型上主要由机制而非能力驱动。
4. **成本先验**：思考型模型在紧契约下的期望产出价值 ≈ 0（本批实证 15/15），调度器在约束过滤阶段就应把"思考型 × 紧输出预算"组合标记为低通过率，除非契约可调。

## 6. 审计轨迹

| 事件 | 提交 |
|---|---|
| 原始运行标记 INCOMPLETE + 审计 | `30f21ed` |
| GLM 零调用 A–E 分析 + 恢复执行器 v1 | `921d3f0` |
| 401 fail-stop 记录#1（/root/.env 无效 key ****a2f0，零花费停止） | 保留于 `fe_recovery_20261013_213531/` |
| 凭据修复（.env.modelpool 优先；DASHSCOPE_API_KEY） | `205df86` + 401 记录#2 `fe_recovery_20261013_213704/` |
| 凭据优先级反转修复 → 10/10 delivered COMPLETE | `fe_recovery_20261013_213713/` |

两次 401 均被 fail-stop 立即拦截（零调用完成、零花费、INCOMPLETE 记录保留），验证了修复后的失败停止纪律本身。
