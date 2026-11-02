# STAGE_D 终局执行器代码资产审计（第一阶段，零调用）

**日期**：2026-11-02  
**范围**：`/root/research_outputs/static_pi/stage_d/` 及复用的 `stage_a/executor.py`、`capital_opinion_pilot/transport.py`、`quality_v4/terminal_quality.py`。  
**方法**：完整阅读 `d2_executor.py`（340 行）、`stage_a/executor.py` 关键接口、`transport.py` 全文、`terminal_quality.py` 评分入口；对照 V1.1/V1.2/V1.3.2 预注册。  
**约束**：不修改冻结文件；不发送任何模型请求；本报告只做审计。

---

## 一、代码资产清单

| 模块 | 已有实现（源码事实） | 测试状态 | 是否复用 | 缺失功能 |
|---|---|---|---|---|
| `d2_executor.py` | 六臂（`ARMS`）；S0–S4 场景注入；`Exec` 状态机；检测器 `detect`；策略 `policy`；修复库 `REPAIR_LIB`；格式旁路 `fmt_bypassed`；每执行预算 `calls=14/yuan=0.18`；每执行 `Semaphore(2/1)`；`ThreadPoolExecutor` 调度；`finish` 写 `runs_d2/`；TP/F1/F2 评分；分块随机化 `SEED=20261101` | D2 108 执行实测（`runs_d2/` + `STAGE_D2_REPORT.md`）；无独立单测 | **是**，作为基类与策略/检测/修复来源 | 无 S5；矩阵 18/臂（终局 32/臂）；无全局预算；无虚拟时钟；无 Mock Provider；无断点成本去重；无唯一执行 ID；无 token 台账；无原始输出/评分分离 |
| `stage_a/executor.py` | 提示词（`E_SYSTEM`/`J1_SYSTEM`/`J2_SYSTEM`/`SINK_SYSTEM`）；合同 `CONTRACT`/`SRC`；`build_terminal_output`；`apply_format_rules`；`E_POSITION_ADDENDUM`/`RELAY_ADDENDUM`/`DISAMBIG_ADDENDUM` | Stage A/B/C 多轮实测；合同哈希冻结 | **是**，提示词/合同/终端构建/格式规则全部复用 | 无 |
| `transport.py` | `call_model`：GLM Anthropic 兼容端点 + DeepSeek/Qwen OpenAI 兼容端点；返回 `text/in/out/stop/lat` | 多轮真实调用使用 | **是**，经 `RealProvider` 包装 | **无取消能力**（urllib 同步阻塞）；无统一 Provider 接口；无 Mock |
| `terminal_quality.py` | P0 终端质量评估 `evaluate_terminal_quality(contract, terminal, src)`；claim 级结果；红/黄/绿门禁 | 64 项 P0 测试（既有） | **是**，不修改 | 无（执行器只消费） |
| `d_executor.py` | D1 执行器（S0–S2 先导）；历史实现 | D1 18 执行 | 否（D2 已覆盖） | — |
| `analyze_d2.py` | D2 汇总/符号检验 | D2 报告 | 参考报告格式 | 非终局分析入口（终局是 `stage_d_final_analysis.py`） |
| `stage_d_final_analysis.py` | 终局分析入口：16 对精确符号翻转、族门禁、保护集三分支、HL/CI/LOO | 5 例自检通过 | **是**，不修改 | 需要 `FINAL_RUNS.json` 输入（执行器需产出） |
| `exact_perm.py` / `power_sim.py` | 冻结统计件 | 已审计 19/19 清单 | 是（只读） | 不修改 |
| 单元测试 | `stage_d/` 内无 `test_*.py` / `*_test.py` | **缺失** | — | 需新增终局执行器测试套件 |
| S5 竞速 | **不存在**：`d2_executor.py` 无 S5 分支、无 SLO、无 racing、无 DS 对冲 | **缺失** | — | 必须新增 |
| 全局预算 | **不存在**：预算只在 `Exec` 实例内 | **缺失** | — | 必须新增全局硬停 |
| 断点恢复/成本去重 | 仅 `if f.exists(): continue`（按结果文件跳过）；无成本台账 | 部分（文件级） | — | 必须新增状态仓库与已计成本不重复 |
| 唯一执行 ID | 文件名 `{arm}_{scenario}_r{rep}` 隐式 | 部分 | — | 必须显式 ID（192 个） |
| Token 台账 | 不存在；`transport` 返回 in/out 但执行器未累计 | **缺失** | — | 必须新增 |
| 原始输出/评分分离 | `outputs`（原始文本）+ `finish` 评分混在同一记录 | 部分 | — | 必须分层 |
| 配置 | 硬编码常量 | — | — | 需 `stage_d_executor_config.json` |

## 二、终局需求与现有实现的差距

