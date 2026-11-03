# MODEL_POOL_EXPANSION_PLAN — 执行模型池扩展方案（零付费核实轮）

## 1. 现有双模型身份与计费（已核实）
| 槽位 | 模型 | 端点 | 计费状态 |
|---|---|---|---|
| M1 强 | `glm-5.3`（bigmodel 编码计划通道） | coding-plan Anthropic 兼容 | 订阅内 UNKNOWN_CASH（token 记账） |
| M2 快 | `glm-5.3-flash` | 同上 | 同上 |

**平台面发现（同密钥 /api/paas/v4/models 免费枚举）**：glm-4.5 / 4.5-air / 4.6 / 4.7 / 5 / 5-turbo /
5.1 / 5.2 / 5.3-flashx 全系可用（同 z-ai 家族不同档位）——**同家族档位多样性可用，但不满足跨家族要求**；
按量价目未核（UNKNOWN，待价卡核实后按真实价计 C）。

## ⚠ 环境事故（2026-10-13 核实）
宿主 GPU 消失（nvidia-smi "No devices were found"、torch.cuda False；会话早期尚在）。
**本地 Qwen 服务当前不可行**——M3/M4a 暂缓，待 GPU 恢复或改远程；本地嵌入升级同缓。

## 2. 扩展候选（按家族多样性，事故后修订）
| 槽位 | 候选 | 家族 | 状态 | 费用性质 |
|---|---|---|---|---|
| M3 | **Qwen2.5-7B-Instruct（本地 vLLM，端口 8127）** | Qwen | **就绪**（权重在库；服务器本轮已拉起） | 零现金；GPU 时延真实（ infra 成本单列） |
| M4a | Qwen2.5-14B-Instruct-GPTQ-Int8（本地） | Qwen（跨规模） | 权重在库（24GB 可载） | 零现金；需与 M3 分时或换卡部署 |
| M4b | `glm-4.5-air`（远程中档） | GLM（同家族） | 密钥可用 | 按量 UNKNOWN |
| M5 | DeepSeek 系列（远程） | DeepSeek | **待你提供 API 密钥** | 按量 |

**事故后建议（按优先级）**：
- **首选 P4 = {M1 glm-5.3, M2 Flash, M4b glm-4.5-air, M5 DeepSeek}**（需你提供 DeepSeek 密钥；
  满足 ≥3 家族的唯一现路径——z-ai 系全是同家族）；
- 次选（无密钥）P4' = {M1, M2, glm-4.5-air, glm-5-turbo}：4 档位但**仅 1 家族**——家族多样性目标
  无法达成，只能验证"档位异构性"，论文口径需如实降级；
- 本地 Qwen（M3/M4a）与 gte-Qwen2 嵌入升级：列入 GPU 恢复后的增强项。
**不强行凑满 5 个**：仅当筛选显示增量价值才引入。

## 3. 预注册嵌套子集（消融用，事前冻结）
P2={M1,M2}（现状）｜P3={M1,M2,M3}｜P4={M1,M2,M3,M4}｜P5=+M5（可选）。
子集固定不依测试结果挑选；消融检验"池多样性→调度收益"是否单调（允许饱和结论）。

## 4. 对调度器的影响（零改动）
joint_scheduler 的 models/π 枚举本就是池无关的；能力表将按 (node_type, model) 扩列，
本地模型计量（vLLM usage 返回 prompt/completion tokens）与远程同构记账；C 口径分列
"现金成本（订阅=UNKNOWN/按量=真实价）"与"infra 成本（GPU 时）"。
