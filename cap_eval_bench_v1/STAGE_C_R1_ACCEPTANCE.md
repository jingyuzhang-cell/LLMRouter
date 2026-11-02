# Stage-C-R1 验收报告（唯一交付）

**日期**: 2026-10-30
**性质**: 零模型调用（全部结论来自确定性适配器驱动的生产路径测试）。真实 API HOLD。
**改动对象**: 生产代码 `integration/six_arm_scheduler.py`（六臂决策层，重写）与 `integration/stage_c_r1.py`（共享执行器，新建，真实路径经 auth gate FAIL-CLOSED）；预置的独立演示程序 `stage_c_r1_engine.py` 与其测试已删除——所有验收经由生产入口 `run_arm()` 完成。冻结历史（stage_c_runs/、144-run 结果、账本）未触碰。

---

## 1. 八项验收 PASS/FAIL 与证据（8/8 PASS，日志 `stage_c_r1_runs/ACCEPTANCE_LOG.json`）

| # | 验收项 | 判定 | 关键证据 |
|---|---|---|---|
| A1 | 六臂独立决策接线 | PASS | 6 个注册决策器驱动同一执行器；决策指纹（Z/R/π/调用序列）成套记录 |
| A1b | FIX-1 弱基线标记 | PASS | Static-Parallel 全程 `baseline_type='no-recovery weak baseline'`，attribution_note 禁止把其 Q 差归因联合优化 |
| A1c | FIX-2 真实 R 比较 | PASS | R-only rationale 记录合法 R 族规模、argmax 与 runner-up 的 U 值（非机械最小集） |
| A2 | 行为分化 | PASS | 四场景故障套件（单瞬断/双瞬断/持续contract/紧截止期）下 **5/6 组物理轨迹签名互异** |
| A3 | Transport 恢复+多次异常 | PASS | 单瞬断：5 个自适应臂全部 COMPLETE；双瞬断：Joint 经 2 轮有界反馈恢复而 SimpleDyn 耗尽；持续 contract：**仅 Joint(Z,R,π) 经 SPLIT_VERIFY 完成** |
| A4 | K_m 排队/Makespan/截止期/成本 | PASS | K=1 排队等待 18.0s vs K=2 等待 0s；并行 makespan 50.8s < 串行时延和 64s；deadline 与 token 成本逐 run 记录 |
| A5 | 缓存/阻断/版本/多父 | PASS | e1_chk 故障时健康节点全部恰好执行 1 次、故障节点 v2；多父节点 prompt 含双父（v 标注）且无非父泄漏 |
| A6 | 评分一致性 | PASS | 评分器确定且内容驱动（E1 事实文本 Q=0.714 vs E2 事实文本 Q=0.143），与臂标签无关 |
| A7 | 异构 π 与资源上限 | PASS | 双模型真实使用；任意时刻每模型并发 ≤ K_m=2 |
| A8 | 任务与账本完整性 | PASS | 12/12 冻结任务（文档齐全、silver 非空、deadline 在位）；8 份 SC 原始 PDF SHA256 全部匹配 manifest；trace 含 rounds+calls（model/latency/wait/usage/version/attempt），预算核算与逐调用求和一致 |

## 2. 六臂逐状态 Z/R/π 与物理动作指纹（SC-E1，故障套件）

| 臂 | 单瞬断@tl | 双瞬断@tl | 持续contract@chk | 紧截止期@tl |
|---|---|---|---|---|
| Static-Parallel | 不恢复，INCOMPLETE | 同左 | INCOMPLETE | INCOMPLETE |
| Simple-Dynamic | R={tl}, 升级 flash→glm53, COMPLETE | 重试1次耗尽, INCOMPLETE | INCOMPLETE | COMPLETE |
| R-only | R=argmax{tl}（保留 flash π）, COMPLETE | 多轮重试 COMPLETE | INCOMPLETE | COMPLETE |
| π-only | R={tl}+剩余π重优化, COMPLETE | COMPLETE | INCOMPLETE | COMPLETE |
| Joint(R,π) | R×π 枚举 argmax, COMPLETE | 2 轮反馈 COMPLETE | INCOMPLETE | COMPLETE |
| Joint(Z,R,π) | 同上 + Z=KEEP（瞬断不构成结构依据） | 同左 | **Z=SPLIT_VERIFY(e1_chk→_a/_b)，唯一 COMPLETE** | 同 Joint(R,π) |

三处修复的落点：FIX-1（Static 标记+归因限制）、FIX-2（R 族枚举+目标函数比较，rationale 留痕）、FIX-3（Z 空间=冻结五算子；SPLIT_VERIFY 需 verification/timeline 合同+≥2 异类健康父+血统可分；MERGE 需同 kind 同父且焦点重叠——本任务集两 extracts 节点文书焦点不相交→非法；ADJUST_DEP 需传递冗余边——4 个 SC DAG 均无→非法；SUBSTITUTE_EV 需同事件备选文书——无→非法；无合法非 KEEP 时保留 KEEP 并记录）。

## 3. Transport 恢复与多次异常

