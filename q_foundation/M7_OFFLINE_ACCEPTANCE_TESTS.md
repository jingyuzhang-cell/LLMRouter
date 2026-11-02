# M7-2E: 离线验收测试与结果（Offline Acceptance Tests）

**测试**: [m7_acceptance_tests.py](m7_acceptance_tests.py) | **结果**: **33/33 PASS（exit 0）** | 零模型调用

操作员九条验收标准全部转为可执行断言，另加第 10 组稳定性/泛化边界测试。

---

## 验收结果对照表

| # | 操作员验收标准 | 测试断言 | 结果 |
|---|---|---|---|
| 1 | 相同状态输入 → 确定性决策 | 重复调用决策哈希一致；节点/边元组顺序打乱后决策内容不变 | PASS ×2 |
| 2 | 不产生非法 DAG 或循环依赖 | apply_split 后无环断言；子节点单血统；下游同时消费双子验证器；上游不健康时禁止拆分（故障继承风险） | PASS ×4 |
| 3 | 不重复执行已完成节点 | assignments 永不含 done 节点；重试目标仅为 failed 节点（运行时断言兜底） | PASS ×2 |
| 4 | 不违反并发/预算/时延约束 | 紧预算拒绝高成本候选并记录原因；紧时延拒绝；槽超订检出；引擎仍返回可行决策 | PASS ×4 |
| 5 | 未知故障不强制分类 | 未知签名@attempt1 → 仅保守重试（候选集不含任何 Z/SWITCH/持久退出）；@attempt2 → stop_unclassified；视图标注 unknown | PASS ×3 |
| 6 | INCOMPLETE 不自动赋 Q=0 | 非 COMPLETE-able 候选 dq_hat 全为 None；任何候选不出现数值 0 质量 | PASS ×2 |
| 7 | 单项收益与交互效应分别记录 | 三对交互项齐备；Z×R 为 JOINT_MODELED（非可加）；NO_EVIDENCE 显式为零；校准审计串附 n 与证据级 | PASS ×4 |
| 8 | Pareto 不可比时不强行唯一最优 | priced_recovery 机制检出；前沿≥2 成员返回；forced_unique=False；chosen 标注为陈述偏好推荐 | PASS ×4 |
| 9 | 决策记录预测值/实际值/误差 | 校准点 vs 语料观测：split 1.00 vs 6/6；persistent-retry 0.03 vs 1/17；transient-retry 0.76 vs 22/29（均 |err|≤0.03）；每条预测携带 n 与证据级 | PASS ×4 |
| 10 | 稳定性与泛化边界（附加） | 空 DAG、全 done、零预算、多故障并发（确定性） | PASS ×4 |

## 验收过程中抓住并修复的两个真实缺陷

1. **净额/总额预算混用**（验收#4 抓住）：约束过滤曾用净额 ΔĈ（split = +600 tok）做可行性判断，遮蔽了 2 次子调用 ~5,000 tok 的总额预留。修复：`reserve_calls`（GROSS）独立字段 gating 约束，`dc_hat`（NET）仅用于比较与报告。**这是 net-vs-gross 预算会计错误，若未抓住会在紧预算下静默超支。**
2. **拆分后状态不一致**（冒烟测试抓住）：`apply_split` 只更新 edges 不更新下游节点的 `parents` 字段，导致就绪集判定失真。修复：双表示同步更新。

## 验收#9 的诚实边界（重要）

校准常数派生自同一语料，因此该项是**自洽性审计**而非前瞻验证：
- split 恢复概率 1.00 的 n=6（LOW_N）——六个配对恢复无失败，但置信区间宽；
- persistent-retry 0.03 的分母含 R6 n4 唯一反例（其存在已驱动 R_1′ 阶梯设计）；
- 三个校准点与观测频率的误差 ≤0.03，说明引擎的预测账本与语料事实一致，可支撑审计回路。

**V1.1 规则与全部校准常数保持 PRELIMINARY。离线验收 33/33 ≠ 生产验证。** 升级路径：前瞻批次（MVR_V1 级）→ 按 Feedback Schema V1 采集 → 回放器重算校准 → 证据级从 PRELIMINARY 升 REPLICATED。

## 典型决策示例（引擎实际输出，H1 G2 复现状态）

```
状态: e1_chk (verification, glm53) 第1次失败 contract，双亲 entity_facts+timeline
视图: merge_interface/persistent/HIGH
候选:  exit_node      p=0.00 dC=0     GROSS=0 calls
       ladder_exit    p=0.03 dC=+2500 GROSS=1 call   (R_1′)
       split_retry    p=1.00 dC=+600  GROSS=2 calls  (dC_Z=2800−1×2200)
前沿:  全部三个（priced_recovery 机制）
选择:  split_retry（陈述偏好：可行 → 恢复概率 → 成本 → 时延）
       forced_unique=False —— 选择是推荐，不是唯一最优证明
拆分:  e1_chk_a←(e1_fin), e1_chk_b←(e1_tl)；e1_rpt 消费双子；无环断言通过
```
