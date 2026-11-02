# Q Foundation P1 人工 Gold 材料制备交付（2026-10-30，零调用零费用）

**授权依据**（操作员原文）："授权启动 Q Foundation 的 P1 人工 Gold 材料制备阶段"（范围/允许/禁止
四要素完整；本交付严格遵守：未做任何 Gold 裁决、未生成 Gold 标签、未联系评审者、未改任何历史
账本/原始数据/冻结规格/历史代码、零模型调用零 GPU 零费用）。

## 轨道 A：C9 双人盲审材料（q_foundation_p1/track_a_working/）

| 文件 | 说明 |
|---|---|
| REVIEWER_A_WORKING_COPY.jsonl / REVIEWER_B_WORKING_COPY.jsonl | 冻结模板的评审工作副本（30 组 × 123 候选；score=null/reason=空 待填） |
| SCORING_INSTRUCTIONS.md | 冻结评分说明副本（0-4 分制+依据要求） |
| DISAGREEMENT_RECORD_FORM.md | 分歧记录表（新制：分差>1 触发仲裁；≤1 取保守均值） |
| ADJUDICATION_WORKSHEET.md | 仲裁底稿（新制：第三裁决者可见双方理由、不可见模型身份） |
| COMPLETENESS_CHECK.json | 完整性校验 |

**完整性校验结果**：A/B 各 30 组 123 候选 ✓；候选字段 label/answer/score/reason ✓（未填状态 ✓）；
A/B 组序列一致（同题独立作答）✓；**盲化扫描零命中**（无模型/策略身份泄漏）✓；工作副本 sha256
与冻结 SHA256SUMS 一致 ✓。

## 轨道 B：E08 资本市场事实级 Gold 核验材料（q_foundation_p1/track_b_working/）

| 文件 | 说明 |
|---|---|
| E08_REVIEWER_1_WORKSHEET.md / E08_REVIEWER_2_WORKSHEET.md | 双评审独立工作副本（10 事实逐条：主体/谓词/值/原文跨度/溯源 + 确认栏 CONFIRM/CORRECT_TO/REJECT/UNKNOWN + 跨度核对栏） |
| E08_ADJUDICATION_WORKSHEET.md | 仲裁底稿（分歧>1 事实点触发；全部通过才 GOLD_CONFIRMED） |
| COMPLETENESS_CHECK.json | 完整性+确定性定位校验 |

**完整性校验结果**：10 事实全部含 source_evidence（doc/page/quote/start/end+双 sha256）✓；
**UNKNOWN 1 条保留（U1：最终处罚/金额——不得补全）** ✓；全部 PENDING_DUAL_BLIND_REVIEW ✓；
页 1 文本 sha256 复核一致 ✓；**逐事实确定性定位核验 10/10 通过**（每条引文在页内且
[start:end] 偏移一致——零调用确定性验证）；草案三文件 sha256 已入档。

## 待人工确认事项（唯一剩余输入 = 人类评审者）

1. **轨道 A**：需 2 名独立评审者（资本市场/财务/审计/信披经验，与样本制备无利益关系）各自
   填写工作副本（123 候选各 0-4 分+依据，30 组各置信度）；互不可见。
2. **轨道 B**：需 2 名独立评审者逐条确认 10 事实 + 保持 U1=UNKNOWN。
3. 评审者由操作方指定；材料分发由操作方执行（本授权禁止制备方联系评审者）。
4. 汇总/一致性计算/分歧记录组织：可由制备方承担（不构成 Gold 裁决）。

## 状态

材料制备完成，**立即停止**，等待操作员验收与人工评审阶段的单独授权。
