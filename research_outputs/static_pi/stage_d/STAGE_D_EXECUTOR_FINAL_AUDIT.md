# STAGE_D 终局执行器最终审计（第四阶段，零调用）

**日期**：2026-11-02  
**结论**：192 块零调用 Dry-run 全部通过；终局执行器可执行 V1.3.2（裁定 A，`1001da54`）的 S0–S5 矩阵。**执行器控制流 PASS；仍余 3 项 BLOCKED（B1 真实网络行为、B2 S5 科学效应、B3 官方 tokenizer 精确计量），它们只能在 GO 后实测/校准，不阻塞工程冻结，但必须与 PASS 分列。** B4/B5/B6 已按操作员 2026-11-02 裁定收口。  
**真实模型调用**：0；**API 费用**：0；**192 真实执行**：未授权、未启动。

---

## 一、交付物

| # | 文件 | 作用 |
|---|---|---|
| 1 | `STAGE_D_EXECUTOR_ASSET_AUDIT.md` | 第一阶段代码资产审计 |
| 2 | `stage_d_executor.py` | 终局执行器（S0–S5，192 块） |
| 3 | `stage_d_executor_config.json` | 执行矩阵/预算/槽位/S5/截止配置 |
| 4 | `test_stage_d_executor.py` | 19 个零调用测试（18 默认 + 1 完整 192） |
| 5 | `STAGE_D_DRYRUN_FULL.log` | 完整 192 dry-run 日志 |
| 6 | `STAGE_D_EXECUTOR_TEST_COVERAGE.md` | 20 项检查映射与结果 |
| 7 | `STAGE_D_EXECUTOR_MATRIX.json` | 192 矩阵核验 |
| 8 | `STAGE_D_EXECUTOR_TOKEN_CAP.md` | token 上界核算（建议 9.5M，精确计量 BLOCKED） |
| 9 | `STAGE_D_EXECUTOR_SHA256.json` | 执行器产物 SHA-256 清单 |
| 10 | 本文件 | 最终审计（PASS/FAIL/BLOCKED） |

## 二、复用了什么 / 为什么必须改

| 模块 | 处置 | 理由 |
|---|---|---|
| `d2_executor.Exec` 状态机、六臂 `policy`、`detect`、`REPAIR_LIB`、S3/S4 注入 | **复用**（子类继承，D2 源码未改） | 六臂策略/修复已在 D2 108 执行中验证；不重写 |
| `stage_a/executor.py` 提示词/合同/终端构建/格式规则 | **复用**（只读） | 冻结合同与终端评分边界 |
| `terminal_quality.evaluate_terminal_quality` | **复用**（只读） | P0 评分器；执行器只消费 |
| `transport.call_model` | 经 `RealProvider` 包装；dry-run 不使用 | 真实调用默认禁用 |
| D2 `time.time()` 的 policy/detect/action | **重写为虚拟时钟版** | D2 与虚拟时钟混用会误判剩余时间 |
| 全局预算/槽位/断点/token/原始-评分分层/S5/分析输入 | **新增** | D2 只有每执行局部预算与文件级跳过 |

**未修改**：V1.3.2、`exact_perm.py`、`power_sim.py`、`stage_d_final_analysis.py`、`d2_executor.py`、`runs_d2/` 历史结果。

## 三、测试与 dry-run 证据

- 默认测试套件：**19 tests, OK (skipped=1)**；完整 192 用例单独运行 **1 test OK（4.55s）**。
- 完整 CLI dry-run：**192 记录 / 192 唯一 ID / 全部 COMPLETE**；六臂各 32；S0–S5 = 12/18/18/48/48/48（即每臂 2/3/3/8/8/8）。
- S5 竞速：π-only / Fixed-Composite / Proposed-Dynamic 各 8 次触发；Static / R-only / Simple 0 次；DS 全部胜出；取消有效/迟到两种模式均通过。
- 成本：1,451 调用；核算 ¥2.358712；实际现金代理 ¥0.080276；远低于全局硬顶 2,688 / ¥34.56。
- 双槽：最大并发 glm=2 / ds=1，无超额。
- 恢复：二次 CLI 运行 `skipped=1`；全局 calls == 记录 calls 之和，无重复计账。
- 配对一致性：S3/S4/S5 每个 `(scenario, rep)` 的 E1 基础输出在六臂间逐字相同（192 记录比对，0 差异），策略差异仅来自 action/repair。

