# 零调用测试汇总与原始日志索引

本轮一个顺序隔离运行器，8套件全部退出0。原31项已扩展到39项，本轮运行完整39项迁移单测及10项新定向单测；其余套件另列，不将覆盖重叠当独立样本。

| 套件 | 退出码 | 原始完整日志 |
| --- | --- | --- |
| test_budget_guard.py | 0 | [test_budget_guard.py.log](test_budget_guard.py.log) |
| dry_run_tests.py | 0 | [dry_run_tests.py.log](dry_run_tests.py.log) |
| test_meter_v22.py | 0 | [test_meter_v22.py.log](test_meter_v22.py.log) |
| test_fixes_v2.py | 0 | [test_fixes_v2.py.log](test_fixes_v2.py.log) |
| test_joint_executor.py | 0 | [test_joint_executor.py.log](test_joint_executor.py.log) |
| test_v5_modules.py | 0 | [test_v5_modules.py.log](test_v5_modules.py.log) |
| test_v5_migration.py | 0 | [test_v5_migration.py.log](test_v5_migration.py.log) |
| test_final_acceptance.py | 0 | [test_final_acceptance.py.log](test_final_acceptance.py.log) |

## 首次失败与分类（未删除）

| 记录 | 结果 | 分类／处理 |
| --- | --- | --- |
| [FIRST_GAP_TESTS.log](FIRST_GAP_TESTS.log) | 8项中2 ERROR | 真正实现缺口：join根未支持、其时延未纳入；同断言修复后通过。 |
| [FIRST_REFUSAL_SAFETY_TEST.log](FIRST_REFUSAL_SAFETY_TEST.log) | 9项中1 FAIL | 真正安全缺口：拒绝恢复返回失效终端；提前剔除硬失效闭包后通过。 |
| [GAP_FIX_TESTS.log](GAP_FIX_TESTS.log) / [REFUSAL_AND_JOIN_FIXED.log](REFUSAL_AND_JOIN_FIXED.log) | 定向修复检查通过 | 仅对已暴露缺口回归，没有修改预算/时限或删失败断言。 |
| [MATRIX_RUN.log](MATRIX_RUN.log) | 退出0 | 13固定场景×2策略，26次合成验收；不是真实模型调用。 |

本轮没有修改原39项、原V5或FakeMeter套件的测试源码，哈希与上轮一致；全部运行在新沙箱。新增断言文件[test_final_acceptance.py](test_final_acceptance.py)包含Z/R/π实执行、提交/Lineage、健康缓存NONE、拒绝安全、join重算、legacy显式入口及历史代理不混用检查。

[退出码JSON](TEST_RESULTS.json)、[完整场景执行JSONL](MATRIX_EXECUTION.jsonl)、[公平性汇总](MATRIX_SUMMARY.json)与最终清单提供哈希。没有删原始失败日志，没有覆盖旧版报告、账本、协议或归档。