- 瞬断（transient，重试可信）：不触发可信度衰减，最小重试即最优——五自适应臂 COMPLETE，JointZ 保持 KEEP（结构变更无依据，FIX-3 纪律）。
- 双瞬断：Joint 类以第 3 次重试恢复（有界反馈环，MAX_RECOVERY_ROUNDS=3）；SimpleDyn 受单节点 2 次尝试上限约束而耗尽——真实策略差异。
- 持续系统性失效（contract：宽域节点端口违约）：同模型重复重试按 SUCCESS_DECAY=0.5 衰减（换模型重置；分裂节点为窄域新节点无历史）。首轮后 U_keep=0.142 < U_split=0.284 → JointZ 选择 SPLIT_VERIFY 并真实重构 DAG（e1_chk 移除，e1_chk_a/_b 各消费一条父血统，子节点重接），是唯一完成臂。
- 失败阻断与解除：故障期下游 blocked，恢复后自动解阻塞；无未记账调用、无静默重试。

## 4. K_m 排队 / Makespan / 截止期 / 成本（虚拟时钟）

| 配置 | 总排队等待 | Makespan | 说明 |
|---|---|---|---|
| K_m=1/1 | 18.0s | 63.8s | 资源竞争真实产生排队 |
| K_m=2/2（冻结值） | 0.0s | 50.8s | 并行收益 13.2s vs 串行 64s |
| 串行时延和 | — | 64.0s | 并行核优于串行的下界对照 |

每 run 记录 makespan、deadline_s=1800、deadline_met、token 成本；并发上限验证 ≤ K_m。真实执行的时延将由 Meter 的实测 latency_s 进入同一内核。

## 5. R、π、Z 三维实际可辨识性

- **R 可辨识** ✓：Static(∅) vs SimpleDyn({f}) vs R-only(族argmax，可>单点) vs Joint(族×π argmax)。持续故障下闭包差异体现为重试轮数与成本分层（9.1K/10.0K/12.3K tokens）。
- **π 可辨识** ✓：π₀ 冻结异构（timeline/reasoning=flash，其余 glm53，六臂统一）。瞬断下 R-only 保留 flash 重试 vs SimpleDyn/π-only/Joint 升级 glm53，成本/时延物理可分。
- **Z 可辨识（有条件）** ⚠：本任务集仅 SPLIT_VERIFY 存在合法实例（verification 节点双异类父），且只在**持续系统性失效**状态下优于 KEEP；MERGE/ADJUST_DEP/SUBSTITUTE_EV 在 4 个 SC DAG 上全部非法。结论：Z 维度的真实实验价值集中于 contract 类故障场景；若实验只含 transport 瞬断，Joint(Z,R,π) 与 Joint(R,π) 物理等价（如实声明）。
- 已知物理等价对：{π-only ≡ Joint(R,π)} 在当前故障套件上动作一致（决策算法不同：贪心 vs R×π 枚举，rationale 留痕可审计）。

## 6. 冻结任务与历史账本完整性

- 12/12 任务（T-R1/R2/P1/P2/P3/D1/D2/M1 + SC-E1..E4）：证据文档全部在位（evidence/texts 或 stage_c_evidence/text），silver 评分参考非空（SC 6-7 facts/任务，T-* 在 `silver` 键下），deadline_s=1800 全部在位。
- 8 份 SC 原始 PDF 的 SHA256 与 manifest 逐一匹配（独立来源核验）。
- 历史不触碰：stage_c_runs/（652 条最终账本）、失败批次、144-run 冻结结果未修改、未重跑；本报告全部结论零模型调用。

## 7. 最小公平配对实验矩阵与费用上限（建议，待授权）

六臂共用同一执行器、冻结 DAG、同故障注入点、同 K_m、同证据与评分器；π₀ 统一；无任何为分化而设的参数。

| 维度 | 取值 |
|---|---|
| 任务 | SC-E1、SC-E3（DAG 最丰富：双血统 verification + 双 extracts 分支） |
| 故障场景 | S1=transport 瞬断@timeline（left=1）；S2=contract 持续@verification |
| 重复 | S1×2、S2×2 |
| 臂 | 6 |
| **运行数** | 2 任务 × (2+2) 场景重复 × 6 臂 = **48 runs** |
| 调用上限 | 每 run 健康 7 + 恢复 0–4 → **max_calls = 550**（48×约9.3 + 12% 余量） |
| Token 上限 | 按历史实测 888 tok/call → 保守 **max_tokens = 600,000**（550×~1.1K） |
| 分模型 | glm53 ≤ 300 calls / 380K；glm53flash ≤ 250 calls / 220K |
| 现金 | ¥0（订阅） |

预期判读：S1 区分 R/π 维度（恢复范围与模型升级），S2 隔离 Z 维度（仅 JointZ 可完成）。若 S1 中 {π-only, Joint(R,π)} 动作一致，按第 5 节等价性声明解读。

## 8. 下一阶段真实实验准入结论

**具备准入条件**：生产路径已满足操作员三项实质性标准——六臂经不同决策算法控制同一执行器（A1/A2）；执行异常真实改变恢复范围、剩余模型分配与合法 DAG 结构（A3，SPLIT 在持续失效下真实触发）；资源竞争与并行时延被正确测量（A4）。12 条任务与账本链完整（A8）。

**限制（如实声明）**：确定性适配器的 Q 值不代表模型真实质量（适配器输出为真实证据文本的声明性摘录，仅用于机制验收）；Z 维度仅 contract 场景可辨识；{π-only, Joint(R,π)} 在弱故障下物理等价；真实执行前需按第 7 节七字段授权（batch 建议 `stage_c_r1_v1`）。

**模型调用 HOLD 维持，等待明确授权。论文暂停。**
