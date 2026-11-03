# Stage D S5 修复、测试与真实实验准入审计

**日期**：2026-11-03
**性质**：零 API / 零 GPU；不覆盖历史数据；不增加预算。
**范围**：仅 S5 竞争结算；不改任务、Gold、提示词、模型身份、策略、评分规则。
**执行器候选**：`4ab0c47d642e4ec6e19b28f3725024550ea56df5842876434b55deaf5c67c997`（48,385 B）

---

## 0. 结论先行

| 项 | 判定 |
|---|---|
| S5 修复本身 | **PASS**（测试 + 192 Mock 控制流） |
| 192-run Mock | **PASS WITH KNOWN S5 BOUNDARY**（192/192 COMPLETE；两例为旧基线已知边界翻转） |
| R1 保护（软件/单元） | **PASS** |
| R1 保护（真实数据） | **BLOCKED**（mock 不能替代；真实 R1 必须用真实 SINK 输出） |
| DD-V4 / DD-V5 回归 | **BLOCKED / UNRESOLVED**（Stage D 目录无此命名测试；需操作者给出路径） |
| 真实 192-run 准入 | **BLOCKED**（见 §8；不得启动） |

**没有发起任何真实调用。** 预算仍为 2,688 calls / 9.5M tokens / ¥34.56；`runs_final/` 不存在；真实调用授权环境变量未设置。

---

## 1. 冻结资产核验（先于修改）

- `MANIFEST_STAGE_D_CORE_19.json`：**19/19 PASS**。
- 配置 `stage_d_executor_config.json`：`11e52032…` **PASS**。
- 时钟测试 `test_stage_d_clock.py`：`49f428c6…` **PASS**。
- 预算/矩阵/槽/截止期：未改；`matrix` 校验 192、6 臂各 32。
- **执行器哈希不一致**：冻结登记为 `ef50527e…`（43,292 B），工作树为 `b0d7a589…`（44,419 B）。`b0d7a589` 是 2026-11-02 12:51 的**未登记部分 S5 修复**（胜者先提交 + 败者后台线程，但 `finish()` 仍 join 败者）。该版本已存档于 `archive_freeze_b0d7a58900f8f27a/`；冻结基线 `archive_freeze_ef50527e/` 保留。本轮以 `b0d7a589` 为工作基础完成剩余修复，并生成新候选；**没有覆盖任何历史文件**。

`STAGE_D_ASSET_INTEGRITY_REPORT.md` 记录完整哈希与判定。

---

## 2. 问题与修复边界

### 2.1 冻结 `ef50527e` 的问题

S5 竞速中，胜者可解析后，代码先 `_finish_call` 胜者，再 **同步** `_finish_call` 败者，最后才 `_after_j2(r)`。因此：

- J2 的 Completed 状态被败者的迟到响应阻塞；
- SINK 无法及时 Ready/启动；
- `makespan` 包含败者等待，不能反映获胜路径。

### 2.2 本轮修复（仅 S5 结算）

| 要求 | 实现 |
|---|---|
| 胜者满足条件后立即提交 | 胜者 `_finish_call` 后立即 `_after_j2(r)`，J2 置 Completed |
| 立即释放合法下游 ready 节点 | DAG 调度器在 J2 Completed 后立即提交 SINK；不再等待败者 |
| 败者后台继续结算 | `_settle_loser` 线程等待迟到响应，全额计账；不阻塞 DAG |
| 完整记录败者 Token/费用/异常/结束时间 | `S5_SETTLEMENTS.jsonl` + 每 run 的 `settlement` 字段 |
| 败者不得覆盖胜者 | `_settle_loser` 不改 `outputs/state/exec_log/score`；恢复 `model_used["J2"]` 为胜者 |
| 不改质量选择/重执行/分配 | 未改任何 `policy`/`apply_action`/`detect`/重试逻辑 |
| 不得靠取消败者降成本 | 未新增取消；既有 `glm.cancel()`/`ds.cancel()` 与 `cancel_effective` 语义不变 |
| 区分终端完成与后台清理 | `terminal_completed_at_s`（= makespan）与 `settlement_completed_at_s` 分开记录 |

