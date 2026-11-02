# Stage D 终局预注册审计包（分支 stage-d-final-prereg-audit）

状态：**HOLD，零调用**。192 次执行未授权。

## 精确范围（最终）
本目录与 ZIP **仅含 29 个文件条目**：
- `artifacts/`：**26 项正式冻结材料**（与 `MANIFEST_STAGE_D.json` count=26 一一对应，无多余无缺失）
- `MANIFEST_STAGE_D.json`、`PACKAGE_SHA256.txt`（28 行）、`README_AUDIT.md`

ZIP 为**白名单精确打包**（29 条目、无目录树、无运行记录）。

## 不在包内的材料（历史实验档案，仅保留在工作区）
`runs_d2/`、`runs_probe/`、`runs_probe2/`、`runs_final_dryrun/` 等运行目录；
`d_executor.py`、`STAGE_D1_REPORT.md`、`D2_PREREGISTRATION*.md`、`FINAL_PREREGISTRATION.md`、
`STAGE_D_EXECUTOR_ASSET_AUDIT.md`、`power_v23.log`/`VERIFY_L2_JOINT.log`（别名日志）。
**这些不参与冻结材料计数，不构成第二清单。**

## 独立核验步骤（不依赖本包内任何声明）
1. `gh api repos/jingyuzhang-cell/LLMRouter/contents/audit/stage_d_final/artifacts/<file>?ref=stage-d-final-prereg-audit --jq .content | base64 -d | sha256sum`
2. 与 `MANIFEST_STAGE_D.json` 的 `artifacts.<file>.sha256` 比对
3. 重点：`STAGE_D_FINAL_PREREGISTRATION_V1_3_2.md`、`exact_perm.py`、`power_sim.py`（V2.3）、
   `verify_l2_joint.py`、`stage_d_final_analysis.py`

## 关键数字（V1.3.2）
- 主检验（S3+S4 合并，整数化，nsim=20000×3 种子）：**0.7719**（<80%，中等功效）
- L2 联合（主检验 ∩ 族门禁，同轮模拟）：**0.7717**；功效损失 **0.00025/种子**（5/20000）
- L3 情景化（非验证性）：0.1769；S3 单族 0.1818；S5 方向性（0.5033 @ 胜率 80%）
