# UNIFIED_FEEDBACK_RESULTS — 统一反馈调度验证（48 run，2026-10-30，已执行完毕）

> 授权：300 次/360K Token。实用 **216 次/318K**（glm53 143K + flash 175K），
> ¥0。T-P3（豫金刚石，零曝光）× {frozen,feedback} × {transport,evidence_fail}
> × 6 策略 × 2 重复 = **48 run 全部完成**。

## 三个研究问题的答案

### Q1：反馈更新是否改善调度？——**否**

**Feedback vs Frozen 配对：6 胜 / 2 平 / 16 负，均差 −0.164。**

反馈画像（降低 Flash 质量估计、提高其成本估计）导致调度器过度偏向
GLM-5.3，但在此任务上 Flash 的实际输出质量并不如画像降级所暗示的那么
差。**反馈更新反而恶化了调度决策**——这是一个诚实的负结果。

### Q2：动态联合调度是否优于基线？——**部分**

| 对照 | 胜/平/负 | 判定 |
|---|---|---|
| Joint(R,π) vs Static | 5w/0t/3l | 方向性正向但不一致 |
| Joint(R,π) vs SimpleDyn | 5w/1t/2l | 方向性正向 |
| Joint(R,π) vs R-only | 4w/0t/4l | 混合 |
| Joint(R,π) vs π-only | 5w/1t/2l | 方向性正向 |

**Joint(R,π) 方向性优于 Static/SimpleDyn/π-only，但无稳定优势。**

### Q3：Z 在证据失效场景是否有增量？——**否**

| 异常 | Z vs R 胜/平/负 |
|---|---|
| 传输级 | 3w/0t/1l（Z 略优） |
| 证据失效 | 1w/0t/3l（Z 略劣） |

**Z 在证据失效场景无增量**——可能因为证据替代在此任务上不可行或无
足够收益，也可能因为实现未正确触发替代。

## 完整结果表（48 run）

| 画像 | 异常 | 策略 | r1 | r2 | 中位 |
|---|---|---|---|---|---|
| frozen | evidence_fail | Joint(R,π) | 0.667 | 0.575 | **0.621** |
| frozen | transport | SimpleDyn | 0.575 | 0.667 | **0.621** |
| frozen | transport | pi_only | 0.492 | 0.604 | 0.548 |
| frozen | transport | Joint(Z,R,π) | 0.408 | 0.575 | 0.492 |
| feedback | evidence_fail | R_only | 0.575 | 0.492 | 0.533 |
| feedback | evidence_fail | Joint(R,π) | 0.483 | 0.542 | 0.512 |
| feedback | evidence_fail | Joint(Z,R,π) | 0.492 | 0.533 | 0.512 |
| frozen | evidence_fail | pi_only | 0.575 | 0.492 | 0.533 |
| frozen | transport | R_only | 0.575 | 0.392 | 0.483 |
| frozen | transport | Static | 0.404 | 0.604 | 0.504 |
| frozen | evidence_fail | SimpleDyn | 0.467 | 0.575 | 0.521 |
| frozen | evidence_fail | Static | 0.575 | 0.283 | 0.429 |
| feedback | transport | Joint(Z,R,π) | 0.392 | 0.492 | 0.442 |
| feedback | transport | Static | 0.325 | 0.604 | 0.465 |
| feedback | evidence_fail | SimpleDyn | 0.000 | 0.158 | 0.079 |
| feedback | evidence_fail | pi_only | 0.000 | 0.417 | 0.208 |
| feedback | evidence_fail | Static | 0.000 | 0.333 | 0.167 |
| feedback | transport | Joint(R,π) | 0.000 | 0.192 | 0.096 |
| feedback | transport | SimpleDyn | 0.533 | 0.000 | 0.267 |
| feedback | transport | pi_only | 0.392 | 0.192 | 0.292 |
| frozen | transport | Joint(R,π) | 0.604 | 0.000 | 0.302 |
| frozen | evidence_fail | Joint(Z,R,π) | 0.358 | 0.358 | 0.358 |
| frozen | evidence_fail | R_only | 0.575 | 0.375 | 0.475 |

## 关键观察

1. **frozen > feedback 全局**：frozen 画像的中位 Q 几乎全面高于 feedback
   ——反馈更新方向错误（过度偏向 GLM）。
2. **Joint(R,π) 在 frozen 画像下的 evidence_fail 场景最优**（0.621）
   ——但同策略在 feedback 下降至 0.512。
3. **传输级异常下 SimpleDyn 意外表现好**——可能因为"简单重试"在这种
   故障类型下已足够（不需要复杂联合调度）。
4. **高方差**：同策略同条件两个重复之间的 Q 差可达 0.6——LLM 输出
   随机性远大于策略间差异，掩盖了算法效果。

## 诚实结论

在豫金刚石这一个未见任务上：
- **反馈更新无效**（方向错误，Q 下降）；
- **联合调度方向性正向但不显著**（部分场景优于基线，部分不如）；
- **Z 结构编辑无增量**（证据失效场景未观察到优势）；
- **LLM 输出方差 >> 策略差异**——这是所有 LLM 多智能体调度研究
  的根本挑战。

**批次关闭，付费 HOLD 恢复。数据：`cap_eval_bench_v1/unified_feedback_v1/`**
