# API_PRICING_RESEARCH — 公开定价调研（零调用；待操作员独立核实后冻结）

⚠️ **以下数据来自公开网页搜索，未经操作员独立核实，不可直接用于费用冻结。**
操作员必须访问官方定价页确认后方可填入 MODEL_REGISTRY 并解除 M3/M4 门控。

## GLM（智谱 BigModel）

| 模型 | 输入 (元/百万tok) | 输出 (元/百万tok) | 备注 |
|---|---|---|---|
| GLM-5-Turbo [0,32K) | ~5 | ~22 | 有限时免费活动 |
| GLM-5-Turbo ≥32K | ~7 | ~26 | |
| GLM-5.1（旗舰） | ~6 | ~24 | |
| GLM-5.3 | **未找到国内平台逐项价格** | | 国际站约 $1.40/$4.40 |
| GLM-5.3-Flash | 免费档（Z.ai） | 免费档 | 需确认订阅条件 |

**关键缺口**：GLM-5.3 在国内 BigModel 平台的逐项定价未从搜索中获取到（页面动态渲染）。操作员需直接访问 [docs.bigmodel.cn/cn/guide/start/pricing](https://docs.bigmodel.cn/cn/guide/start/pricing) 确认。

**订阅问题**：capital_opinion_pilot 中已有 147 次 GLM-5.3/Flash 调用。若这些调用在订阅额度内（零增量现金），**不能当作零推理成本**——需用标准化资源成本替代（操作员既有裁决）。

## DeepSeek

| 模型 | 输入 (元/百万tok) | 输出 (元/百万tok) | 备注 |
|---|---|---|---|
| deepseek-chat (V3.x) 空闲 | 1（缓存未命中） | 4 | 缓存命中 0.5 |
| deepseek-chat 高峰 | 2 | 8 | 缓存命中 1 |
| deepseek-reasoner (R1) 空闲 | 2 | 8 | 缓存命中 1 |
| deepseek-reasoner 高峰 | 9 | 27 | 缓存命中 4 |

来源：[api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing)

**候选**：`deepseek-chat`（非推理）或 `deepseek-reasoner`（推理）。需要操作员确认使用哪个 + 访问凭据。

## Qwen（阿里云百炼）

| 模型 | 输入 (元/百万tok) | 输出 (元/百万tok) | 备注 |
|---|---|---|---|
| qwen-plus (当前) | ~0.8（优惠价） | ~8 | 常规约 2/8 |
| qwen3.7-plus [0,256K] | 2 | 8 | 8折后 1.6/6.4 |

来源：[help.aliyun.com/zh/model-studio/model-pricing](https://help.aliyun.com/zh/model-studio/model-pricing)

**候选**：`qwen-plus`。需操作员确认具体版本号 + 凭据 + 是否在免费额度内。

## 80 次筛选预算估算（基于上述价格，未经核实）

假设平均输入 2,000 tok + 输出 500 tok/次：

| 模型 | 20 次调用输入费 | 20 次调用输出费 | 合计 (元) |
|---|---|---|---|
| GLM-5.3 (~6/24) | 0.24 | 0.24 | ~0.48 |
| GLM-5.3-Flash (免费) | 0 | 0 | 0（需标准化） |
| deepseek-chat (高峰 2/8) | 0.08 | 0.08 | ~0.16 |
| qwen-plus (~0.8/8) | 0.032 | 0.08 | ~0.11 |
| **合计** | | | **~0.75 元** |

**注意**：这是基于未核实价格的粗估。实际费用可能因阶梯定价、缓存命中率、高峰/空闲时段而有显著差异。GLM-5.3-Flash 若在订阅内则现金为零但标准化成本非零。

## 下一步

1. 操作员访问三个官方定价页截图/记录 → 填入 MODEL_REGISTRY
2. 确认 GLM-5.3 具体型号名（搜索中 GLM-5.3 未在国内平台单独列出——可能是 GLM-5.1 的别名或需要操作员的实际调用记录确认）
3. 确认 DeepSeek 选 deepseek-chat 还是 deepseek-reasoner
4. 确认 Qwen 选 qwen-plus 还是其他版本
5. 凭据填入后 M3/M4 门控解除 → 80 次筛选可执行