## 三·五、P0 收口（2026-11-02 操作员裁定后，零调用）

| 项 | 状态 | 证据 |
|---|---|---|
| B5 S5 截止期 | **CLOSED（操作员裁定 90s）** | 配置 `deadline_s.S5=90`，其余 180；9.5s SLO 保留；不允许为按时率事后调整 |
| B4 保护集 | **规格收口，待一句话确认 R1/R2** | `STAGE_D_PROTECTION_SET_SPEC.md`（冻结原文+操作员裁定+8 槽合同基准）+ `protection_set_audit.py`（Mock 1,152 槽-run 路径验证，输出标 MOCK）；384=8×8×6 六臂全含；倒退=原本正确→变错误；无抵消；`protection_regressions=0` 仅 MOCK |
| B3 Token 硬顶 | **硬限已实现 + 双词表校准通过；GLM/DS 官方 tokenizer 校准仍 BLOCKED** | 预留台账：调用前 `reserve(1 tok/char+64 + max_out)`，并发互斥累加，峰值不变量 `used+reserved ≤ 9.5M`（实测峰值 2,427,390；全局 token 2,423,553 == 记录 in+out；审计中修复了 release+settle 双计）；结算归还差额；9.5M 已入配置为硬停。零调用校准：tiktoken o200k/cl100k 在 280 份真实提示词样本上最差 0.909 tok/char ≤ 预留口径 1.0（`STAGE_D_TOKEN_CALIBRATION.json`；tiktoken 为第三方 BPE，非 GLM/DS 官方 tokenizer，作交叉校验） |
| B1 真实取消 | **控制逻辑收口；真实网络行为仍 BLOCKED** | `RealProvider` 异步线程化；三态：`transport_cancel`（仅 Mock 可模拟）/`late_completed`（逻辑取消后完整响应，全额计账）/`logical_only`（取消后出错）；槽占用到线程真实结束（测试实证）；`race_log.loser_cancel_state` 记录三态；urllib 无传输级取消——真实网络下取消语义=逻辑取消+迟到全额计账，不冒充传输取消 |
| B2 S5 时延 | **工程验证完成；科学结论待真实实验** | `test_stage_d_p0.py` P05S5Boundary：边界谓词 89.9/90.0/90.1 精确；端到端两次校准法（抖动实测 0.3s → 自动降级 ±1.0 档：88.9→True、91.0→False，如实记录）；GLM 先完成/DS 先完成/双超时/取消后迟到四路径全过；Mock 不进科学统计 |
| B6 清单冲突 | **材料齐备，待操作员选 A/B** | `STAGE_D_VERSION_DIFF_V1_3_2.md`：4 处并行改动逐行归属；回退后哈希恰回 `1001da54…`（字节级恢复证明）；原版存档 `archive_1001da54/`；双层清单：`MANIFEST_STAGE_D_CORE_19.json`（锚 1001da54）+ 26 项现状；18 项共享哈希一致，唯一分叉 V1.3.2；`power_sim_v23.py` 为 `power_sim.py` 别名重复（标注不删除） |

P0 专项测试：`test_stage_d_p0.py` 14/14 通过；主套件 19 项回归 OK；完整 192 dry-run（9.5M 硬顶）192/192 COMPLETE。

## 四、PASS / FAIL / BLOCKED

### PASS（有实际测试证据）

192 矩阵；六臂/场景计数；S5 GLM 先行+SLO 9.5s 触发+DS 竞速+首个可解析胜出；取消有效与迟到响应；迟到成本入账；双槽不超额；每执行/全局调用与现金硬停；截止硬停；token 硬停；断点恢复；已完成不重跑；成本不重复；异常记录；原始/评分分离；结果进入 `stage_d_final_analysis.py`；完整 192 dry-run；Mock 零网络。

### FAIL

无（本轮测试未发现失败项）。

### BLOCKED（不得写成 PASS；仅余 3 项，均为 GO 后才能验证的真实世界属性）

