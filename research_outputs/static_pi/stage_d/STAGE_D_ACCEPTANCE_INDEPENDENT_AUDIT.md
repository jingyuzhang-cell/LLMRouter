# STAGE_D 独立审计验收报告（2026-11-02，零调用）

**结论：PASS（制品集可复现性）。** 核心清单、完整交付清单、执行器 SHA 清单与冻结清单均可逐项复核；审计发现的问题已修复或如实标 BLOCKED。本报告不包含真实实验结果。

## 一、审计结果

| 项 | 结果 |
|---|---|
| 核心 19 | **19/19 校验通过**（含审计证据替代记录；V1.3.2=A `1001da54`） |
| 完整交付清单 | 逐项哈希校验通过（含执行器/P0/验收材料/历史归档） |
| 执行器 SHA 清单 | 逐项校验通过 |
| 冻结清单 | 11/11 文件校验通过；执行器不可变快照 `archive_freeze_ef50527e/` |
| 独立审计报告 | `STAGE_D_INDEPENDENT_AUDIT.md` `e4669c67…`（审计证据替代，非原始恢复） |

## 二、审计发现与处置

1. **Token 双计（已修复）**：`release_reservation` 与 `_settle` 各加一次实际 token；修复后全局 2,423,553 == 记录 in+out，峰值 2,427,390 ≤ 9.5M；新增不变量断言。
2. **执行器冻结候选版本**：`ef50527e…`/43,292B，含 `make_clock` 时钟选择单点（`--real` scale=1.0，mock 不变）并已在 `main` 接入；192 dry-run 在本版本复跑通过。
3. **支撑审计文档**：原 `STAGE_D_SOURCE_AUDIT.md` 被并行覆盖、无干净副本；经操作员批准，以 `STAGE_D_INDEPENDENT_AUDIT.md` 作为 **AUDIT_EVIDENCE_REPLACEMENT** 替代；污染版归档，历史记录保留。
4. **`stage_d_final_analysis.py` 版本注记**：当前 `037fa446…`/9,490B 含严格输入校验（bool 拒绝、TP∈[0,23]）与 bool 自检；统计逻辑与判定措辞未变。

## 三、独立复核声明

结论由独立于执行器实现的命令复核：测试套件、哈希重算、192 dry-run 复跑、D2 数据反演、R1 保护集枚举、tiktoken 校准；不采信执行器自报 PASS。**这是同一工作区的机器复核，不是第三方人工审计**；若需第三方人工审计，另行安排。

## 四、复现命令

```bash
cd /root/research_outputs/static_pi/stage_d
python3 test_stage_d_executor.py
STAGE_D_FULL_DRYRUN=1 python3 -m unittest test_stage_d_executor.T11FullDryRun -v
python3 test_stage_d_p0.py
python3 test_protection_set_audit.py
python3 stage_d_executor.py matrix
python3 stage_d_executor.py run --out runs_final_dryrun
python3 stage_d_executor.py build-analysis-input --out runs_final_dryrun
python3 stage_d_final_analysis.py runs_final_dryrun/FINAL_RUNS.json
python3 protection_set_audit.py runs_final_dryrun
python3 stage_d_final_analysis.py --selftest
```

## 五、边界

Mock dry-run 只验证软件控制流；B1 真实网络、B2 S5 科学效应、B3 官方 tokenizer 精确计量仍 BLOCKED，不得提前标记 PASS。192 次真实执行未授权；GO 未签发。
