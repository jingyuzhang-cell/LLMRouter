# STAGE_D 独立审计报告（2026-11-02，零调用）

> **审计证据地位（2026-11-02 操作员裁定）**：本报告经操作员批准，作为核心 19 第 19 项的正式审计证据，**替代**被并行进程覆盖的 `STAGE_D_SOURCE_AUDIT.md`。这是 **AUDIT_EVIDENCE_REPLACEMENT（审计证据替代）**，**不是原始文件恢复**；污染版完整归档 `archive_parallel_f4d5e79a/STAGE_D_SOURCE_AUDIT.contaminated.md`，其锚点/当前哈希与替代关系记录在 `MANIFEST_STAGE_D_CORE_19.json` 的 `replacement_record` 中。
>
> **独立复核声明**：本报告结论由独立于执行器实现的命令复核（测试套件、哈希重算、192 dry-run 复跑、D2 数据反演、R1 保护集枚举、tiktoken 校准），不采信执行器自报 PASS；但这是同一工作区的机器复核，**不是第三方人工审计**。若需第三方人工审计，另行安排。

**审计对象**：V1.3.2（裁定 A）、exact_perm.py、power_sim.py、stage_d_final_analysis.py、stage_d_executor.py 及其配置/测试/日志/清单。  
**方法**：逐行读源码；重跑全部零调用测试与 192 dry-run；重算 19/完整清单哈希；D2 数据反演；R1 保护集枚举；tiktoken 双词表校准。  
**真实模型调用**：0；**API 费用**：0；**192 真实执行**：未授权。

---

## 〇、三项独立结论（先给结论，后给证据）

| # | 结论 | 判定 | 边界 |
|---|---|---|---|
| 1 | **预注册（科学/统计/证据）PASS** | **PASS（科学核心 18/18）** | 核心 19 的第 19 项 `STAGE_D_SOURCE_AUDIT.md` 被并行进程覆盖，**1 项 BLOCKED**；因此核心清单整体为 **18/19 + 1 BLOCKED**，不称 19/19 |
| 2 | **执行器（工程链路）PASS** | **PASS（控制流）** | B1 真实网络行为、B2 S5 科学效应、B3 官方 tokenizer 精确计量 **GO 后才能验证**，与 PASS 分列 |
| 3 | **独立审计（可复现性）PASS** | **PASS（制品集）** | Mock 的 p=0.0039 / 保护集 864 是软件测试产物，**不作科学证据** |

**一句话**：科学核心、执行器控制流与制品可复现性均通过独立复核；唯一未闭合的是被并行覆盖的支撑审计文档（非科学文件）。**GO 未签发，192 次执行继续 HOLD。**

## 一、预注册审计

### 1.1 正式依据（裁定 A）

| 文件 | SHA-256 | 字节 | 状态 |
|---|---|---|---|
| `STAGE_D_FINAL_PREREGISTRATION_V1_3_2.md` | `1001da54b31f575b923d5fef364aaefcaedb3b35aea4302808c7e6edd71a2c45` | 13094 | **PASS（唯一正式依据）** |

- 并行版 `f4d5e79a…`（13515B）已归档 `archive_parallel_f4d5e79a/`，不删除；其 4 处改动（清单簿记 2 + 数值注释 2）逐行归属见 `STAGE_D_VERSION_DIFF_V1_3_2.md`；回退后哈希**恰回 1001da54**（字节级恢复证明）。
- 两条数值注释（L2 损失 0.00025/种子；独立相乘高估 ≈309 倍）**未并入 A**；如需要，另走 V1.3.3 增补页。

### 1.2 科学/统计核心文件（18/18 PASS）

