# 执行器身份勘误（EXECUTOR_IDENTITY_ERRATUM · 零调用 · 2026-11-06）

> **性质**：新增勘误文件（操作员 2026-11-06 批准）。**不修改、不覆盖、不删除**下列原文件，它们保持原样：
>
> | 原文件 | SHA256（勘误时实测） |
> |---|---|
> | `EXECUTOR_IDENTITY_SUPPLEMENT.md` | `62e9494beca20bbcf2004a500a2be1988b579b2b06481e3d5c390540df421448` |
> | `MANIFEST_STAGE_D_V2.json` | `65d50ff7f6593e8a65a5b3bc52ba2d84c688d8d093f7affc63bdff89fe916a54` |
> | `MANIFEST_STAGE_D.json` | `27bccff0f8fcd575a78bab6bcd0886a82b701314a8574e91600b99c317166c3d` |

## 一、勘误内容

`EXECUTOR_IDENTITY_SUPPLEMENT.md` 第一、二节，以及 `MANIFEST_STAGE_D_V2.json` 的 `executor_version_registration`，均称"192 次 Stage D 执行推定由 `stage_d_executor.py`（64dea819…）产生"。**该推定错误。** 更正登记为：

| 组件 | 文件 | SHA256 |
|---|---|---|
| 执行器（A‴） | `stage_d_v2_executor.py`（56,231 字节，mtime 2026-11-03 12:11:14） | `e80fe6a3a37947cada79540885dc8cbd631dbcd1a0daffbc82e3ef3bb9ea8d5b` |
| 配置 | `stage_d_v2_executor_config.json`（mtime 2026-11-03 11:33:14） | `914f3edd4c4848e3f7063ce6c398f80afc773cf790844973638550848f543581` |

原推定的基础执行器 `stage_d_executor.py`（`64dea81992f9f036af783cf91079f32dbb808948210c13ea72069ddd35839f7d`）与基础配置（`11e520323ecf94a3d70130c8b1da15cd65e31b019f4bf669aed93361bbdecdb5`）**不是** 192 次执行的产生者。

## 二、证据

**记录内判别特征（192 条记录全部满足 A‴、全部违背基础执行器）**

| 判别特征 | 192 条记录实测 | 基础执行器 + 基础配置 | A‴ 执行器 + V2 配置 |
|---|---|---|---|
| 截止期 | 192/192 为 300 s | 180 s（S5 为 90 s） | 300 s |
| E 节点模型 | deepseek 782/782 次调用 | glm53flash | deepseek（`AROUT`） |
| J1 走 GLM 时的最大输出 | 8,192 | J1 上限 3,000，不可能出现 8,192 | 8,192（`AMAX`） |
| 真实句柄 `latency` 字段 | 1,409 次调用为数值 | 属性不存在，真实路径首调即抛 `AttributeError` | 已修复（文件内注释：bugfix 2026-11-03） |
| git 归档 `65fd5abd`（2026-11-03 14:05） | — | 64dea819 | e80fe6a3 / 914f3edd |

**零调用逐记录重放**（`e_node_audit/replay_all_192.py`，结果 `REPLAY_192_RESULTS.json` SHA `d1178041e97fa788b95081896ce846c454e2ad030a19c5934ae7979bd1a8ecca`）：

- 时序完整的 170 条记录：**170/170 逐字段复现**（TP、状态、调用数、终态、动作、逐节点模型）；
- 全部 192 条：185 条完全一致、191 条 TP 一致；不一致的 7 条均为原记录含时长未记录的传输错误；
- 基础执行器真实模式下任何 LLM 节点都无法完成，因此可复现 0/192。

**时间序**：A‴ 执行器 mtime 11-03 12:11，记录跨度 11-03 13:03 至 21:56。

## 三、可声明范围

这是**行为复现证据**，不是逐次运行的密码学证明：192 条记录本身不含任何执行器、配置或依赖哈希。论文建议措辞：

> 192 次 Stage D 真实执行由 A‴ 执行器 `stage_d_v2_executor.py`（e80fe6a3…）与配置 914f3edd… 产生，依据为记录内五项判别特征与零调用逐记录重放（完全时序记录 170/170 复现）；不存在逐次密码学证明。

论文方法部分对 192 次执行配置的描述应为 A‴ 路由：E1–E4、J2、SINK 走 DeepSeek（thinking 关闭）@4000，J1 走 GLM-5.3-Flash（reasoning_effort=low）@8192，FMT 本地，截止期 300 s。

## 四、勘误中发现的附带事实：S0–S4 的 swap 动作没有换模型

A‴ 执行器的 `exec_llm` 用路由表决定模型：`alias = AROUT.get(node, spec_model)`。`AROUT` 覆盖全部 LLM 节点，而 `swap` 动作只改写 `spec[node]["model"]`，所以在 S0–S4 中 **swap 不改变模型**，实际等同于原模型重执行（版本递增、下游失效、重跑）。

192 条记录实测：S0–S4 的全部 89 次 swap（E2 8 次、FMT 33 次、J1 42 次、J2 6 次）之后的重执行均使用**同一模型**。A‴ 执行器中唯一真正的模型切换，是 S5′ 中 J1 的 GLM→DS 条件性异构重执行（`_exec_s5prime_j1`），它不经过 swap 动作。

**对论文的影响**：Stage D 在 S0–S4 中记为"π/swap"的动作应表述为同模型重执行（R），不得据此声称模型切换（π）的效果。此前"重复的不必要 swap 导致质量级联退化"的机制，应改述为"重复的不必要重执行（记录标签为 swap）导致质量级联退化"。

## 五、命名提示

`EXECUTOR_IDENTITY_SUPPLEMENT.md` 中的"V2"标签指 `4ab0c47d…`（S5 修复候选），**不是** `stage_d_v2_executor.py`。本勘误一律用文件名加 SHA 指称执行器，以免混淆。

## 六、关联

- 审计报告：`e_node_audit/E_NODE_COMPAT_AUDIT.md`（SHA `3cbac9e83e989bbdd83e16f8e3bdc5aa1a46bad2815840b609be6a471e75fb4b`）
- 新批次清单：`DAMJS_R2_BATCH_MANIFEST.json`（登记本勘误）
