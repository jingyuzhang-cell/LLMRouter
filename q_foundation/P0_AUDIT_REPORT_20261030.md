# P0 审计报告 — quality_v4 / PR #5（2026-10-30）

操作者指令：上一轮声称 PR #5 "18/18 PASS" 但实际未执行任何 Python 测试；先完成真实测试与代码审查，再考虑合并；PR 保持 Draft。本报告为该指令的执行记录。

## 1. 对象

- PR #5 "Add Gold-gated terminal quality evaluator v1"（分支 `quality-evaluator-v1-20261030`，DRAFT）
- 新增 6 文件 +850/−0：`r3_own_pool/deadline_reward_v1/quality_v4/{terminal_quality.py(421行), test_terminal_quality.py(222行,18测试), QUALITY_EVALUATION_PROTOCOL_V1.md, Q_EVALUATION_AUDIT.md, README.md, quality_contract.example.json}`

## 2. 真实测试执行（首次真实验证）

| 项目 | 结果 |
|---|---|
| 环境 | Python 3.12.3, Linux |
| `python -m py_compile` 两文件 | OK（exit 0） |
| `python -m unittest -v test_terminal_quality` | **Ran 18 tests in 0.004s — OK（exit 0）** |
| 重复执行 | 两次运行输出逐字节一致（纯函数、仅 stdlib 导入 re/unicodedata/decimal/typing） |
| 模型调用 | 0（代码审读确认，无网络/IO） |
| 隔离性 | 仅新增 6 文件，不导入既有评分器，无写入；历史评分未动 |

**结论：18/18 PASS 现在是经真实执行验证的事实；此前 PR body 中的通过声明无执行记录支撑，已由 commit 47668268 与 PR 评论（issuecomment-6522984321）纠正。**

## 3. 代码审查发现（全部最小用例复现，代码未改，待操作者决定修复语义）

| # | 级别 | 发现 | 复现 |
|---|---|---|---|
| F1 | 高（规范缺口） | **关键事实硬门禁未实现**：`critical` 字段在合同示例/测试夹具中出现，但评分器从未读取 | 2 个 GOLD 事实，critical 金额错约 10 倍、其余全对 → `Q_final=0.625`（四维平均 0.5/0.5/0.5/1.0），关键金额错误可被平均稀释，违反冻结 Q 规范 |
| F2 | 高（正确性） | **已校准 Judge 的 SUPPORTED 可推翻确定性数值核验**：显式 `fact_id` + 判定 SUPPORTED（calibration PASS）分支不重跑 `_value_equal`/`_derived_value_ok` | 日期错一天（09-19 vs 09-18）+ 同义谓词 + SUPPORTED → 计 TP，状态 `SEMANTICALLY_CORRECT` |
| F3 | 中（健壮性） | 数值类型 value=`NaN` 使评分器崩溃：`_decimal` 接受 `Decimal("NaN")`，有序比较抛 `decimal.InvalidOperation` | amount 事实 + claim value="NaN" → 整个评价中断（应为 fp 或 NULL） |
| F4 | 低（标签） | 正确值的重复 claim 且无引用：fp 记数正确，但标签为 `WRONG_GOLD_FACT_VALUE_OR_RELATION`（误导诊断）；带引用才标 `DUPLICATE_CLAIM` | 复现确认 tp=1/fp=1、无 blocking、无警告 |
| F5 | 低 | 无日历合法性校验：仅月/日范围检查，`2026-02-31` 可规范化并匹配 | gold 与 claim 同为 2026-02-31 → tp=1.0 |
| F6 | 低-中（门禁范围） | 派生事实输入可引用非 GOLD 事实（`facts_by_id` 建自全部 required）：`min_gold_coverage<1` 时 SILVER 值参与 GOLD 派生一致性检查并发出正式 Q | gold_coverage=0.667 → `Q_final=0.875`，SILVER 输入 F2 参与 F1 派生 |

**离开 DRAFT 前的建议顺序**：操作者裁定 F1 门禁语义（封顶/NULL/事实级否决）→ 修复 F1–F3 并补回归测试 → 重标 F4；F5/F6 可随后。

