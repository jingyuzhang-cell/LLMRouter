# 最终整合交付说明

本目录保存本轮整合版本。推荐先阅读 `论文完整草稿.docx` 或 `论文完整草稿.pdf`，再查看 `FINAL_CLAIM_AUDIT.md`。六个指定章节均有独立 Markdown 文件，补充相关工作、实验设置与参考文献后组成完整草稿。

全文约 1.24 万中文字，PDF 16 页，12 个表格；所有章节标题为中文。Word 使用原生公式，检查了表格结构与 PDF 页面文本边界。该检查不等于逐页视觉审校。

原稿位于 `原稿备份/`；本轮仅修改论文文件，未启动实验、模型调用、Git 提交或推送。旧日期目录仍保留，勿将旧稿数字直接合并回新稿。

证据清单见 `FINAL_SOURCE_MANIFEST.json`，自动核对见 `CONSISTENCY_CHECKS.json`。正文区分条件化节点、真实传播、确认、开发交叉验证、理想失败检测及事后 Oracle。

原两项待补来源（传播 headroom、D0–D4 配对诊断）已于 2026-09-21 以零调用审计闭环：见 FINAL_CLAIM_AUDIT.md 第八节及 static_dag_v0/propagated_row_oracle_audit/ 与 static_dag_v0/structure_aware_experiment/EVIDENCE_DIAGNOSIS_AUDIT.json。
