# STAGE_D 执行器验收报告（2026-11-02，零调用）

**结论：PASS（工程控制流）。** 192 块零调用 dry-run 全部贯通；预算、并发、恢复、评分、S5 竞速与保护集审计均可复现。本报告不包含任何真实模型执行结果。

## 一、冻结

| 项 | 值 |
|---|---|
| 冻结清单 | `STAGE_D_EXECUTOR_FREEZE.json`（11/11 文件校验通过） |
| 执行器 | `stage_d_executor.py` `ef50527e2920b42d…`，43,292B；不可变快照 `archive_freeze_ef50527e/stage_d_executor.py` |
| 配置 | `stage_d_executor_config.json` `11e520323ecf94a3…` |
| 正式分析 | `stage_d_final_analysis.py` `037fa446…` |
| 检验/功效 | `exact_perm.py` `09468d24…`；`power_sim.py` `4eb9d3c5…` |
| 保护集审计 | `protection_set_audit.py` `e9974f0e…` + `PROTECTION_BASELINE.json` |
| 测试 | 主套件 / P0 专项 / 保护集 R1 |
| 冻结纪律 | 冻结后不得修改；任何变更需新版本 + 操作员批准；执行前逐文件校验；GO 中引用本清单 |

## 二、验证证据

- **矩阵**：192 = 6 臂 × 32；S0/S1/S2/S3/S4/S5 = 2/3/3/8/8/8；ID 唯一；种子 20261102。
- **测试**：主套件 19（18 默认 + 完整 192 单独 OK）；P0 14/14；保护集 R1 6/6。
- **完整 dry-run**：192/192 COMPLETE；1,451 调用；核算 ¥2.358712；全局 token **2,423,553 == 记录 in+out**（审计修复了 release+settle 双计）；峰值 used+reserved **2,427,390 ≤ 9.5M**；结束预留归零。
- **S5**：π/Fixed/Proposed 各 8 次竞速，Static/R-only/Simple 0 次；GLM 先行、SLO=9.5s 在途触发、DS 胜出；取消三态与迟到全额计账（P0 测试）。
- **槽位**：最大并发 glm=2 / ds=1，无超额。
- **恢复**：二次 CLI 运行 `skipped=1`；无重复计账。
- **记录**：`raw`/`score` 分层；异常/动作/决策/竞速日志齐全；六臂配对基础输出 0 差异。

## 三、BLOCKED（真实执行阶段验证，不得提前 PASS）

| # | 项 | 边界 |
|---|---|---|
| B1 | 真实网络取消/限流/并发性能 | 异步 urllib 无传输级取消；三态已实现，真实行为需 GO 后实测 |
| B2 | S5 绝对时延/按时率 | Mock 时钟不作科学证据；89.9s 是压力测试预测 |
| B3 | 官方 tokenizer 精确计量 | 9.5M 硬预算控制 PASS；官方 GLM/DS tokenizer 计量 BLOCKED；tiktoken 仅交叉校验 |

## 四、边界

Mock dry-run 只验证软件控制流，不冒充真实网络性能；`p=0.0039` 与保护集 864 是 Mock 缺少 8 槽答案的产物，**不是科学结果**。192 次真实执行未授权。
