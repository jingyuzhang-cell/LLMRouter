# STAGE_C_R7 — 信息传播可靠性审计（P0 完成）

> 零模型调用。基于 R6 20/20 run 的原始响应、账本与运行器源码分析。

---

## 核心发现：R6 结果被基础设施 Bug 严重扭曲

### 根因：两个运行器有不同的上游数据传递逻辑

| 运行器 | 上游传递方式 | 效果 |
|---|---|---|
| `stage_c_r6_runner.py`（原始） | `call_with_upstream` 包装器在每次节点调用时更新 | **✓ 正常**：n3 收到 n2 的日期 |
| `stage_c_r6_fix.py`（补跑用） | 上游在 `execute_dag` **返回后**才更新 | **✗ 断裂**：n3 永远收不到上游数据 |

### 影响范围

| 运行来源 | Run | n3 收到日期？ | 350天计算？ | 结论 |
|---|---|---|---|---|
| **原始 runner** | Simple-Dyn r1/r2, π-only r1, Joint r1, R-only r1 | ✓ | **✓ 5/5** | 信息链完整→100% 成功 |
| **fix runner** | π-only r2, Joint r2（补跑） | ✗ | ✗ 0/2 | 上游断裂→0% 成功 |
| **fix runner** | SC-E3 全部 10 个 run | ✗ | ✗ 0/10 | 上游断裂→0% 成功 |
| **原始 runner** | R-only r2 | —（n3 未执行） | — | 执行中断 |
| **by design** | Static r1/r2 | —（不恢复） | — | 无恢复基线 |

### 修正后的真实结果

**当信息传播正常时（原始 runner 的 SC-E1 数据）**：

| 臂 | n | n3 收到日期 | 350天计算 | dQ_recovery |
|---|---|---|---|---|
| Simple-Dynamic | 2 | 2/2 | **2/2** | 应>0 |
| R-only | 1 | 1/1 | **1/1** | **0.5** |
| π-only | 1 | 1/1 | **1/1** | 应>0 |
| Joint(R,π) | 1 | 1/1 | **1/1** | 应>0 |
| Static | 0 | 0（不恢复） | 0 | 0 |

**关键洞察**：350天跨文档时间推导在信息链完整时**100% 成功**（5/5）。R6 报告的"R-only 仅 1/4 成功"实际上是因为 12/20 个 run 使用了有 bug 的 fix runner。

### 对 R6 结论的修正

| 原结论 | 修正后 |
|---|---|
| R-only 1/4 成功 | **所有恢复臂在信息正常时 100% 成功** |
| 联合优化无增量 | **无法判断**（SC-E3 全部被 bug 影响） |
| 下游事实恢复不稳定 | **稳定**（当信息传播可靠时） |
| 信息传播是瓶颈 | **确认**，但原因是基础设施 bug 而非架构缺陷 |

---

## P1：信息完整性合同（设计）

```yaml
node: n3_timeline
contract: temporal_derivation
requires:
  - port: doc_extracts
    from: n2_extracts
    must_contain:
      - date: "事先告知书送达日期"
      - date: "处罚决定书送达日期"
    validation: both dates must be present in upstream
on_missing:
  action: mark_upstream_missing
  do_not: fabricate, guess, or pass empty
  block_downstream: true
output:
  - field: date_interval
    value: computed from two dates
    lineage: preserve both source dates and doc_ids
```

## P2：R×π 可辨识性（受 bug 影响需重评）

在修复信息传播后需重新评估。当前判断：
- π 维度：GLM/Flash 切换仍不可达（预算设计问题持续存在）
- R 维度：最小闭包选择在 bug 修复后可能不再是唯一合理选择
- Joint 退化：需要重新测试

---

## 下一步必须完成

1. **修复 `stage_c_r6_fix.py` 的上游传递**（将 `call_with_upstream` 逻辑移植到 adapter 类中）
2. **P3 回归验收**（使用确定性假模型覆盖信息传播场景）
3. **重新评估 R×π 可辨识性**（在信息传播可靠的前提下）
