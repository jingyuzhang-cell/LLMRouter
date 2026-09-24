# DV/FR 故障扩展：候选池前沿分析(2026-09-24)

> 9 个组合(3 故障率 × 3 种子)× 2 个新臂(DV/FR),~4200 秒真实执行。
> 数据:`fault_pool/fp{p}_s{seed}.json`。回答:扩展候选能否丰富 Pareto 前沿?

## 结论(先说)

**DV 与 FR 在全部故障条件下保持被支配**——前沿仍是 {Single(≤20%), Dynamic(30%)},
没有出现第三个前沿点。这本身是一个有价值的负结果:确认了当前候选空间的**紧凑性**
(compactness),同时也把"丰富前沿"的瓶颈定位到候选生成(需要真正不同的执行机制,
而不是同一机制的加强版)。

## 五策略池全景(3 种子 mean±std)

| 策略 | clean | f10% | f20% | f30% | clean tokens |
|---|---:|---:|---:|---:|---:|
| Single LLM | **0.5500** | **0.4972±0.017** | **0.4389±0.017** | 0.3639±0.032 | 603 |
| Static DAG | 0.3500 | 0.3250±0.008 | 0.3056±0.013 | 0.2861±0.017 | 1503 |
| Dynamic DAG | 0.4000 | 0.4056±0.005 | 0.4111±0.005 | **0.4056±0.013** | 2324 |
| DV(+Verifier) | 0.4000 | 0.4028±0.005 | 0.4000±0.008 | 0.3917±0.022 | 2727 |
| FR(Full Replay) | 0.3750 | 0.3944±0.013 | 0.3861±0.005 | 0.3833±0.008 | 3347 |

Q-前沿:clean/f10/f20 → {Single};f30 → {Dynamic}。DV 在各条件下略低于或持平 Dynamic
(f30 0.3917 vs 0.4056),FR 各条件最低——二者被 Dynamic 支配(质量更低、成本更高)。

## 五策略 Oracle Gap(相对最优固定策略)

| 条件 | 最优固定 | 5 策略 oracle | gap |
|---|---:|---:|---:|
| clean | 0.5500 | 0.5917 | +4.2pp |
| f10% | 0.4972 | 0.5889 | +9.2pp |
| f20% | 0.4389 | 0.5778 | +13.9pp |
| f30% | 0.4056 | 0.5694 | +16.4pp |

与 3 策略 oracle(+8.1/+12.5/+13.3pp)相比,5 策略 oracle gap 更大(+9.2/+13.9/+16.4pp):
扩展候选增加了任务级策略互补性,但现有策略的平均性能仍无法完全覆盖该潜在收益
(potential, 非 achieved improvement)——说明自动化 workflow 搜索仍存在进一步优化空间,
为后续工作提供实证基础而非已实现的改进。

## 论文表述(建议)

> Extended candidates (Dynamic+Verifier, Full Replay under faults) were evaluated
> across all fault conditions but remained dominated by Dynamic DAG, confirming the
> compactness of the current Pareto frontier. The five-strategy per-task oracle
> nevertheless reaches +16.4pp over the best fixed strategy at 30% faults (vs. +13.3pp
> with three strategies), indicating that task-level complementarity grows with pool
> diversity even when pool-level front structure does not — motivating automated
> combinatorial policy selection as future work.

## 对手稿的影响

1. **表 4-6 / S4.2 可选扩展为 5 策略版**(前沿结论不变,DV/FR 行全为被支配,可作为
   S4.4 或 S4.5 的扩展表)。
2. **调度器候选池敏感性实验(E1 故障侧)**:P3(3 策略)→ P5(5 策略)——前沿过滤
   行为不变(仍只留 Single/Dynamic 入前沿),selector 行为不变,但 oracle gap 增大,
   进一步验证"前沿过滤有效、扩展候选不干扰选择"。
3. **负结果的价值**:The verifier-augmented workflow does not provide additional Pareto gains
   under the evaluated fault model: Dynamic 的模型切换已覆盖主要可恢复故障场景
   (与 clean 下 DV=Dynamic 的负结果一致,故障侧复制);Full replay introduces additional execution cost without improving recovery
   effectiveness compared with localized recovery(突出局部恢复的核心价值)。两个负结果从故障侧复制了 clean 侧的结论,增强了外部效度。
