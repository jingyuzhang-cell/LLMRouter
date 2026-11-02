# M7-2D: 联合决策引擎规格（Decision Engine Spec）

**引擎**: [m7_decision_engine.py](m7_decision_engine.py)（零模型调用；纯函数决策核心）
**验收**: 33/33 断言通过（[M7_OFFLINE_ACCEPTANCE_TESTS.md](M7_OFFLINE_ACCEPTANCE_TESTS.md)）

---

## 一、接口

```python
decide(state: EngineState) -> JointDecision        # 纯函数，无副作用
apply_split(state: EngineState, node_id: str) -> EngineState   # 执行器侧 Z 变换
classify(node, state) -> {layer, persistence, rate, n, confidence, signature}
split_legal(node, state) -> (bool, [原因列表])       # Z 合法性七条件
pi_switch_legal(node, state) -> (bool, [原因列表])   # π 合法性四条件
```

**输入 `EngineState`（不可变值对象）**：`task_id, dag_version, nodes, edges, budget_remaining, deadline_remaining_s, slots_total/in_use, persistence_table（只读，M6-5 学得）, profile_q（只读，M1）, params`。

**输出 `JointDecision`（不可变，全量留痕）**：

| 字段 | 内容 |
|---|---|
| `fault_views` | 每个故障节点的机制视图 `layer/persistence/confidence` |
| `candidates` | 全部合法候选（含被约束拒绝前的完整集合） |
| `rejected` | 约束拒绝记录（候选名 + 逐条原因） |
| `frontier` | Pareto 前沿候选名列表 |
| `regime` | single_arm_dominance / priced_recovery / quality_tradeoff / single_quality_point / no_fault / empty |
| `chosen` | 所选联合动作（陈述偏好下的推荐） |
| `forced_unique` | False = 前沿不可比，chosen 仅为推荐而非唯一最优证明 |
| `assignments` | 立即执行的 `(node, model)` 列表（不含 done 节点） |
| `split_of` | 需执行器应用 `apply_split` 的节点（若有） |
| 每候选 | `(Z, R, π)` 三元组 + `p_recover / dq_hat / dc_hat / dl_hat` + `reserve_calls` + 校准审计串（`point/n=/level`）+ 三对交互项（`JOINT_MODELED` / `NO_EVIDENCE:0` / `N/A`） |

## 二、算法流程（决策时序）

```
1. 识别故障节点（status=failed）与就绪集（pending 且双亲全 done）
2. 无故障 → 正常执行：返回就绪集分配（当前 π）
3. 每个故障节点：classify() 机制视图
     unknown → 保守通道（一次保守重试；第2次仍未分类 → stop_unclassified）
4. generate_candidates(): 按机制生成联合候选（J_1..J_5 + exit）
     Z 合法性七条件 → split_retry（+ split_retry_switch 若 π 合法）
     persistent → ladder_exit（R_1′：恰好一次同配置重试）（+ ladder_switch）
     transient → retry_same（cap，CANDIDATE）（+ retry_switch 仅系统签名）
5. constraint_filter(): 总额（GROSS）保留检查
     reserve = (candidate.reserve_calls + |ready|) × {2500 tok, 12s}
     拒绝记录原因；dc_hat 是净报告值，永不作为可行性门槛
6. pareto_frontier() + detect_regime()
7. 选择：词典序（可行 → p_recover → dc_hat → dl_hat）；
     前沿>1 → chosen 为陈述偏好推荐，forced_unique=False
8. 输出 assignments（执行器执行）+ split_of（执行器 apply_split 后再次 decide）
```

## 三、关键设计裁决（含缺陷修复记录）

| # | 裁决 | 依据 |
|---|---|---|
| 1 | **总额保留 vs 净额报告分离**：约束用 GROSS（reserve_calls×2500），比较用 NET（dc_hat） | 验收#4 抓住的真缺陷：split 净额 +600 不得遮蔽 2 次调用 ~5,000 tok 总额预留 |
| 2 | 拆分后 `Node.parents` 与 `edges` 同步更新 | 冒烟测试抓住：只改边不改节点字段导致下游就绪判定失真 |
| 3 | 未知签名第二次失败 → 停止（不再无限保守重试） | 政策 C.6 完整语义 |
| 4 | π 仅系统签名（contract/parse）+ attempt 阶梯 | M6-5 Phase E：PI_2 在瞬态故障 5/8 过度触发 |
| 5 | persistent 永不立即退出（先一次同配置重试） | R6 n4 反例的永久地位 |
| 6 | Z×R 恢复概率整体建模（JOINT_MODELED），Z×π/R×π 显式 NO_EVIDENCE:0 | 验收#7：交互不可加 |

## 四、校准常数（只读，附样本量）

见引擎 `CAL` 字典与策略文档 C.2 表。全部标注 `point/n/level`；`switch_dq_factor`（0.76）**n=1**，其产物全部标 UNVALIDATED。升级任何常数需前瞻批次证据（MVR_V1 级，HOLD 不变）。

## 五、与执行器/M6 的集成契约

- **执行器循环**：`decide → 执行 assignments →（若 split_of）apply_split → 更新状态 → decide`。引擎不做 IO、不调模型、不读时钟。
- **反馈接口**：每候选的 `cal` 审计串与决策结果（预测 vs 实际）回写 Feedback Schema V1 的 `prediction_errors` 层（M6-2 字段：what_was_predicted / expected / actual / error_magnitude / lesson）——由执行器负责写入，引擎只产出可审计预测。
- **只读边界**：persistence_table / profile_q / 历史账本为外部输入；引擎修改冻结资产为零。
- **确定性**：无随机源、无时钟依赖、全排序迭代；同状态跨进程重启决策一致（sha256 决策哈希可验证）。

## 六、已知限制（如实）

1. `transient_retry_cap=2`、`reserve_per_call_tok=2500`、`reserve_latency=12s` 是设计值非语料拟合，标 CANDIDATE。
2. 恢复概率用 p_recover 作为质量代理（节点级 ΔQ̂ 仅在 π 切换时有量化）；完整 ΔQ̂ 预测需 M1 可靠性维度补全。
3. 校准源自既有语料，验收#9 为自洽性审计，**非前瞻验证**；V1.1 全部规则保持 PRELIMINARY。
4. 多故障同时存在的候选空间按节点独立生成后组合，未做跨节点组合的联合合法性证明（当前语料无此场景）。
