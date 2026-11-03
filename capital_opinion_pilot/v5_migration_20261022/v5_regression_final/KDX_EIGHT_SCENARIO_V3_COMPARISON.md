# KDX_EIGHT_SCENARIO_V3_COMPARISON — 四策略八场景完整比较（零付费）

## 完整矩阵

| # | 场景 | S5 | S5+Gate | S5+CloGate | S6_v3 | S6 独有？ |
|---|---|---|---|---|---|---|
| F1a | t1 DS 屏蔽 | LOCAL glm53 | LOCAL glm53 | LOCAL | LOCAL glm53 | 否 |
| F1b | t1 GLM 屏蔽 | LOCAL ds | LOCAL ds | LOCAL | LOCAL ds | 否 |
| F2a | t5 GLM 屏蔽 | LOCAL flash | NONE | NONE(q:t5) | NONE | 否 |
| F2b | t5 仅 Flash | LOCAL flash | NONE | NONE(q:t5) | NONE | 否 |
| F3 | t1+t2 DS | LOCAL glm53 | LOCAL glm53 | LOCAL | LOCAL glm53,? | 否(伪影) |
| F4 | t1DS+t5GLM | LOCAL glm53,flash | LOCAL glm53,NONE | **NONE(q:t5)** | **NONE** | **否** |
| F5 | t1GLM+t5GLM | LOCAL ds,flash | LOCAL ds,NONE | **NONE(q:t5)** | **NONE** | **否** |
| F6 | t0 GLM 屏蔽 | LOCAL ds | LOCAL ds | LOCAL | LOCAL ds | 否 |

## 结论

**S6 在全部 8 个场景中无独有增量（0/8 vs S5+CloGate）。**

原先 F4/F5 的"S6 独有优势"实际上是闭包级可行性门禁的贡献。S5+ClosureGate
（固定分配+闭包门禁）在相同场景下做出相同决策。

## 五个问题的最终回答

**1. F4/F5 的 S6 独有分离在强基线加入后是否仍存在？**
**否。** S5+CloGate 在 F4/F5 同样选择 NONE。归因完全来自闭包级质量门禁。

**2. 原先预计节省的 800 Token、6 秒是否仅来自闭包级拒绝执行？**
**是。** 资源节省来自"在执行前发现 t5 不可行"——这是门禁功能，不需要联合搜索。

**3. S6 有没有找到固定恢复策略无法找到的其他合法完成方案？**
**没有（0/8）。** 在全部场景中，S6 的最优动作与 S5+CloGate 的固定策略一致。

**4. NONE 是否可能错误放弃实际可完成任务？**
**可能。** 当前 Q_output_ratio=0 的判定依赖未经 Gold 验证的产出代理。如果 Flash/Qwen/DS
实际能完成跨源核查（只是提示词不适配），S6 的 NONE 就是错误放弃。必须 Gold 校准后评估。

**5. 在 Gold 校准前是否还值得开展付费实验？**
**不建议。** 在 0/8 独有增量的现状下，真实实验只会确认 S6=S5+CloGate。应先：
(a) Gold 标注校准 Q；(b) 修复跨源核查提示词使非 GLM 模型能产出；(c) 设计真正存在多合法
恢复路径的场景。Gold 校准可能改变模型排序，从而打开 S6 的决策空间。
