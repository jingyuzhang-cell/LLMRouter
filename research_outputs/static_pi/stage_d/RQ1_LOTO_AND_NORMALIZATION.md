# RQ1 LOTO 覆盖率审计与终端质量归一化（零调用）

## 一、LOTO 覆盖率

### 1. 五折类型覆盖（V1.5 类型）

| 留出 | 训练 | extract | timeline | merge | reason | verification | report |
|---|---|---|---|---|---|---|---|
| E04 | E05–E08 | ✓ | ✓(E05) | ✓ | **✗** | ✓(E07) | ✓ |
| E05 | E04,E06–E08 | ✓ | ✓(E04) | ✓ | ✓(E04) | ✓ | ✓ |
| E06 | E04,E05,E07,E08 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| E07 | E04–E06,E08 | ✓ | ✓ | ✓ | ✓ | ✓(E04) | ✓ |
| E08 | E04–E07 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

- timeline：E04/E05 两任务；留出 E04 或 E05 时训练仅 1 个 → 标注 single_task。
- merge：E05/E06/E08；训练至少 2 个。
- verification：E04/E07；留出其一训练仅 1 个 → single_task。
- reason：仅 E04；留出 E04 时训练 **0 个** → non_estimable；其余 4 折训练仅 1 个（E04）→ single_task。
- extract/report：5/5。

### 2. 预注册回退

1. 训练 ≥2 任务且 ≥3 节点 → 类型条件均值；
2. 训练 1 任务 → 类型条件均值 + single_task 标记；
3. 训练 0 任务 → 全局训练均值；
4. 该类型在全折均不可估计 → non_estimable，单独报告。
禁止：用留出任务自身、用重复次数冒充任务数、把 non_estimable 当 0。

### 3. 结论

V1.5 的 timeline 从 1 个任务扩到 2 个，verification 2 个，merge 3 个；**reason 仍是单任务（E04）**。若 reason 是核心假设，必须扩充至少 2 个计算/推断型任务；否则只能报告探索性结果。

## 二、终端质量归一化

### 1. 事实计数

| 任务 | 原始 | 派生 | 唯一槽位 | 节点测量槽位（含重复引用） |
|---|---|---|---|---|
| E04 | 29 | 6 | 35 | 37 |
| E05 | 11 | 5 | 16 | 22 |
| E06 | 12 | 5 | 17 | 22 |
| E07 | 11 | 6 | 17 | 23 |
| E08 | 10 | 5 | 15 | 20 |
| 合计 | 73 | 27 | 100 | 124 |

差异来源：同一事实在多个下游节点的 fact_ids 中重复引用。**终端唯一槽位用 100；节点级测量用 124**，两者都报告，不得混用。

### 2. 聚合

- **主口径 task-equal**：`Q = mean_t(TP_t / slots_t)`；每任务等权。
- **敏感性 fact-equal**：`Q = ΣTP / Σslots`；E04 占 35%，会支配结果。
- 原始 TP 必须同时报告；不得只报归一化百分比。

### 3. +1 TP 门槛

- 保留 **+1 TP 绝对门槛**；不下调为 +0.5 或百分比。
- E04 的 35 槽位：+1 TP=+2.9%；task-equal 均值中 E04 的 +1 TP 贡献 0.2×2.9%=0.58%。
- 主结论必须同时满足：task-equal ΔQ>0、E04 参照 +1 TP、fact-equal 同向。
- 若仅 fact-equal 显著、task-equal 不显著 → 判为"E04 驱动"，不判正面。
- 不降门槛；若 5 任务下 +1 TP 的 task-equal 变化太小，应扩充任务（B/C），不是降门槛。

### 4. 五分量

value_match、evidence_localization、evidence_support、contract_valid、UNKNOWN_correct、critical_errors、parse_success 分别报告；UNKNOWN：答 UNKNOWN=1，断言具体值=0，未答=0；不得把 UNKNOWN 当 TP。

### 5. 结论

归一化只改聚合权重，不改事实/评分器/门槛。V1.5 以 task-equal 为主、fact-equal 为敏感性；方向不一致时不做正面结论。
