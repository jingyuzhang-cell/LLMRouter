# Stage D 冻结资产完整性报告（2026-11-03，零 API / 零 GPU）

## 1. 核心清单

`MANIFEST_STAGE_D_CORE_19.json`：**19/19 PASS**（18 科学核心 + 1 替代审计证据；见清单）。

## 2. 执行器与配置

| 资产 | 期望 | 实际 | 判定 |
|---|---|---|---|
| `stage_d_executor.py`（冻结 `ef50527e`） | `ef50527e2920b42d…`，43,292 B | `b0d7a58900f8f27a…`，44,419 B | **FAIL（工作树含未登记的部分 S5 修改）** |
| `stage_d_executor_config.json` | `11e520323ecf94a3…` | 同 | PASS |
| `test_stage_d_clock.py` | `49f428c607d5c0a1…` | 同 | PASS |
| `archive_freeze_ef50527e/stage_d_executor.py` | `ef50527e…` | 同 | PASS（冻结基线存档） |
| `archive_freeze_b0d7a58900f8f27a/stage_d_executor.py` | `b0d7a589…` | 同 | 未登记中间版存档 |

**结论**：工作树执行器不是冻结 `ef50527e`，而是 2026-11-02 12:51 的未登记部分修复版 `b0d7a589`（含“胜者先提交 + 败者后台线程”，但 `finish()` 仍 join 败者）。本轮以该版为工作基础，完成剩余 S5 结算修复，生成新候选 `4ab0c47d…`；冻结基线 `ef50527e` 与中间版 `b0d7a589` 均保留，不覆盖。

## 3. 实验协议与预算

| 项 | 值 | 判定 |
|---|---|---|
| 矩阵 | 6 臂 × 32 = 192；S0 2 / S1 3 / S2 3 / S3 8 / S4 8 / S5 8 | PASS（`stage_d_executor.py matrix`） |
| 槽 | GLM 2 / DS 1 | 未改 |
| 预算 | 2,688 calls / 9,500,000 tokens / ¥34.56 | 未改 |
| 截止期 | S0–S4 180s；S5 90s；SLO 9.5s | 未改 |
| 真实调用授权 | `STAGE_D_REAL_CALLS_AUTHORIZED` 未设置 | PASS（本轮零调用） |
| `runs_final/` | 不存在 | PASS（真实批次未启动） |
| 并行 GLM 消费者 | 0 | PASS |

## 4. R1 保护集

| 项 | 值 |
|---|---|
| 保护规格 | `STAGE_D_PROTECTION_SET_SPEC.md` sha `080ccc4d…` |
| 基线 | `PROTECTION_BASELINE.json` sha `652f3ea4…` |
| 审计器 | `protection_set_audit.py` sha `e9974f0e…` |
| 审计器单元测试 | `test_protection_set_audit.py` sha `747bb083…`，**PASS（包含在 48 passed 中）** |
| 192 Mock R1 审计 | **864 regressions / verdict FAIL — 但为 mock fixture 限制**：mock SINK 只输出 D_1/D_2，不输出 B1/B2/B4/E1/F3/U2/F1/F2，审计器把这些槽判为缺失。**不是执行器回归，也不是真实 R1 结果。** |
| 真实 R1 | **BLOCKED**：必须用真实 SINK 输出审计；mock 不能替代 |

## 5. 判定

- **PASS**：Core-19、配置、时钟测试、矩阵、预算、真实调用门禁、无并行消费者、R1 审计器单元测试。
- **FAIL**：工作树执行器与冻结 `ef50527e` 哈希不一致（已定位为未登记部分 S5 修改；本轮生成新候选修复）。
- **BLOCKED**：真实 R1 保护审计（需真实输出）；DD-V4/V5 测试文件未找到；真实预检未执行。

**资产完整性总判定：PASS WITH EXECUTOR MISMATCH — 该不一致正是本轮 S5 修复对象，未被掩盖。**