### 2.3 关键代码改动

| 位置 | 改动 |
|---|---|
| `FinalExec.__init__` | 新增 settlement 状态、`terminal_completed_at_s`、提交快照 |
| `_exec_s5_j2` | 胜者时间戳；`_after_j2` 先于败者线程 |
| `_settle_loser` | 生成 settlement 记录（loser in/out/cost/late/cancel/error/end），写 JSONL；不碰胜者结果 |
| `finish()` | **移除败者 join**；写入 `terminal_completed_at_s`、`j2_winner_completed_at_s`、`settlement_pending`、`settlement` |
| `settle()` / `recommit_with_settlement()` | 批次尾部 join 败者，把迟到成本/token 合并回该 run 的已提交记录 |
| `main()` | 收集本次执行的 `ex`；全部 run 结束后统一 settle + recommit；再打印 `gb.left()` |
| `CallHandle`（Mock only） | `cancel_effective=False` 时不再提前 break，完整跑到迟到响应（与 `_RealHandle` 语义一致）；`cancel_effective=True` 仍 transport cancel |

**Mock-only 说明**：`CallHandle` 只被 `MockProvider` 使用；`_RealHandle`（真实 urllib）未改。该修改是为了让 `cancel_effective=False` 的“逻辑取消、传输继续”在 Mock 中可测试，不是真实协议变更。

### 2.4 残留风险（如实披露）

1. **槽占用**：真实败者的 HTTP 调用仍持有其模型槽直到响应返回；下游节点可立即进入 Ready，但若槽已满仍需等待。这是真实资源约束，不通过提前释放槽来“造出”并发。
2. **批次尾部等待**：`settle_all()` 在 192 个 run 全部结束后等待最长的败者；这不影响任何单 run 的 `makespan`，但会延长批次收尾时间。
3. **崩溃恢复**：若进程在 `settlement_pending=True` 时崩溃，该 run 的迟到成本可能只存在于 ledger 或丢失；`RunStore.completed` 会跳过已提交记录，不会自动补结算。真实批次不应中断；该限制未在本轮扩展修复（避免超范围重构）。

---

## 3. 测试报告

### 3.1 主套件

`test_stage_d_p0.py + test_stage_d_executor.py + test_stage_d_clock.py + test_protection_set_audit.py`

```
48 passed, 1 skipped in 14.73s
```

### 3.2 新增 S5 结算测试（`T07S5Settlement`）

| 测试 | 验证 |
|---|---|
| `test_finish_returns_before_late_loser` | `finish()` 返回时 `settlement_pending=True`；`terminal_completed_at_s == makespan_s`；makespan < 败者延迟；settle 后 `settlement_completed_at_s > terminal_completed_at_s` |
| `test_loser_does_not_override_winner` | settle 后 `state["J2"]=="Completed"`、`outputs["J2"]` 仍为胜者文本、`score`/`status` 不变 |
| `test_both_branch_costs_counted` | `settled_accounting_yuan == sum(raw calls)`；`late_accounting_yuan > 0` |
| `test_both_unparseable_fallback` | 两分支均不可解析 → `S5_BOTH_UNPARSEABLE`、无 winner、无 settlement |

### 3.3 既有 S5 回归

- `P05S5Boundary::test_winner_only_makespan_with_late_loser`：**PASS**（Proposed makespan 显著小于 Simple）。
- `T02S5Race` / `T03S5Late` / `P0-2` 三态取消 / `P0-3` token 预留：**PASS**（包含在 48 passed）。

### 3.4 其他回归

- `test_stage_d_v2_transport.py`：**4 passed**。
- `test_stage_d_clock.py`：**5 passed**（包含在主套件）。
- `test_protection_set_audit.py`：**PASS**（包含在主套件）。

### 3.5 DD-V4 / DD-V5