| 文件 | SHA-256 | 字节 | 复核结论 |
|---|---|---|---|
| `exact_perm.py` | `09468d2488ba3d6d6ba02f2c91c68f12bd6e8fc17954e362d2d843ca08e7fd6e` | 6079 | PASS：零差剔除/平均秩/2^m 全枚举/W+ 方向正确；D2 反演 S3=0.125、S4=0.03125；压力测试 0.00390625/0.63671875/1.0；300 例向量化==暴力；2000 例 scipy 交叉 0 不一致；`m>16` 拒绝 |
| `power_sim.py`（V2.3） | `4eb9d3c55a7f59bba9104fe9d977a8b5e39ed675823c81466f328f34bb68edbe` | 7492 | PASS：同批联合模拟 L2=0.7717、门禁 0.9963、主检验 0.7719；三种子 0.7688/0.7767/0.7703；L3=0.1769 标非验证性；四类计数恒等式成立 |
| `stage_d_final_analysis.py` | `037fa446c440c856ea0366d9e331bc8fa49d3a8f84318576f496c6a8e66c773e` | 9490 | PASS（含版本注记）：精确检验/族门禁/保护集三分支/HL·CI·LOO 与预注册一致；自检 5 例 + bool 拒绝全过。**版本注记**：并行进程在 8948B 版（`f03a50f2…`）基础上加入严格输入校验（bool 拒绝、TP∈[0,23]）与 bool 自检；统计逻辑与判定措辞未变；CORE-19 锚定当前 `037fa446` |
| V1/V1.1/V1.2/V1.2 FULL/V1.3/V1.3.1 | 见 `MANIFEST_STAGE_D_CORE_19.json` | — | PASS（历史版本保留） |
| D2 证据（d2_executor/报告/日志/analyze） | 见 CORE-19 | — | PASS（历史执行证据未改） |

### 1.3 裁定项落实

- **S5=90s**（S0–S4=180s，SLO=9.5s）：配置 `deadline_s` 已落实；P0-5 边界回归通过。
- **保护集 R1**：S3/S4/S5 各 384，累计 **1,152**；8 槽基准从冻结合同逐项提取；审计器固定 R1；合成测试 6/6；`FINAL_RUNS.json` 由审计器计算，**不再硬编码 0**。
- **Token 9.5M**：硬顶已入配置；预留台账（调用前预留、并发互斥、峰值不变量、结算归还）通过；tiktoken o200k/cl100k 280 样本最差 **0.909 tok/char ≤ 预留口径 1.0**。

### 1.4 未闭合项（支撑文档，非科学文件）

`STAGE_D_SOURCE_AUDIT.md`：

- CORE-19 锚点 `d75c053d…`（15937B）与当前磁盘 `47254278…`（17941B）**均非操作员审阅版**；当前版本含"26 项 / ZIP / 分支"等与裁定 A 不一致的并行内容。
- 无干净副本（已搜索全盘）；污染版归档 `archive_parallel_f4d5e79a/STAGE_D_SOURCE_AUDIT.contaminated.md`。
- **判定：BLOCKED（核心 19 的 1 项支撑文档）**。科学核心 18/18 不受影响。
- **建议**：以本报告 `STAGE_D_INDEPENDENT_AUDIT.md` 替换该支撑文档作为核心第 19 项（需操作员一句话批准）；在批准前不称核心 19/19。

## 二、执行器审计（控制流 PASS）

**源码**：`stage_d_executor.py`，`b0d7a58900f8f27a…`（44419B；冻结快照 `archive_freeze_b0d7a58900f8f27a/`）。以子类继承 D2 `Exec`，未修改 `d2_executor.py`/`exact_perm.py`/`power_sim.py`/`stage_d_final_analysis.py`/`runs_d2/`。**版本注记**：冻结候选含并行新增的 `make_clock` 时钟选择单点（`--real` 使用 scale=1.0，mock 保持配置缩放；已在 `main` 接入）；全量 192 dry-run 在本版本复跑通过（192/192、token 台账相等、保护集 864 Mock）。

**逐项复核**：
- **矩阵**：192 = 6 臂 × 32；S0/S1/S2/S3/S4/S5 = 2/3/3/8/8/8；ID 唯一；分块随机种子 20261102。
- **S5**：GLM 先行；SLO=9.5s 在途触发（记录 `j2_start_at`/`trigger_at`/`in_flight_at_trigger`）；GLM→DS 竞速；首个可解析胜出；`transport_cancel`/`late_completed`/`logical_only` 三态；迟到全额计账；双槽 K_glm=2/K_ds=1 不超额。
- **预算**：每执行 14 调用/¥0.18；全局 2,688/¥34.56；Token 9.5M；调用/现金/Token 均在调用前硬停；实测 192 dry-run 1,451 调用、核算 ¥2.358712、全局 token 2,423,553 == 记录 in+out、峰值 used+reserved 2,427,390 ≤ 9.5M、结束预留归零。
- **恢复**：已完成块不重跑；全局成本持久化；二次运行 `skipped=1`；无重复计账。
- **记录**：唯一 `exec_id`；`raw` 与 `score` 分层；异常/动作/决策/竞速日志齐全；六臂配对基础输出一致（S3/S4/S5 每个 scenario/rep 的 E1 raw text 0 差异）。
- **零网络**：默认 Mock；`--real` 需 `STAGE_D_REAL_CALLS_AUTHORIZED=1`，本轮未使用。

