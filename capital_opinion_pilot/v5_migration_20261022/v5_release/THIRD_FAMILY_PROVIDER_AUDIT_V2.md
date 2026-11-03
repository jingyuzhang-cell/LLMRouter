# THIRD_FAMILY_PROVIDER_AUDIT_V2 — 模型身份核验修订版（零付费，官方文档直核）

## 状态声明（按裁定）
M3/M4 为**候选**，凭据未配置、接口未实测——不得写成"已验证执行模型"。
当前实际可接入：仅 M1/M2（GLM 订阅）。

## M3 = deepseek-flash（修订：deepseek-chat 已于 2026-07-24 停用，接受纠正）
| 项 | 核验值（来源：api-docs.deepseek.com，2026-10-13 抓取） |
|---|---|
| 服务版本 | DeepSeek-V4.1-Flash（旧别名 deepseek-v4-flash 已退役→自动重定向并按 Flash 计价；**禁止再用 deepseek-chat / deepseek-reasoner**） |
| 上下文 / JSON | 1M tokens；response_format JSON ✓；支持思考/非思考与 Anthropic 兼容 API |
| 价格（USD/1M tok） | 入（缓存未命中）$0.15 谷 / $0.30 峰；入（命中）$0.003/$0.006；**出 $0.60 谷 / $1.20 峰**；峰时=工作日 01:00–04:00 与 06:00–10:00 UTC |
| 并发 | 2500 |
| 备选 | deepseek-v4-pro（入 $0.66/$1.32，出 $1.98/$3.96）——仅登记，本轮不加入 |
| 旧价作废 | 此前引用的 deepseek-chat 人民币价表**全部作废**（旧模型价，不得沿用） |

## M4 = qwen-plus（现行别名，钉死条件）
| 项 | 核验值（来源：help.aliyun.com 百炼计费页，2026-10-13 抓取） |
|---|---|
| 身份 | **current 别名**（当前=qwen-plus-2025-12-01；Qwen2.5 系已下线） |
| 地域 | **北京**（国际地域更贵——如 qwen3.8-max 国际 14.988 vs 12；端点与计费均钉北京） |
| 价格（¥/1M tok） | ≤128K 非思考：入 **0.8** / 出 **2**；思考模式输出 **8**（128–256K/256K–1M 阶梯另有 2.4/20、4.8/48） |
| JSON | 计费页未载——**接入测试实测项**（dashscope 兼容模式 response_format） |
| 免费额度 | 多数模型 100 万 token/90 天（北京）——若可用则首测现金可更低，不作依赖 |

## 目标池（修订）
M1 glm-5.3 + M2 glm-5.3-flash（GLM）+ M3 deepseek-flash（家族2）+ M4 qwen-plus（家族3）
= 4 模型 / 3 家族。GLM 订阅 0 增量现金 ≠ 0 推理成本；代理价（如 4.6 档 ¥5/M）一律标 PROXY。

## 凭据状态
`/root/.env.modelpool` **未配置**（模板与 600 权限示例已建：.env.modelpool.template；
.gitignore 已覆盖）。密钥只由你在服务器填写；一切日志/账本只记 SHA16 指纹与 configured:true。
