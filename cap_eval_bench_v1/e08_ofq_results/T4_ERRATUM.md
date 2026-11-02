# T4 勘误记录

**问题**: T4_RESULTS.json 中 `key_fact_ok: false` 为报告展示层 bug，非测试失败。

**根因**: `key_fact_tests = ['B1','B2','B3','B6','B7','B10']` 查找 `results` 字典时使用短键名（如 'B1'），但实际键名为完整测试名（如 'B1_entity_sub'）。`results.get('B1', {}).get('ok', False)` 因键不存在返回 False。

**实际结果**: B1_entity_sub / B2_date_confusion / B3_date_offbyone / B6_qualifier_lost / B7_id_error / B10_omission 全部 PASS。关键事实零容忍实际通过。

**影响范围**: 仅影响 T4_RESULTS.json 中 `key_fact_ok` 字段和终端显示。不影响任何测试断言的执行或判断。Verdict = PASS 正确。

**处置**: 保留原始 T4_RESULTS.json 不修改；本勘误单独存档。后续修复 Parser 时不影响此记录。

**日期**: 2026-10-30