| # | 项 | 原因 | 影响 |
|---|---|---|---|
| B1 | 真实网络取消/限流/并发性能 | Mock 只验证控制流；`RealProvider` 为异步 urllib，取消为**逻辑取消**（无传输级终止）；已实现 `transport_cancel`（仅 Mock 可模拟）/`late_completed`/`logical_only` 三态，迟到全额计账、槽占用到线程真实结束 | 真实网络的取消/限流/并发性能需 GO 后实测；不得用 dry-run 宣称网络性能 |
| B2 | S5 绝对时延/按时率 | Mock 时钟含线程调度噪声：48 个 S5 记录全部 `on_time=false`（~105–130s）；89.9s 是预注册压力测试预测，不是实测 | S5 科学效应只能由真实 192 执行产生；dry-run 不作时延证据 |
| B3 | 官方 tokenizer 精确计量 | 9.5M 硬顶已实现（预留台账、并发互斥、峰值不变量、结算归还）；tiktoken o200k/cl100k 280 样本最差 0.909 tok/char ≤ 预留口径 1.0，但第三方 BPE ≠ GLM/DS 官方 tokenizer | **硬预算控制 PASS；精确计量 BLOCKED**——两项必须分列验收 |

### 已收口（原 B4/B5/B6）

| # | 裁定 | 证据 |
|---|---|---|
| B4 | **CLOSED**：保护集 R1（S3/S4/S5 各 384，累计 1,152；0/1/≥2；四元组追溯；无抵消；U2 UNKNOWN） | `STAGE_D_PROTECTION_SET_SPEC.md`；`protection_set_audit.py`（R1 固定）；合成测试 6/6；Mock dry-run 枚举 1,152、倒退 864（Mock 缺 8 槽答案，标 MOCK）；`FINAL_RUNS.json` 由审计器计算，不再硬编码 0 |
| B5 | **CLOSED**：S5=90s（S0–S4=180s），SLO=9.5s；不得为按时率事后调整 | 配置 `deadline_s`；P0-5 边界回归（谓词 89.9/90.0/90.1；端到端抖动 0.3s 如实降级 ±1.0 档） |
| B6 | **CLOSED**：V1.3.2 正式依据 = A（`1001da54`）；双层清单统一锚 A；并行版 `f4d5e79a` 存档不删；旧 26 项清单转历史 | `STAGE_D_VERSION_DIFF_V1_3_2.md`（4 处逐行归属；回退后哈希恰回 1001da54）；`MANIFEST_STAGE_D_CORE_19.json`（19/19）+ `MANIFEST_STAGE_D.json`（49/49，锚 A）+ `MANIFEST_STAGE_D_HISTORY_26_F4D5E79A.json` |

## 五、关键限制与诚实声明

- 完整 dry-run 的 `stage_d_final_analysis.py` 输出 p=0.0039 是 **Mock 数据产物**（S4 Simple TP=0、Proposed 修复后 TP=2）；R1 审计对同一批 Mock 记录算出 864 倒退（S3/S4/S5 各 288，因 Mock SINK 只提供 D_1/D_2、缺 8 个保护槽），故整体 verdict=`PROTECTION_FAIL_OVERALL_NOT_MET`。**这是 Mock 缺少保护槽答案的产物，不是执行器失败，也不是科学结果。**
- Mock 的 S5 makespan（~105–130s）不是预注册 89.9s 的复现，也不构成对其的否定；真实时延需真实执行。
- 执行器代码在本轮结束后应冻结哈希；在此之前不得启动真实执行。
- 真实调用授权仍只能由操作员以明文 GO（批次名/调用上限/token 上限/现金上限）签发；本报告不构成授权。

## 六、下一步（零调用优先）

1. ~~B5 / B4 / B6 裁定~~：已完成（S5=90s；保护集 R1=1,152；V1.3.2=A）。
2. 独立审计：逐行源码、哈希、日志与统计输出可复现（见 `STAGE_D_INDEPENDENT_AUDIT.md`）。
3. 冻结执行器：`stage_d_executor.py` + 配置 + 测试 + 支撑材料 SHA-256（`STAGE_D_EXECUTOR_SHA256.json`）。
4. B1/B2/B3-精确计量：只能在 GO 后由真实 192 执行/官方 tokenizer 验证；不得用 Mock 结论替代。
5. 以上完成后，另提交 GO 申请；在此之前不启动 192 真实执行。
