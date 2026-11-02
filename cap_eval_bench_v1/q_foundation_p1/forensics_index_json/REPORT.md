# evidence/index.json 来源调查报告（三步授权范围）

**日期**: 2026-10-31 | **授权**: 操作员三项裁定之第三项（UNEXPLAINED CHANGE / HOLD 的后续核查，只做三件事）
**纪律**: 原文件未覆盖、未恢复、未删除、未定性为合法追加；本轮零调用零修改（唯一写入为本报告与只读快照副本）。

## 第一步：原始字节保全（完成）

| 项 | 值 |
|---|---|
| 当前文件 | `evidence/index.json`，13,844 字节，mtime **2026-10-29 14:34:23** |
| 当前 SHA256 | `e72b5c787ce5e9017498c6b1a709e04eca77befcf5a81e68a8c99bc00444d987` |
| 快照副本 | `q_foundation_p1/forensics_index_json/SNAPSHOT_20261031.json`（字节一致，哈希同上） |

## 第二步：与冻结基线比对（完成，差异结构如下）

- 基线哈希（BENCH_FREEZE_MANIFEST.json 记录）：`a768ae508bba188711a8f25763fa44b68ef57202faa6c07ee6b0f431ea94d862` ≠ 当前 `e72b5c78…`。
- 基线**内容**不可得（清单只存哈希；cap_eval_bench_v1 未纳入 git，无历史版本可回溯），故无法逐字段 diff；以下为当前文件的结构画像：
  - JSON 顶层数组，**31 条文档条目**，字段：`doc_id / event / title / url / public_date / sha256_raw / text_chars / class_usage / source`。
  - `sha256_raw` 指向**原始来源文件**（evidence/raw/ 下的 PDF 等），非 texts/ 文本快照哈希。
- **与当前 raw 语料的实际一致性**：31 条中仅 **10 条**能在 `evidence/raw/`（39 个文件）中找到精确哈希匹配；**13 条不匹配**（如 kdx_inquiry_2018 / kdx_notice_2019 / kdx_notice_2020 / kdx_penalty_2020 等，含唯一候选仍不匹配者）；**8 条在 raw/ 无对应文件**。
  - 注意：不匹配条目中出现"前 12 位十六进制相同、后段不同"的形态（kdx 系列），提示可能是**同源文件被重存/重下载后字节变化**，或索引构建时引用的 raw 版本与现存版本不同——两种假设均未证实。

## 第三步：修改来源查找（部分完成）

1. **时间线证据（强）**：`index.json` 的 mtime 与 `evidence/texts/` 目录及其全部文本文件**精确同秒**（2026-10-29 14:34:23）——指向一次同时重建 texts/ 与 index 的脚本运行，而非零散编辑。
2. **写入者脚本**：本轮检索未定位到该再生成事件的执行脚本或日志。`retrieval_api.py` 只读 index.json（L37）；`build_tasks.py` 仅引用其路径（L277）；`evidence/__pycache__`（10-29 10:34）不含 index 构建模块。
3. **授权记录**：AUTHORIZATION_LEDGER.md 中未检索到 2026-10-29 前后针对 index 重建的授权条目（该账本今日另有非本会话写入，见附录）。
4. **旁证**：`BENCH_FREEZE_MANIFEST.json` 自身 mtime 为 10-30 12:22:49（晚于 index 再生成），其记录的 index 哈希应系承袭更早参照而非 10-30 现场状态——清单与现状的差异在 10-29 即已形成。

## 结论（维持操作员定性，新增三项事实）

- **维持 UNEXPLAINED CHANGE / HOLD**：来源与授权状态仍未确认；不覆盖、不恢复、不删除、不作为正式 Gold 证据。
- 新增事实：① 再生成事件锚定于 10-29 14:34:23（与 texts/ 重建同秒）；② 当前 index 与现存 raw 语料仅 10/31 哈希一致（13 不匹配 + 8 缺 raw）——这构成**独立于冻结问题的数据质量疑点**；③ 基线内容不可恢复，逐字段 diff 在现有材料下不可能，如需继续只能从原始 PDF 重抓对证（属新动作，需单独授权）。

## 附录：调查中发现的治理事项（非 index 本身，需操作员裁定）

今日 11:20:39，AUTHORIZATION_LEDGER.md 被本会话之外的写入者追加"台账 #21 补记-5/6/7/8"，内容为 E08 审计包 V3/V3.1 的**整包 256 字符块交付记录**（V3.1 zip 10,121B、SHA256 `a2069033…`、53 块）及其向**逐文件协议**的切换（THREE_LAYER L20/21、VERIFICATION_SCOPE、MANIFEST、L1_REVIEW L03"双表示"、LAYER3 L11-27 等修复记录）。

**字节级对账结果**：V3.1 zip 内的 L1_REVIEW_RECORD.md（1,277B）、LAYER2（2,937B）、LAYER3（1,283B）、E08_FROZEN_PAGE1_TEXT（1,946B）、VERIFICATION_SCOPE.md（1,238B）与 track_b 目录同名文件**逐字节相同**。因此两条通道交付的这五个文件内容一致，操作员已验收文件的完整性不受影响；此前我方报告的"zip 哈希不一致疑点"（a2069033 vs V1.1 的 a5666f62）系**版本代际差异**（V3.1 = V1.1 的后继版本，7 文件），非损坏。

**待裁定**：① 两条交付通道并存（本会话 64 字符行协议 / 未知会话整包+逐文件协议）且共用共享账本，需指定唯一交付通道与账本写入权归并；② 按台账补记-8，E08_REFERENCE_V1.json（8,654B）为并行通道的"末批"，其交付归属需明确；③ 台账 #21 补记系列的作者身份需 append-only 澄清（与 R10 VOID 争议同类处理）。
