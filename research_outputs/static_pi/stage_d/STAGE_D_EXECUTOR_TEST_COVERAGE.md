# STAGE_D 终局执行器测试覆盖报告（第三阶段，零调用）

**日期**：2026-11-02  
**执行器**：`stage_d_executor.py`（SHA 见 `STAGE_D_EXECUTOR_SHA256.json`）  
**测试**：`test_stage_d_executor.py`，19 个测试方法；默认运行 18 个，完整 192 dry-run 单独运行 1 个。全部 PASS。  
**Mock Provider + 虚拟时钟 + 零网络**；未向任何模型发送请求。

## 20 项检查映射

| # | 检查项 | 测试/证据 | 结果 |
|---|---|---|---|
| 1 | 192 个执行块完整生成 | `T01Matrix.test_192_blocks_six_arms_scenarios`；`STAGE_D_EXECUTOR_MATRIX.json` | PASS |
| 2 | 六臂执行数量正确（每臂 32） | 同上 | PASS |
| 3 | S0–S5 数量与预注册一致（2/3/3/8/8/8 ×6） | 同上 | PASS |
| 4 | S5 GLM 先行、DS 竞速路径正确 | `T02S5Race.test_glm_first_ds_wins_and_slo_wait`；`test_glm_finishes_before_slo_no_race` | PASS |
| 5 | 双槽资源不超额（K_glm=2/K_ds=1） | `T04Slots.test_no_overcommit` | PASS |
| 6 | 先完成、后取消、迟到响应三种情况 | `T02`（DS 先完成 + GLM 取消）；`T03S5Late.test_late_response_cost_counted` | PASS |
| 7 | 迟到成本完整记录 | `T03`（`late_cost_yuan > 0`） | PASS |
| 8 | 单执行调用预算硬停 | `T05Budget.test_per_exec_call_cap` | PASS |
| 9 | 全局调用预算硬停 | `T05Budget.test_global_call_cap` | PASS |
| 10 | 单执行现金预算硬停 | `T05Budget.test_per_exec_cash_cap` | PASS |
| 11 | 全局现金预算硬停 | `T05Budget.test_global_cash_cap` | PASS |
| 12 | 截止时间硬停 | `T06Deadline.test_deadline_hard_stop` | PASS |
| 13 | Token 预算保护 | `T05Budget.test_token_cap` | PASS |
| 14 | 中断后恢复 | `T07Resume.test_no_double_cost_on_resume`（CLI 二次运行 `skipped=1`） | PASS |
| 15 | 已完成执行块不重复执行 | `T07Resume.test_store_skips_completed` + CLI resume | PASS |
| 16 | 已计成本不重复计账 | `T07Resume.test_no_double_cost_on_resume`（全局 calls == 记录 calls 之和） | PASS |
| 17 | 异常状态正确记录 | `T08AnomalyRawScore.test_anomaly_recorded`（注入 provider 异常） | PASS |
| 18 | 原始模型输出与评分数据分离 | `T08AnomalyRawScore.test_raw_and_score_separated` | PASS |
| 19 | 结果可交给 `stage_d_final_analysis.py` | `T09AnalysisInput.test_build_and_run_analysis`；`STAGE_D_DRYRUN_ANALYSIS.log` | PASS（管道）；**Mock 结果 p=0.0039 是测试产物，不是科学证据** |
| 20 | 完整零调用 dry-run 从头到尾贯通 | `T11FullDryRun`（`STAGE_D_FULL_DRYRUN=1`，192 块，4.55s）；CLI `STAGE_D_DRYRUN_FULL.log` | PASS |

## 测试运行记录

- 默认套件：`Ran 19 tests ... OK (skipped=1)`（跳过的就是完整 192 用例）。
- 完整 192 用例：`STAGE_D_FULL_DRYRUN=1 python3 -m unittest test_stage_d_executor.T11FullDryRun -v` → `Ran 1 test ... OK`。
- 完整 CLI dry-run：192 记录、192 唯一 ID、全部 `COMPLETE`；日志 `STAGE_D_DRYRUN_FULL.log`。
- 额外核验：六臂配对基础输出一致（S3/S4/S5 每个 scenario/rep 的 E1 raw text 0 差异，192 记录比对）。

## 测试边界（不得写成 PASS 的项）

- Mock 只验证软件控制流；**不验证真实网络取消、限流、并发性能**。
- S5 的绝对 makespan/按时率是 Mock 时钟产物：48 个 S5 记录全部 `on_time=false`（~105–130s），与预注册 89.9s 压力测试预测无关；不得据此宣称时延结果。
- 预注册包当前 26 项清单 vs V1.3.2 §六 仍写 19，属于执行器工作之外的冲突，见终审报告。

## P0 专项套件（2026-11-02，`test_stage_d_p0.py`，14/14 PASS）

| 组 | 测试 | 结果 |
|---|---|---|
| P0-2 三态取消 | 逻辑取消不停止+全额计账；槽占用到线程真实结束；Mock 传输取消零成本；race_log 记录 cancel_state | 4/4 |
| P0-3 预留台账 | 20 并发预留峰值 ≤ 上限且有拒绝；结算归还差额；在途不足拒绝；端到端峰值不变量+归零 | 4/4 |
| P0-5 S5 边界 | 谓词 89.9/90.0/90.1 精确；端到端两次校准（抖动 0.3s → ±1.0 档，如实降级）；GLM 先完成；DS 胜出+取消；取消后迟到计账；双超时 | 6/6 |

Mock 输出一律不作科学证据。
