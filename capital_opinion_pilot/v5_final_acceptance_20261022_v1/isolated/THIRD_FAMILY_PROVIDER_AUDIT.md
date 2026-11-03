# THIRD_FAMILY_PROVIDER_AUDIT — 第三/第四家族服务商审计（零付费，公开信息核验）

## 家族计数纠错（接受裁定）
原 P4={glm-5.3, glm-5.3-flash, glm-4.5-air, DeepSeek} = **2 个家族**（GLM×3 + DeepSeek），
此前"三家族"说法有误。修订目标池：**M1 glm-5.3 / M2 glm-5.3-flash（GLM 家族）+ M3 DeepSeek
（家族2）+ M4 Qwen（家族3）= 4 模型 3 家族**。

## 逐服务商核验（公开信息；接入以凭据到位为准）

| 项 | M3 DeepSeek | M4 Qwen（阿里云百炼） | GLM（对照） |
|---|---|---|---|
| 端点 | api.deepseek.com（OpenAI 兼容 /chat/completions） | dashscope.aliyuncs.com /compatible-mode/v1（OpenAI 兼容） | open.bigmodel.cn /api/paas/v4（已验证同密钥可用） |
| 建议模型 ID | `deepseek-chat`（V 系对话）；`deepseek-reasoner` 备选 | `qwen-plus`（主力）；`qwen-turbo`（轻量备选） | `glm-4.5-air`（档位候选） |
| 价格（元/百万 tok，公开页核验） | chat：入 1（空闲）/2（高峰，缓存未命中），出 4/8；reasoner 出 13.5/27（[官方定价](https://api-docs.deepseek.com)） | plus：入 0.8 / 出 2；turbo：0.3/0.6（[百炼定价](https://help.aliyun.com)）；JSON 模式不加价 | 4.5-Air：入 0.8 / 出 2（[智谱文档](https://docs.bigmodel.cn)）；5.3 按量价待接入时核对 |
| JSON 契约支持 | response_format json_object ✓ | response_format json_object ✓ | 契约输出可用（V2 经验：需打捞兜底） |
| 上下文/配额 | 128K；按账号限流 | 128K+；主账号维度限流 | 编码计划订阅额度 |
| **凭据状态** | **PENDING——需你在服务环境配置（见下）** | **PENDING——同左** | 已有（订阅） |
| 故障域 | 独立服务商（RQ2 记录：网关/限流/时段策略独立） | 独立服务商（阿里云网关） | bigmodel 平台（M1/M2/M4b 同域——**同平台故障相关性如实记录**） |

## 凭据安全规程（按指令）
**不经过聊天/仓库/日志传递密钥**：请直接在服务器环境变量配置（如 `/root/.env.modelpool`，
权限 600、入 .gitignore）：`DEEPSEEK_API_KEY=...` 与 `DASHSCOPE_API_KEY=...`；代码仅从环境读取，
账本只记 key 的 SHA16 指纹与"configured:true"，不存原文。

## 无 GPU 适配
云端 API 全程不需要 GPU；本地 Qwen/嵌入升级等 GPU 恢复（见 GPU_AVAILABILITY_AUDIT）。
