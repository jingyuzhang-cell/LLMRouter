# BUDGET PROTOCOL V2（任何 V2 模型调用前冻结）

## 范围
仅限江苏舜天（600287）单事件修复轮（PILOT V2）。不新增事件、不运行多目标优化、不改动
r3_own_pool 冻结实验。第一轮账本 `model_call_ledger.jsonl` 冻结只读；V2 使用
`model_call_ledger_v2.jsonl` + `model_call_ledger_v2_responses.jsonl`（逐调用即时落盘）。

## 口径定义（消除第一轮的歧义）
1. **实际（settled actual）**：API usage 返回的 input+output token，逐调用累计。失败/截断调用的实际消耗照计。
2. **在途预留（in-flight reservation）**：单次调用发出时的 max_tokens。调用串行，故任意时刻在途预留 ≤ 单次 max_tokens；完成即结算为实际，未用完的预留不复存在。
3. **最保守累计口径（conservative）**：实际 + 历次（含失败）max_tokens 之和。仅披露不执法；第一轮该口径为 36,564（超 30,000，超限部分来自已结算调用的未用预留，已在 PILOT_REPORT 披露）。

## 硬性执法（程序化，Meter v2）
- 调用次数 ≤ 档位上限；
- 每次调用前检查：`实际(前) + 本次max_tokens ≤ 档位保证线`，违反立即抛 BudgetExceeded 停止；
- 触发上限立即停止并汇报，不得为完成率突破；
- 每条账本记录同时写入 cumulative_settled_actual 与 cumulative_conservative，两种口径全程可审计；
- 环境连通性探针（第一轮 6 次 ~388 token）已披露，V2 开始后一切调用必须入账本。

## 档位（待授权选择，未授权前零调用）
| 档位 | 调用上限 | 保证线（实际+在途） | 内容 |
|---|---|---|---|
| A 最小 | 18 | 30,000 | 规划(≤2) + 全图执行(5-6节点) + 3类型×2模型×1次对照 + 基线(1) + 修复预留 |
| B 推荐 | 23 | 36,000 | A 基础上 extraction/verification 各加 1 次重复（稳定性），检索类单次 |

## 预估（按第一轮实测每节点均值）
规划 ~1.6K/次；全图 ~7.7–8.7K；对照：extracts ~2.8K/次、extraction ~1.0K/次、verification ~1.8K/次；
基线 ~2.1K；修复预留 ~2.5K。A 档典型 ~26K/最坏 ~29K；B 档典型 ~32K/最坏 ~35K。