在 Stage D 目录与 `/root/q_foundation`、`/root/research_outputs` 中**未找到**名为 DD-V4/DD-V5 的测试文件。`/root/cap_eval_bench_v1/` 存在 DD-V5.1 联合实验代码，但那是另一个项目，不是本执行器的回归测试。**该项 BLOCKED/UNRESOLVED，需操作者给出明确路径**；不能用 P0-4/P0-5 或 v2 transport 冒充 DD-V4/V5。

---

## 4. 192-run Mock 全量控制流

运行：`python3 stage_d_executor.py run --out runs_s5fix_mock3`

| 指标 | 结果 |
|---|---|
| 执行 | **192/192 COMPLETE** |
| calls | **1,451** |
| accounting | **¥2.358712** |
| tokens | **2,423,553** |
| settlement 行 | **24**（3 个 race 臂 × 8） |
| `settlement_pending`（批次结束后） | 0（全部 settle + recommit） |
| `cancel_effective=True` 下 late 败者 | 0（transport cancel，0 成本）；`cancel_effective=False` 单元测试显示 late 成本 >0 |
| `runs_final/` | 未创建 |

### 4.1 与冻结基线逐 run 对比

基线 `regression_20261102_191of192/run1` 与 `run2`（各 192 条）：

- 与 run1 相比：**191/192 的 status/tp/calls 完全一致**；唯一差异 `Static|S5|r1`：`INCOMPLETE_DEADLINE → COMPLETE`。
- 与 run2 相比：**191/192 完全一致**；唯一差异 `R-only|S5|r4`：`INCOMPLETE_DEADLINE → COMPLETE`。
- 这两条都是**非 race 臂**（Static / R-only），S5 结算修复不经过它们；旧 run1/run2 本身就在这两条上发生过 COMPLETE↔INCOMPLETE 翻转（已知 S5 边界非确定性，操作者 2026-11-02 已裁定“PASS WITH KNOWN NONDETERMINISM”）。
- 新 run 的 makespan 也落在旧两 run 的同一边界区间（Static|S5|r1：128.0s vs 旧 131.8/125.6s；R-only|S5|r4：126.7s vs 旧 126.5/170.5s）。

**判定：192 Mock 控制流 PASS WITH KNOWN S5 BOUNDARY；不是 S5 修复引入的回归。**

### 4.2 R1 保护审计（重要）

`build-analysis-input` 在 `runs_s5fix_mock3` 上运行 R1 审计得到 **864 regressions / verdict FAIL**。原因不是执行器回归，而是 **mock fixture 限制**：

- mock SINK 只输出 `D_1`/`D_2` 两条 claim；
- R1 保护槽 `B1/B2/B4/E1/F3/U2/F1/F2` 在 mock 中从未被断言；
- 审计器按“参考正确但当前不正确”计为 regression → 864 条全部是 fixture 缺口。

**因此：**
- R1 **审计器单元测试**：PASS。
- 192 Mock 的 R1 结果：**NOT APPLICABLE**，不得写成 PASS，也不得写成执行器 FAIL。
- **真实 R1 保护审计：BLOCKED**，必须在真实 192 输出上运行；若真实数据出现 regression，按协议停止/报告。

---

## 5. 实验协议一致性审计

| 项 | 冻结值 | 本轮 |
|---|---|---|
| 臂 | 6（Static/R-only/π-only/Simple/Fixed/Proposed） | 未改 |
| 矩阵 | 6×32=192；S0 2/S1 3/S2 3/S3 8/S4 8/S5 8 | 未改（matrix PASS） |
| 槽 | GLM 2 / DS 1 | 未改 |
| 预算 | 2,688 calls / 9.5M tokens / ¥34.56 | 未改 |
| 截止期 | S0–S4 180s；S5 90s；SLO 9.5s | 未改 |
| 质量选择/重执行/分配 | 冻结 | 未改 |
| 任务/Gold/提示词/模型 | 冻结 | 未改 |
| 评分器 | `terminal_quality v1.2.3` | 未改 |
| 双合同 | 旧合同 + V3 | 未改（最终报告仍双口径） |

