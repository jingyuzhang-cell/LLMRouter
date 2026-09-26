# FROZEN_EVAL_PROTOCOL

## 状态
FROZEN_BEFORE_EXECUTION — 本文件在任何模型调用之前锁定。

## 目的
在所有方法、阈值、预算规则和候选策略冻结之后，在从未参与开发、阈值选择或参数调优的独立任务集上一次性验证三个核心结论。

## 任务集
- 文件：`FROZEN_TASKS_200.json`（SHA256: `03565a349139daacd9cc3df07c00ac7a3242d7151d290cbc64e9cf233c0cd48e`）
- 来源：TAT-QA train（195）+ dev（5），SHA256 排序确定性选取
- 排除：所有已参与任何实验的 615 个任务 UID（零重叠，已验证）
- 复杂度分布：1-2 步 173 / 3+ 步 27
- 筛选条件：answer_type=arithmetic, derivation 可解析, ≥2 非常数操作数, evaluable

## 冻结配置（不可在任何新任务结果之后修改）

| 项目 | 冻结值 |
|---|---|
| 模型池 | Qwen2.5-7B-Instruct (medium) / Qwen2.5-14B-Instruct-GPTQ-Int8 (large) / Qwen2.5-Coder-7B-Instruct (coder) |
| 生成配置 | temperature=0, top_p=1, max_tokens=512 |
| 评分器 | extract_value + tolerance max(1e-4, 1e-4·\|gold\|)；DAG 用 exec_calc |
| Mono 提示 | 与 decomposition_benchmark 冻结版本逐字一致 |
| DAG 提示 | eprompt v1 + sprompt v1（与 decomposition_benchmark 一致） |
| 分解门控 | LogisticRegression, 12 特征, τ=0.5, seed=20260921 |
| 预算规则 | max(200, 1.2 × Static 实际 tokens) |
| 失败策略 | 抽取解析失败 → DAG 判错，不重试，不喂 gold |
| 统计 | 配对 ΔQ + 10000 次 bootstrap (seed 20260916) + exact McNemar |

## 验证的方法（一次性运行，全部方法在同一次会话中执行）

| 方法 | 说明 |
|---|---|
| Mono-L | 单体 large 直接作答 |
| DAG-L/M | 强制分解：large 抽取 → medium 推理 → 确定执行 |
| Selective-DAG | 分解门控选择 Mono 或 DAG |

## 预注册读出

1. **Selective-DAG vs Mono-L**：配对 ΔQ、95% CI、McNemar、Help/Harm
2. **Selective-DAG vs DAG-L/M**：同上
3. **决策粒度**：查询级路由 / 节点级路由 / 工作流级调度的质量对比
4. **门控覆盖率**：DAG 被选中的任务比例及分复杂度分布

## 成功标准（预注册）

- **方向一致**：Selective-DAG > Mono-L（点估计）
- **补充证据**：Help ≥ Harm
- **不要求**：CI 不含零（200 题可能不足以达到显著）

## 禁止事项

- 不根据结果修改门控特征、阈值或候选策略
- 不根据结果修改评分器或预算规则
- 不从冻结集中删除任务
- 不重复运行

## 运行前检查清单

- [ ] commit hash 记录
- [ ] FROZEN_TASKS_200.json SHA256 验证
- [ ] 模型 checkpoint provenance 哈希验证
- [ ] GPU 空闲（local_gpu.lock 可获取）
