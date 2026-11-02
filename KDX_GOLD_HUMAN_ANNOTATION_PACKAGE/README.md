# KDX Gold 人工标注包 — 资本市场事实级 Gold 证据库（轨道 B）

> Q Foundation P1 轨道 B。目标：从权威监管文书与上市公司公告出发，建立**事实级**任务评价合同
> （逐事实：来源、页码、原文跨度、双哈希），经双人独立盲审确认后升级 GOLD。
> **在人工确认完成之前，一切事实均为 SILVER_SOURCE_ANCHORED，本包不宣称任何 GOLD。**

## 状态（2026-10-30）

| 项 | 状态 |
|---|---|
| 证据条目 | 1（E08-中铁装配 立案告知书公告，SILVER 草案） |
| 已确认 GOLD | 0 |
| 人工评审者 | 待到位（与轨道 A 共用双人盲审协议） |
| 模型调用 | 0（构建全部为确定性提取与哈希锚定） |

## 目录结构

```
evidence/
  E08_zhongtie/
    build_e08_silver_draft.py          # 可复现构建脚本（确定性，重跑逐字节一致）
    source_pages.json                  # 页文本 + raw_sha256 + page_sha256（评分器输入）
    TASK_CONTRACT_E08_SILVER_DRAFT.json # SILVER 草案合同（quality_v4 v1.1 schema）
    FACT_SHEET_E08.md                  # 人工评审用逐事实核验单（含易错点提示）
    selfcheck_e08_silver.py            # 确定性自检：SILVER阻断/GOLD化满分/关键事实否决
```

## 构建与核验流程（每份证据必须走完）

1. 从冻结 manifest（`capital_opinion_pilot/benchmark_v1/verified_docs_manifest.json`）取源文件并**重算 sha256 比对**（注意：manifest 中 pool_id 不唯一，须按 sha256 反查唯一条目）。
2. 确定性页文本提取（pymupdf text 模式），计算每页 page_sha256。
3. 机器锚定候选事实：谓词化（主体/谓词/值/类型/单位/日期类型），引文用**去空白归一化匹配 + 偏移映射**锚定原文精确区间（评分器 `_norm_text` 语义一致）。
4. 全部标 `SILVER_SOURCE_ANCHORED`；`critical_proposed` 为拟议关键性，**仅在人工确认后随合同冻结为 `critical`**。
5. 自检三连（selfcheck 脚本）：SILVER 状态正确阻断正式 Q；模拟满分答案（GOLD 化 mock）得 1.0 且门禁 PASS；任一关键事实损坏 → Q_final=0 且 Q_raw 保留。
6. 人工双人盲审（盲模型、盲策略）逐事实核对 FACT_SHEET；分歧裁决（沿用 C9 协议：>1 分歧第三裁决）。
7. 全过后：status→GOLD_CONFIRMED、critical 冻结、合同版本与 sha256 冻结；任何一项不过：修正或降级 UNKNOWN。

## 已记录的坑

- **provenance 词汇表**：合同的 `gold_provenance` 必须取自评分器冻结枚举 `{human_adjudicated, native_dataset_annotation, official_structured_record}`。首版草案误写 `official_company_announcement`，自检立刻暴露（全部事实无法转正式 Gold）——这正是自检存在的意义。
- **manifest pool_id 不唯一**：一家公司有多份公告，必须按 sha256 反查。
- **PDF 提取文本含版式空格与句中换行**（如"2026 年9 月18 日收\n到"、"证监立案字0142026049 号"）：引文锚定用归一化匹配映射回原文偏移，勿手工拼接。

## 事实设计口径（对齐操作者 Q 规范）

- 收件日 ≠ 公告日 ≠ 处罚决定日（date_type 区分 receipt/publication/decision）。
- "涉嫌信息披露违法违规"（立案时点）不得升级为最终认定；"可能涉及"必须保留不确定性限定。
- 立案对象主体关系单独成事实（公司本身 vs 实际控制人 vs 董监高个人；对照 E10/E10b）。
- 立案≠处罚：最终结论/金额进 UNKNOWN（U1），任何确定性断言按 UNKNOWN 错误断言处理。