**审计发现并修复（本轮）**：P0-3 初版 `release_reservation` 与 `_settle` 各加一次实际 token，导致全局台账双计（记录 2,423,553 vs 全局 4,847,106）。已修为仅由 `release_reservation` 记 token、`_settle` 只结算现金；新增端到端不变量断言（全局 == 记录 in+out）。修复后 192 dry-run 复跑：2,423,553 == 2,423,553，峰值 2,427,390。

**审计发现并修复（S5，预启动阻断）**：冻结版 `ef50527e` 在 S5 竞速中先结算胜者、再调用败者 `_finish_call`（`h.done.wait()`），真实 urllib 逻辑取消不终止请求，J2 被 GLM 29.4s 阻塞，竞速退化为静态 GLM，89.9s/15.8s 时间模型失效。修复：胜者立即 `_after_j2`（SINK 不被阻塞），败者进入后台结算线程，`finish` 在 makespan 记录后 join；迟到成本/槽/token 全额入账。验证：迟滞专项 Proposed 22.8s vs Simple 40.9s；修复版 192 Mock Proposed S5 111.2s vs Simple 126.5s（Mock 时钟，不作科学证据）；S5 控制流路径 PASS 恢复，B2 科学效应仍 BLOCKED。

**测试证据**：
- 主套件 19 tests OK（18 默认 + 完整 192 单独 OK）；
- P0 专项 15/15；
- 保护集 R1 6/6；
- 完整 192 dry-run：192/192 COMPLETE。

## 三、独立复现命令

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

哈希校验：`MANIFEST_STAGE_D_CORE_19.json`（18/19 + 1 BLOCKED）、`MANIFEST_STAGE_D.json`（完整交付清单）、`STAGE_D_EXECUTOR_SHA256.json`（执行器产物）；命令见各清单 note。

## 四、BLOCKED（真实世界/精确计量，不得写成 PASS）

| # | 项 | 为什么不能在本轮 PASS |
|---|---|---|
| B1 | 真实网络取消/限流/并发性能 | Mock 只验证控制流；`RealProvider` 为异步 urllib，取消是**逻辑取消**，无传输级终止；三态已实现、迟到全额计账，但真实网络行为需 GO 后实测 |
| B2 | S5 绝对时延/按时率 | Mock 时钟含调度噪声；89.9s 是压力测试预测，不是实测；S5 科学效应只能由真实 192 执行产生 |
| B3 | 官方 tokenizer 精确计量 | 9.5M 硬预算控制 PASS；tiktoken 是第三方 BPE，≠ GLM/DS 官方 tokenizer；精确计量 BLOCKED，须与硬预算控制分列验收 |
| — | `STAGE_D_SOURCE_AUDIT.md` | 被并行覆盖，无干净副本；支撑文档 BLOCKED（见 §1.4），不是科学文件 |

## 五、明确不宣称

1. Mock 的 `p=0.0039` 与保护集 864 倒退（S3/S4/S5 各 288）是 **Mock 记录缺少 8 个保护槽答案**的产物；整体 verdict `PROTECTION_FAIL_OVERALL_NOT_MET` 是软件测试结果，**不是科学结论**。
2. 不宣称 89.9s 已实测、不宣称 S5 时延优势已确认。
3. 不宣称 9.5M 为官方 tokenizer 精确值；只宣称它是保守硬预算上界。
4. 不宣称 192 次真实执行已授权或已启动。

## 六、最终判定

| 验收 | 结论 |
|---|---|
| 预注册（科学/统计/证据） | **PASS（18/18 科学核心）**；核心 19 的 1 项支撑文档 **BLOCKED**，待操作员批准以本报告替换 |
| 执行器（工程链路） | **PASS（控制流）**；B1/B2/B3-精确计量待 GO |
| 独立审计（可复现性） | **PASS（制品集）**；污染支撑文档已归档，不进入正式审计链 |

**当前状态：HOLD。** 无真实调用；192 次执行未授权；GO 仍只能由操作员明文签发。完成 §1.4 的支撑文档替换批准后，方可冻结执行器并进入 GO 申请。
