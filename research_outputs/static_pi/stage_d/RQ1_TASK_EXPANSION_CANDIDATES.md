# RQ1 独立任务扩充建议与候选清单（零调用）

## 1. 现有面板（V1.4/V1.5）

E04 *ST卓然、E05 *ST纳川、E06 欢瑞世纪、E07 ST西王、E08 中铁装配；25 节点；73 原始事实 + 27 派生 = 100 唯一槽位；4 条原始 UNKNOWN + 3 条派生 UNKNOWN。

## 2. 候选任务（来自 tasks_frozen，文档已在 evidence/texts）

| 任务 | 公司 | 类型 | 文档数 | 与现有面板独立性 | 可补节点类型 | 预计节点 | 预计事实 |
|---|---|---|---|---|---|---|---|
| T-P2 | 康得新(002450) | regulatory_penalty | 5 | 文档不相交 | extract/timeline/verification | 8 | 18–24 |
| T-P3 | 豫金刚石(300064) | regulatory_penalty | 5 | 文档不相交 | extract/timeline/merge/verification | 8 | 18–24 |
| T-M1 | 美的集团(000333) | ma_restructuring | 4 | 文档不相交 | extract/merge/report | 6 | 12–18 |
| SC-E1 | 獐子岛(002069) | regulatory_penalty | 2 | 文档不相交 | extract/verification/report | 4 | 8–12 |
| SC-E2 | 康美药业(600518) | regulatory_penalty | 2 | 文档不相交 | extract/verification/report | 4 | 8–12 |
| SC-E3 | 中国船舶(600150) | ma_restructuring | 2 | 文档不相交 | extract/merge/report | 4 | 8–12 |
| SC-E4 | 乐视网(300104) | disclosure_market | 2 | 文档不相交 | extract/timeline/report | 4 | 8–12 |

**排除**：T-P1、T-D1、T-R2（共用 st/csrc 文档，与彼此不独立）；T-D2（与 T-P2 共用 kdx 文档）。任务独立性的判据是**文档集合不相交**，不是公司不同。

## 3. 三种方案

| 方案 | 任务 | 新节点 | 总节点 | 调用 | 任务级精确下限 | 评价 |
|---|---|---|---|---|---|---|
| A | E04–E08 | 0 | 25 | 300 | 5 对，p=0.0625 | 探索；α=0.05 不可达 |
| B | +T-P2/T-P3/T-M1 | 22 | 47 | 564 | 8 对，p=0.0078 | 主检验；需 3 个新任务 Gold |
| C | 训练 E04–E08 + 外部 SC-E1/E2/E3 | 12 | 37 | 372 | 5 训练+3 外部 | 泛化；外部不参与选型 |

调用计算：固定输入 = 节点×2 模型×2 重复；策略矩阵 = 节点×2 重复×4 策略。B：47×2×2 + 47×2×4 = 188+376 = 564。C：12×2×2 + 12×2 = 48+24 = 72，加 300 = 372。

## 4. 新任务建设要求

每任务必须完成：
1. 节点级 Gold（显式事实 + **派生关系/综合结论**，下游不得复制上游）；
2. 每条 Gold 的证据文档/跨度（原文可定位）；
3. UNKNOWN 边界（expected_status=UNKNOWN）；
4. 参考上游 fact_ids 与 DAG 依赖；
5. 任务级 deliverable_schema / unknown_boundary 对照；
6. 文档 SHA 与独立性校验；
7. 禁止模型生成 Gold；禁止用现有面板的文档充当独立任务。

## 5. 推荐

- 若目标是**发现真实增益**：B。8 个独立任务才能把任务级精确检验从 p=0.0625 降到 0.0078；5 任务在 α=0.05 下不可达。
- 若目标是**检验泛化**：C。外部任务不参与选型，能暴露 Task-Conditioned 过拟合。
- 在 B/C 的 Gold 建成并通过校验前，只能做 A 的探索；不得把 A 的 5 任务结果包装成确认性结论。
- 新任务优先补 timeline/verification（T-P2/T-P3/SC-E1/SC-E2）；reason 仍只有 E04，若要 reason 可估计，需另建至少 2 个计算/推断型任务。

## 6. 成本

- T-P2/T-P3：各 1–2 个零调用工作日；T-M1 半天；SC-E1/E2/E3 各半天。
- B 的额外调用 264（564−300）；C 的额外 72。
- 新任务的 Gold 建设不含模型调用；若用模型辅助，必须另立预算并披露。