**经测试正向验证的护栏**（测试断言真实覆盖）：SILVER 不得产生正式 Q；哈希绑定来源跨度；UNKNOWN 弃权计分、断言计 fp；交付失败与语义分离（Q_final NULL / Q_delivered=0 / R_delivery=0）；未校准 Judge 拒绝；claim 抽取不完整 blocking；关键词短引文不算证据支持；重复不虚增 TP；跨文档派生需全部证据跨度。

## 4. C9 人工校准包盘点（P1 就绪度）

- 目录 `phase_c9_0/human_judge_calibration/` **完整（10/10 文件）**：manifest（30 组，seed 冻结，能力维度标注：evidence_synthesis / multi_hop_reasoning / hierarchical_table_reasoning / ambiguity_negotion_exception 等）、密封映射（盲标→模型 ID，已密封）、评审模板 A/B（各 30 行、SHA 相同 = **模板非标签，0 打分**）、SHA256SUMS、协议、状态文件。
- 状态文件：`status=UNAVAILABLE`；需 2 名独立评审者；每人 30 组 / 123 候选；**禁止 LLM 替代**；`human_gold_claim_allowed=false`；`final_scorer_freeze_blocked=true`。
- 产出要求（按指南）：`C9_HUMAN_REVIEWER_{A,B}_SCORED.jsonl`，每候选 score(0–4)+理由，每组 reviewer_confidence；>1 分分歧须裁决。
- **本轮修复**：两份评审指南（`C9_HUMAN_REVIEW_INSTRUCTIONS.md`、`HUMAN_REVIEW_COMPLETION_GUIDE_ZH.md`）此前在工作区被删（未暂存删除），已仅就这两个文件从 git 索引恢复；其余 295 个删除未触碰。
- **KDX_GOLD_HUMAN_ANNOTATION_PACKAGE**：仅含空 `evidence/` 目录（0 文件，git 未跟踪）——P1 轨道 (b) 的证据材料需从零填充。

### P1 启动条件清单
1. 两名人类评审者到位（不可 LLM 替代）；
2. 评审者按恢复的指南独立完成 A/B 打分（模板不动，另存 SCORED 文件）；
3. 分歧裁决 + `analyze_c9_human_calibration.py` 汇总（人工一致性第一层，含加权 Kappa）；
4. 资本市场事实级 Gold：以 quality_v4 合同 schema 起草首批任务评价合同，证据填入 KDX 包（含页码/原文跨度/双哈希）；
5. 样本规模按目标误差与统计功效论证扩充。

## 5. 工作区状态观察（不处理，仅记录）

`/root` 当前有 297 个未暂存删除（多为 r3_own_pool / phase_* 各阶段 .md 报告）与 797 个未跟踪文件。来源不明（疑似早前会话或同步残留）。本次审计仅恢复 C9 两份指南；是否整体恢复/提交/清理由操作者决定。

## 6. 本轮动作清单

1. PR #5 分支提交 47668268：`Q_EVALUATION_AUDIT.md` 追加 "P0 real-execution audit record (2026-10-30)"（真实执行记录 + F1–F6），已推送；
2. PR #5 评论：交付状态纠正 + 测试真实结果 + 发现表（https://github.com/jingyuzhang-cell/LLMRouter/pull/5#issuecomment-6522984321）；
3. PR 保持 DRAFT，未合并、未批准；
4. 恢复 C9 两份评审指南至工作区；
5. 建立本目录 `q_foundation/`（治理规划 + 本报告），**未提交 main**，留待操作者审阅。

## 7. 结论

P0 完成。quality_v4 的 18 项测试经真实执行全部通过、确定性成立、隔离性与零调用成立；但代码审查发现 2 项高优先级问题（F1 关键事实硬门禁缺失、F2 Judge 可推翻确定性核验），合并前必须裁定并修复。人工校准（P1）仍是整个 Q Foundation 的关键路径：C9 包万事俱备，只差两名人类评审者；事实级 Gold 证据库为空。**在 P1–P3 完成并冻结正式 Q 前，不开发新调度功能、不用 quality_v4 产生任何正式质量标签。**