| 终局要求（V1.3.2 / 任务书） | 现有 D2 | 结论 |
|---|---|---|
| 6 臂 × 32 = 192 执行；S0×2/S1×3/S2×3/S3×8/S4×8/S5×8 | `BLOCKS` = S0×2/S1×3/S2×3/S3×5/S4×5（18/臂，108） | **必须新增终局矩阵** |
| S5：SLO=9.5s、GLM 初始 J2、π/Fixed/Proposed 触发 GLM→DS 竞速、首个可解析胜出、迟到成本全额计账、双槽重叠 | 无 S5 | **必须新增** |
| 全局调用硬顶 2,688 / 现金硬顶 ¥34.56 | 仅每执行 14/¥0.18 | **必须新增全局预算** |
| 单执行截止 180s；S5 紧截止变体 D=90s | `DEADLINE_S=180` 全局 | **需按场景配置**（见冲突 1） |
| 断点恢复、已完成不重跑、成本不重复计 | 文件存在即跳过；无成本台账 | **必须新增** |
| 唯一 ID、配对条件一致 | 隐式文件名 | **必须新增显式 ID/配对校验** |
| 原始输出与评分分离 | 混存 | **必须新增记录分层** |
| 结果交给 `stage_d_final_analysis.py` | 无适配器 | **必须新增 `FINAL_RUNS.json` 构建** |
| 零调用 Mock/虚拟时钟 | 无 | **必须新增测试基础设施** |

## 三、必须报告的预注册/工程冲突（未自行修改预注册）

1. **S5 截止期口径**：任务书写“单执行截止 180 秒”；V1.1/V1.2 冻结的 S5 是**紧截止期变体 D=90s**（GLM 103.5s 超期、静态 DS 79.5s、竞速 89.9s 压线 0.1s）。若 S5 用 180s，则静态 GLM 103.5s 也“按时”，S5 的按时率/时延效应消失，等于改变实验设计。**建议实现为按场景截止：S5=90s，S0–S4=180s**；本执行器按此实现并在配置中显式标注，等待操作员确认。未修改预注册。
2. **S5 SLO**：任务书与 V1.2/V1.3 均为 9.5s；旧版 `STAGE_D_FINAL_PREREGISTRATION.md` 有 20s 表述（已被 V1.1 取代）。执行器采用 **9.5s**。
3. **现金口径**：D2 对 GLM 与 DS 统一按 `in*0.8e-6 + out*2.8e-6` 记账（核算口径）；实际 GLM 订阅 ¥0、DS 按账单。终局执行器将同时记录 **accounting_yuan（硬停用）** 与 **actual_cash_yuan（GLM=0，DS 按价）**，硬停沿用预登记核算口径，避免与历史不可比。
4. **保护集计数**：V1.2 定义“8 槽 × 8 重复 × 6 臂 = 384 槽-run；≥2 倒退 FAIL”，但未明确 384 中是否只统计 Proposed 臂。执行器将记录逐槽结果并产出可审计明细；`protection_regressions` 的最终口径在终局分析前由操作员确认。当前不擅自定义。
5. **Token 上限**：预注册未给数值；本执行器实现 token 台账与可配置硬停，全局上限暂不填写；dry-run 后提交“输入字符 + 各层输出上限”的保守核算报告；精确 tokenizer 校准在零调用约束下 **BLOCKED**（需真实 tokenizer/API 计量）。
6. **终局执行器不在预注册冻结包内**：本轮新增 `stage_d_executor.py`、配置、测试、dry-run 产物；**不修改** V1.3.2、`exact_perm.py`、`power_sim.py`、`stage_d_final_analysis.py`、`MANIFEST_STAGE_D.json`。新执行器冻结时另建 SHA 清单。
7. **清单数量冲突（执行器工作之外，必须报告）**：当前 `MANIFEST_STAGE_D.json` 为 **26 项**（26/26 自洽，V1.3.2 哈希 `f258b5e0…`），但 V1.3.2 §六 仍写 **19 项**。该文件在 10:42 被并行进程修改；本执行器工作未写入预注册文件。此冲突需操作员裁定后才能称“预注册包最终冻结”。

## 四、第一阶段结论

- **可复用**：D2 `Exec` 状态机、六臂策略/检测/修复、stage_a 提示词与合同、终端质量评分、真实 transport（经 Provider 包装）。
- **必须新增**：S5 竞速、终局 192 矩阵、全局预算/槽位、虚拟时钟与 Mock Provider、断点状态仓库与成本去重、显式执行 ID、token 台账、原始/评分分层、`FINAL_RUNS.json` 适配器、测试套件与配置。
- **不修改**：任何冻结预注册/统计文件；任何历史 `runs_d2/` 结果；D2 执行器源码（新执行器以子类/组合方式复用）。
- **未解决问题**：S5 截止期 90 vs 180（待操作员确认）；保护集计数口径（待确认）；token 精确计量（BLOCKED）。

**下一阶段**：实现 `stage_d_executor.py` + 配置 + 测试；全部零调用。
