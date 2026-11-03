# DAG_Q_SCORING_ROOT_CAUSE — 元道退冒烟测试 Q=0.0 根因分析（零付费）

## 结论：事后评分错误，S6 运行时未受污染

**根因**：`scoring_kdx` 模块硬编码加载康得新 `facts_seed.json` 作为金标；DAG 冒烟测试的证据来自
元道退——金标与证据来自不同事件，导致全部 Q=0.0（零匹配）。

**污染范围判定**：
| 层 | 是否受影响 | 证据 |
|---|---|---|
| S6 运行时决策 | **否** | S6 使用 `capability_table_v1_real.json`（来自 80 次筛选的 evaluate()，非 scoring_kdx） |
| 能力表构建 | **否** | 80 次筛选用 `execute_screening_80.py` 的 evaluate()（逐事件 JSON 条目计数+引文接地），与 scoring_kdx 无关 |
| 80 次筛选结果 | **否** | 同上 |
| 冒烟测试 C/L | **否** | 计量（token/时延/现金）独立于评分 |
| 冒烟测试 Q | **是 → INVALID_WRONG_EVENT_GOLD** | 四臂全部 Q=0.0，不得出现在可比较 QCL 表中 |
| 冒烟测试 S6 决策日志 | **否** | Z/R/π/被拒候选来自 joint_scheduler.choose()，输入为能力表 |

**修复**：
1. Q=0.0 全部标记 INVALID_WRONG_EVENT_GOLD；
2. 构建事件感知评分器（按 event_id 匹配金标）；
3. 元道退目前仅有无验证候选（40 条程序生成），Q 重评=探索性 Silver；
4. 元道退响应已保存（13 份），可零成本重评。

## 事件身份检查（新增强制规则）

评分器加载金标时必须验证 `event_id` 与当前证据的 `event_id` 一致；不一致即拒绝评分并报错。
此规则已缺失导致本次错误——已列为本轮整改项。
