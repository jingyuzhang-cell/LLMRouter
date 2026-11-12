# MVR2 元道退 材料包（AI 侧复核用 · 2026-11-08）

| 文件 | 说明 |
|---|---|
| TASK_CONTRACT_MVR2_v1.json | 冻结合同：27 事实 / 5 关键 / 2 UNKNOWN / 3 文档（文件 SHA a556d229212b74ac…，与你检索的历史版本一致）|
| docs/ | 三份文书全文（由合同内嵌 source_pages 文本重建；docs/ 同时含原始 PDF 与重建全文 TXT：PDF 为合同 raw_sha256 锚定的原件；TXT 为合同内嵌冻结文本重建）|
| MVR2_SIGNOFF_WORKSHEET.csv | 27 槽签收表（human_verdict 空白）|
| TEMPLATE_ST_SHUN_GOLD.json / TEMPLATE_ST_SHUN_WORKSHEET.csv | 舞天 v2 评分规则与模板 |
| PROTOCOL_FROZEN_v1_0.md | V5 冻结协议（六门 §3.4、评分 §5）|

边界：不重建 27 事实、不增槽、不改冻结原文与合同；AI 预审不替代人工签收。

## 文档重建与 SHA 校验
- Da → docs/Da_yuandao_fulltext.txt：SHA256 773cf6fa185ba1bd…（与合同 raw_sha256 不一致: f789177f381dc341）；7 页
- Db → docs/Db_yuandao_fulltext.txt：SHA256 69897d8f410dd09d…（与合同 raw_sha256 不一致: 51e7d4496865b2ee）；3 页
- Dc → docs/Dc_yuandao_fulltext.txt：SHA256 bccd5ab773581ad6…（与合同 raw_sha256 不一致: fe19b0b382754728）；3 页

## 原始 PDF（SHA 与合同 raw_sha256 逐字一致）
- Da = docs/Da_E03-yuandao.pdf（原始 PDF，SHA256 与合同 raw_sha256 一致）
- Db = docs/Db_E03-yuandao_sup2.pdf（原始 PDF，SHA256 与合同 raw_sha256 一致）
- Dc = docs/Dc_E03-yuandao_sup1.pdf（原始 PDF，SHA256 与合同 raw_sha256 一致）
（重建 TXT 的哈希与 raw_sha256 不同属预期：raw_sha256 锚定 PDF 原件，TXT 仅为合同内嵌文本的拼接重建）
