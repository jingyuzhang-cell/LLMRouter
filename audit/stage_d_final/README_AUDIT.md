# Stage D 终局预注册审计包（分支 stage-d-final-prereg-audit）

状态：**HOLD，零调用**。192 次执行未授权。

## 目录结构
- `artifacts/` — **26 项材料逐个独立文件**（可用 GitHub API 逐个读取并自行重算 SHA-256）
- `MANIFEST_STAGE_D.json` — 26 项全 64 位 SHA-256（不含清单自身）
- `PACKAGE_SHA256.txt` — artifacts/ + MANIFEST + ZIP 的全部哈希
- `STAGE_D_AUDIT_PACKAGE.zip` — 同一批材料的压缩包

## 独立核验步骤（不依赖本包内的任何声明）
1. `gh api repos/jingyuzhang-cell/LLMRouter/contents/audit/stage_d_final/artifacts/<file>?ref=stage-d-final-prereg-audit --jq .content | base64 -d | sha256sum`
2. 与 `MANIFEST_STAGE_D.json` 的 `artifacts.<file>.sha256` 比对
3. 重点文件：`STAGE_D_FINAL_PREREGISTRATION_V1_3_2.md`（终版预注册）、`exact_perm.py`（正式检验）、
   `power_sim.py` / `power_sim_v23.py`（功效模拟，V2.3）、`verify_l2_joint.py`（L2 四类计数）、
   `stage_d_final_analysis.py`（终局分析唯一入口）

## 关键数字（V1.3.2）
- 主检验功效（S3+S4 合并，整数化，nsim=20000×3 种子）：**0.7719**（<80%，中等功效）
- L2 联合（主检验 ∩ 族门禁，同轮模拟）：**0.7717**；功效损失精确 **0.00025/种子**（5/20000）
- L3 情景化（非验证性）：0.1769
- S3 单族：0.1818；S5：方向性（0.5033 @胜率80%）
