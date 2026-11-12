# RQ_DAJF_V1 收口报告：DA-JS v1 三策略真实对照（E04，18 执行，零超支）

**状态：批次完成。126/150 调用，373,146/1,000,000 tokens，¥2.05/¥4。192 HOLD 未动。**

## 1. 结论（先给结果）

**持续故障条件下：DA-JS-v1 (0.545) > Proposed R→π (0.334) > Static (0.000)，+21.1pp。**

| 策略\条件 | persistent Q_merge | natural Q_merge | C (calls/¥) | L (s) | 按期 | Joint Success |
|---|---:|---:|---:|---:|---:|---:|
| Static | **0.000** (3×0.000) | 0.455* | 6.0 / ¥0.099 | 72 / 102 | 6/6 | **0/3** |
| Proposed (R→π) | 0.334 (0.273/0.273/0.455) | 0.303* | 8.0 / ¥0.132 | 146 / 100 | 6/6 | **0/3** |
| **DA-JS-v1** | **0.545 (3×0.545)** | 0.303* | 10.0 / ¥0.157 | 149 / 97 | 6/6 | **3/3** |

\* natural 条件三臂代码完全相同（全部 `merge:ok`、6 调用），臂间差异是抽样噪声；合并基线 **0.354**（9 执行池化）。不得把 0.455 vs 0.303 报告为策略效应。

Joint Success = Q_merge≥0.5 且按期（240s）。

## 2. 机制验证（全部按设计触发，6/6）

- 注入 15 次（9 个 persistent 基座 merge + 6 次 R 重掷），`injected_calls=15` 与设计一致。
- Static：`anomaly:no_recovery` 3/3，Q=0（无恢复 → 不可用输出，但 L 最短 72s）。
- Proposed：`R:fail → π(qwen→ds):ok` 3/3。
- DA-JS-v1：`decide:LOCAL_R(rem≈190s) → R:fail → escalate:Z2_split_R → Z2:ok(n=29/32/36)` 3/3。

## 3. 四个发现

1. **argmax 选择被真实结果验证**：估计表 Z2 Q_hat=0.545 → 实测 0.545（三 rep 完全一致）；π Q_hat=0.500 → 实测仅 0.334（表是 ds→qwen 方向测的，本次是 qwen→ds 反向）。DA-JS 选 Z2 而非 π 的决策带来 +21.1pp。
2. **Z2 恢复超过自然基线**：Z2 并集 0.545 > 池化自然基线 0.354。结构化分片合并（29–36 条事实）比单次大合并（22–26 条）保留更多 Gold 槽位——恢复动作同时是质量升级。
3. **π 恢复可达性但不达质量线**：π(Q≥0.5) 0/3 vs DA-JS 3/3。
4. **R 探针在持续故障下 6/6 全失败**（浪费 1 次调用后升级）——与表 success_rate(persistent)=0 一致；表驱动的"先验持久型直接跳过 R"是下一步候选（需故障类型探测器）。

## 4. 成本-收益

| 对比 (persistent) | ΔQ | ΔC | ΔL | Q/额外调用 |
|---|---:|---:|---:|---:|
| DA-JS vs Proposed | +21.1pp | +2 调 (+¥0.026) | +3s | +10.6pp/调用 |
| DA-JS vs Static | +54.5pp | +4 调 (+¥0.059) | +77s | +13.6pp/调用 |
| Proposed vs Static | +33.4pp | +2 调 (+¥0.033) | +74s | +16.7pp/调用 |

Pareto（persistent）：Static 占 C/L 前沿但 Q=0 不可用；Proposed 与 DA-JS 互不支配（C vs Q），但仅 DA-JS 达到质量线。

## 5. 诚实声明

- n=3，探索性非确证性（3/3 方向一致，无法做 sign-flip p）。
- 评分口径：E04 Gold 11 槽、采纳的 merge 段事实、归一化 quote/value 包含——与 RQ_DYN_3ARM_V2 冻结口径一致（已复现 0.697/0.636/0.545 验证规则）。Q_report 作次级诊断（报告段改写导致偏低，三臂同受影响）。
- 本管线 merge 提示词输入截断 3000 字符（三臂一致）；绝对 Q 低于 v2 管线，内部对比不受影响。
- 估计表修正候选：LOCAL_pi(qwen→ds, merge) Q_hat 0.500→0.334。

## 6. 文件

- 冻结：`RQ_DAJF_FREEZE.json`（含 sha256 清单）
- 评分：`rq_dajf_score.py` → `RQ_DAJF_SCORED.json`
- 执行：`rq_dajf_runner.py`、`rq_dajf_config.json`、`rq_dajf_runs/`（ledger/outputs/18 记录）
- 日志：`RQ_DAJF_RUN.log`

**未修改任何质量门/评分规则/成本口径；负结果（π 未达线、R 探针 6/6 失败、natural 臂间噪声）全部保留。**
