# AUDIT_RERUN_MANIFEST.md — Frozen 200 Corrective Action
# 2026-09-26 | Commit pending

## 审计发现

### 缺陷 FZ-1:Single LLM 故障任务成本核算错误

**位置**:`frozen200_run.py` L153-156

**问题**:Single LLM 的 60 个故障任务被标记为 `ok=False, used=0, lat=0`,未实际
调用模型也未计入重试成本。对照主面板(`benchmark_run.py` L142)与多种子实现
(`multi_seed_run.py` L142),二者均正确计为 `used = clean_used × 2`(调用+重试)。

**影响范围**:
| 指标 | 修正前 | 修正后 | 变化 |
|---|---:|---:|---|
| Single f30 avg cost | 434 | **802** | +85% |
| Pareto front(f30) | {Single(C=434), Dynamic(C=2530)} | {Single(C=802), Dynamic(C=2530)} | 结构不变,Single 仍在前沿 |
| Q(B) 曲线(f30) | Single 全档领先 | B≤2000 Single 领先;B≥2500 Dynamic 接近(0.302 vs 0.397) | 交叉推迟但不消失 |
| HV 独占贡献 | Single 偏大 | Single 减小 | 需重算 |

**不需要修正的部分**:
- Single 的 Q 值(0.3967):全部故障任务失败这一假设与主面板一致
- Static/Dynamic 臂的 Q、成本、时延:故障覆盖机制经审计正确
- 主面板(120 题)全部数字:成本核算正确
- Exact Pareto(18 配置):无 Single 臂,不受影响

### 修复方案:零模型调用(后处理修正)

Single 的 Q 不变(故障任务仍全部失败),仅需将 `used` 从 0 修正为
`clean_avg × 2 ≈ 1226`。无需调用模型,只需:
1. 修改 FROZEN200_RESULTS.json 中 Single 故障任务的 used/lat 字段
2. 重新计算 Pareto、HV、Q(B) 等全部下游统计

## 重运行清单

| # | 项目 | 是否需模型调用 | 理由 |
|---|---|---|---|
| FZ-1a | 修正 Single faulted used=0→1226 | **否** | 后处理数值修正 |
| FZ-1b | 重算 Pareto/HV/Q(B)/退化率 | **否** | 纯计算 |
| FZ-1c | 重算调度器 32-state grid | **否** | 纯计算 |

**总计新增模型调用:0**

## 不修正的项目(经审计确认正确)

| 项目 | 审计结论 |
|---|---|
| 主面板 120 题 Single fault cost | ✅ 正确(2×charge) |
| 主面板 120 题 Static/Dynamic fault | ✅ 正确(修正后) |
| 多种子 20260924/25 全部 | ✅ 正确(修正后) |
| Exact Pareto 18 配置 | ✅ 正确 |
| DV/FR 池扩展 | ✅ 正确 |
| Frozen 200 Static/Dynamic 臂 | ✅ 正确 |
| Frozen 200 Single Q 值 | ✅ 与主面板一致 |
| Workflow Scheduler 56.0% | ❌ 来源不明,维持排除 |

## 状态标记(修正后)

| 实验 | 状态 |
|---|---|
| 主面板 120 题(修正后) | VALIDATED |
| 多种子 24/25(修正后) | VALIDATED |
| Exact Pareto 18 配置 | VALIDATED |
| DV/FR 池扩展 | VALIDATED |
| Frozen 200 Static/Dynamic | VALIDATED |
| Frozen 200 Single Q | VALIDATED |
| Frozen 200 Single cost | **CORRECTED**(本次修正) |
| Frozen 200 Pareto/HV/Budget | **CORRECTED**(待重算) |
| 修正前旧数据(+20pp 等) | INVALIDATED |
| Workflow Scheduler 56.0% | EXCLUDED(来源不明) |