**唯一变更**：S5 结算路径 + Mock 的 `cancel_effective=False` 保真；无其他功能重构。

---

## 6. 预算与资源核算

| 项 | 值 |
|---|---|
| 真实调用上限 | 2,688 |
| Token 上限 | 9,500,000 |
| 现金上限 | ¥34.56 |
| 本轮真实调用 | **0** |
| 本轮 GPU | **0** |
| Mock calls / accounting / tokens | 1,451 / ¥2.358712 / 2,423,553（仅控制流验证，非科学结果） |
| 真实 `runs_final/` | 不存在 |

---

## 7. PASS / FAIL / BLOCKED

**PASS**

- Core-19 资产 19/19；配置/时钟测试哈希一致。
- S5 单元/集成测试（含 4 项新增结算测试）。
- 192 Mock 控制流：192/192 COMPLETE；calls/cost/tokens 与旧基线规模一致；仅两例已知 S5 边界差异。
- 192 矩阵、6 臂各 32。
- R1 审计器单元测试。
- v2 transport 4 passed。
- 零真实调用、零 GPU、预算未动。

**FAIL**

- 修改前工作树执行器与冻结 `ef50527e` 哈希不一致（未登记部分修复 `b0d7a589`）；本轮已生成新候选，但**新候选尚未获操作者批准**。
- 192 Mock 的 R1 审计 864 regressions（**fixture 限制，不是执行器 FAIL**；但自动审计文本为 FAIL，不能直接作为准入通过证据）。

**BLOCKED**

1. 真实 R1 保护审计：必须用真实 SINK 输出；mock 不能替代。
2. DD-V4 / DD-V5 回归：Stage D 目录无此命名测试；需操作者给出路径/口径。
3. 真实 192-run 准入：需操作者批准新执行器候选与 diff。
4. 真实调用前受控预检：本轮未执行；预检失败即停。
5. 已知 S5 边界非确定性：两例（Static|S5|r1、R-only|S5|r4）需操作者确认接受“192/192 vs 旧 191/192”。

---

## 8. 最终准入报告

**真实 192-run 六臂实验：BLOCKED，不得启动。**

解除条件（全部满足后才可申请真实预检）：

1. 操作者批准执行器候选 `4ab0c47d…`（48,385 B）与 `STAGE_D_S5_FIX_DIFF.txt`（189 行，+111/-9；仅 S5 结算与 Mock 保真）。
2. 操作者确认两例已知 S5 边界差异可接受（与 2026-11-02 的 PASS WITH KNOWN NONDETERMINISM 一致）。
3. R1 真实数据审计方案获接受：mock 结果不作为 R1 证据；真实 R1 作为 stop-gate，出现 regression 即停止并报告。
4. DD-V4/V5 的路径与口径明确，并全部通过；若不存在，需操作者裁定以哪些回归替代。
5. 完成一次受控真实预检（HTTP 成功、模型/端点/参数符合冻结配置）；预检失败即停，不换端点/模型。
6. 正式启动命令仍由操作者显式授权；本轮不启动。

---

## 9. 产物

- `STAGE_D_S5_FIX_DIFF.txt`（sha `deed0c7f…`）
- `STAGE_D_S5_FIX_TEST.log`（48 passed + 4 passed）
- `STAGE_D_S5_FIX_MATRIX.json`（192，六臂各 32）
- `runs_s5fix_mock3/`（192 记录 + `S5_SETTLEMENTS.jsonl` + `FINAL_RUNS.json`）
- `STAGE_D_S5_FIX_FREEZE.json`（候选哈希/测试/Mock/预算/准入）
- `STAGE_D_ASSET_INTEGRITY_REPORT.md`（资产核验）

**没有真实 API 调用，没有 GPU 调用，没有覆盖历史数据，没有增加预算。**
