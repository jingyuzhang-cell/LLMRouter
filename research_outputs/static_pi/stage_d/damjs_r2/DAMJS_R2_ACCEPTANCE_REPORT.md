# DAMJS_EXP_36 零调用验收报告

**日期**：2026-11-06　**性质**：零 API 调用（全部验收与彩排共 88 次重放执行，网络尝试 0 次）；所有原有文件未修改；**真实调用未授权**，6 次冒烟和后续 30 次各需单独 GO。
**批次清单**：`DAMJS_R2_BATCH_MANIFEST.json`，SHA `0abb146da201b7eaf958a0ccfb98de02849db46db58feb51c76b773db963dbd9`（12 个运行时组件 + 45 个溯源条目）
**验收记录**：`damjs_r2/ACCEPTANCE_RESULTS.json`，SHA `92652d9c2618d0cca57ba08ca549a6190e693e6e34290c749a56613c67892d89`，与上述清单一致

## 结论

裁决中批准的改动已全部完成：方案 4、M1–M5、F1/F2 整改、F3 限定、身份勘误、新 MANIFEST、36 次方案、截止期 130/150/240 s。零调用验收 **26/26 通过**。在实际 36 次计划上做了一次零调用彩排，预计账本为 **260 次调用、787,482 token、核算 ¥1.39**，低于硬上限 350 次、1.25M token、¥2.30。

有三点会影响论文表述，需要您知道：

1. **R 在本批次中不会被选中**。冻结的增益表 `GAIN_TABLE` 里没有 R 的条目，它的预测增益为 0，过不了"可靠正增益"门禁。因此 DAMJS 臂实际可执行的恢复只有两种：J1 的 Z_structure 和 FMT 的 Z_format；model_suspect 信号一律得到 NONE。这是冻结引擎和增益表的性质，我没有改动。
2. **截止期门禁会系统性地放弃 S3 的 J1 修复**。在 130 s 和 150 s 下，修复所需的 L̂ + σ + 预留 = 137.9 s，而实测剩余时间只有 88–109 s；只有在 240 s 下才会修复。这正是本轮要检验的机制，但也意味着 S3 在紧截止期下 DAMJS 的表现等同于 Static 臂。
3. **新发现**：在 A‴ 执行器中，S0–S4 的 swap 并不换模型，因为路由表覆盖了规格中的模型。192 次基线中 89/89 次 swap 实际是同模型重执行。Stage D 中"π/swap"的结论需要改述，已写入身份勘误第四节。

---

## 一、修改内容

所有新代码都在 `stage_d/damjs_r2/` 下；另有两份新增治理文件放在 `stage_d/` 下。原有文件一律未改动：

| 原有文件 | SHA（未变） |
|---|---|
| `stage_d_executor.py` | 64dea819 |
| `stage_d_v2_executor.py` | e80fe6a3 |
| V2 配置 | 914f3edd |
| `d2_executor.py` | df8a2de6 |
| `damsj_engine.py` | 7eec919b |
| `damsj_executor.py` | 107db96a |
| `_damsj_real_child.py` | 9d2a7716 |
| `damsj_pilot_runner.py` | 6a0f1c3e |
| `DAMJS_BATCH_MANIFEST.json` | cba7d720 |
| `MANIFEST_STAGE_D_V2.json` | 65d50ff7 |
| `MANIFEST_STAGE_D.json` | 27bccff0 |
| `EXECUTOR_IDENTITY_SUPPLEMENT.md` | 62e9494b |
| `runs_final/` | 未改动 |

新增文件：

| 文件 | 作用 |
|---|---|
| `damjs_r2/damjs_bridge.py` | 两部分：一是所有臂共用的执行护栏 Harness（L2/L3、调用账本事件、节点进度）；二是 DAMJS 臂专用的 SchedulerBridge |
| `damjs_r2/damjs_r2_child.py` | 子进程，每次执行一个 |
| `damjs_r2/damjs_r2_runner.py` | 36 次计划、硬上限、共享账本、停批规则、分阶段 GO 门禁 |
| `damjs_r2/test_damjs_r2.py` | 零调用验收套件 |
| `damjs_r2/deadline_grid_check.py` → `DEADLINE_GRID_CHECK.json` | 截止期复核 |
| `damjs_r2/build_manifest.py` | 生成批次清单（幂等：组件不变则清单逐字节不变） |
| `DAMJS_R2_BATCH_MANIFEST.json` | 新批次清单 |
| `EXECUTOR_IDENTITY_ERRATUM.md` | 身份勘误 |

### M1–M5 的落实

| 项 | 实现 | 验收 |
|---|---|---|
| M1 绑定 A‴ | 子进程导入 `stage_d_v2_executor`，使用 V2 配置 | T1：30 条时序完整的基线记录，经子进程真实调用路径全部逐字段复现 |
| M2 臂映射 | Static → Static；Current-Proposed → 原生 Proposed-Dynamic；DAMJS → Scheduler。未知标签在任何调用之前就拒绝（退出码 3） | T2 |
| M3 预算 | 批次状态目录中只有一个 `GlobalBudget` 账本，所有子进程共享，上限 350 次 / 1.25M token / ¥2.30，在预留时拒绝超限调用。每次执行结束后，对出错或被截断的调用按最坏情况补记（提示词字符数 + 64 + max_tokens）。遇到 INCOMPLETE_BUDGET、任一指标触顶、或剩余额度不足一次最小调用（4,997 token / ¥0.0119）时立即停批，并拒绝启动下一次执行 | T5（4 项）、T6 |
| M4 节点进度 | 节点完成时写入带真实输出的 `node_end`；动作导致节点重置时写入 `node_invalidate`。降级评分会剔除被重置的结果，并截止在中止时刻 | T6；T1：降级评分器在全部 COMPLETE 重放上与执行器自身 `finish()` 的 TP 一致 |
| M5 时间锚点 | 截止期从父进程启动时刻起算；子进程扣除自身启动耗时（约 1.1 s）后再交给执行器。引擎时钟 = 执行器时钟 − `ex.t0` | T6：J1 超时实测 278.28 s，理论值 D_rem − 15 = 278.29 s |
| **M6（新发现）** | 原子进程把 Current-Proposed 和 DAMJS 都映射为 `Proposed-Dynamic\|S\|r`，同一状态目录中第二个臂会被 RunStore 当作"已完成"而跳过。现改为唯一的 `exec_id = 标签\|场景\|r\|D截止期` | T1–T5 |

## 二、本批次实际运行的 DAMJS 是什么（F1/F2/F3）

**决策者**是 `damsj_engine.Scheduler`（SHA 7eec919b，未修改），流程为：`build_candidates` → 桥接层过滤 → `select`（门禁 + Pareto + 效用函数 U）→ `apply`。验收中 9 次决策全部由 Scheduler 作出，3 次动作与决策一一对应（T3）。

桥接层只做三件事，都已登记在清单中：

1. **范围过滤（F3）**：只保留 NONE、Z_format、Z_structure、R。智能体名册固定为每个角色一个，引擎没有可迁移的兼容智能体，因此不会生成 X′；Π 只有在存在可靠历史时引擎才会生成，目前没有。验收中这道过滤触发 0 次。
2. **可执行性过滤**：Z_structure 只用于有修复规格的节点（J1）；Z_format 只做一次；同一节点的重执行上限为 2。
3. **L̂ 标定**：依 V0.2.1 修正 3，L̂(a) = 受影响节点 p95 墙钟时间之和。J1 结构修复会重跑 J1、J2、SINK、FMT，合计 116.9 s；格式修复只重跑 FMT，为 0 s。这替换了引擎中每次调用 2.0 s 的占位值。σ_l、成本、σ_c 仍用引擎原值。

**History（F2）**：`apply()` 先记入一个预测增益占位值；被修复的节点完成后，用金盲观测结果覆盖它：信号清除记 +1，信号仍在记 0，节点失败记 −1。C3-a / C3-b 据此生效。T4 用持续性 J1 故障验证：DAMJS 修复一次后即禁止重复；Current-Proposed 连续修复 3 次。

**Q̂_current 取 0**：它在 U 中对所有候选是同一个常数，`feasible()` 自 V0.2.1-R2 起也不再使用它，所以对决策没有影响。

**截止期门禁实测（T3）**：

| 场景 / 截止期 | 动作 | 剩余时间 D_rem | 门槛 | 选择 |
|---|---|---|---|---|
| S3 / 130 s | Z_structure | 88.6–89.5 s | 137.9 s | NONE |
| S3 / 150 s | Z_structure | 108.5–109.4 s | 137.9 s | NONE |
| S3 / 240 s | Z_structure | 198.5–199.4 s | 137.9 s | **Z_structure** |
| S4 / 150 s r1 | Z_format | 16.85 s | 21 s | NONE |
| S4 / 240 s | Z_format | 106.9 s | 21 s | **Z_format** |

## 三、零调用验收（26/26）

| 编号 | 内容 | 关键证据 |
|---|---|---|
| T0 | 原引擎测试 29 项、包装器测试 17 项 | 全部通过 |
| T1 | A‴ 基线重放（S3/S4 × Static/Current-Proposed × 8 次重复） | 时序完整 30/30 逐字段复现；含传输错误的 1/2 复现，不一致的那条与此前全量重放中的不一致记录相同 |
| T2 | 三臂标签 | 映射精确；错拼标签与执行器内部臂名均被拒绝；Current-Proposed 在 S3 的重放中修复了 J1，Static 从不动作 |
| T3 | Scheduler 真实调用 | 决策全部来自引擎，动作与决策一一对应，门禁两个分支都被观测到 |
| T4 | History 重复约束 | 持续性故障下 DAMJS 只修复 1 次、随后被禁止，Current-Proposed 修复 3 次；C3-a / C3-b 单元测试通过 |
| T5 | 跨进程预算 | 调用上限设为 9 时：第 1 次执行后账本为 7，第 2 次执行被拒绝预留，状态 INCOMPLETE_BUDGET，随即停批；不启动下一次执行；yuan 上限和 token 上限都在首次预留时拒绝 |
| T6 | L2/L3/L4 | 卡住的 E1 调用在 120.01 s 被切断；J1 超时 = D_rem − 15；没有调用在 D − 15 之后开始；在 1:1 真实时钟下，D=40 s 的执行于 31.0 s 硬停（D − 15 加两段各 3 s 的宽限）；E 节点输出逐字保留；被截断调用按最坏情况补记（11,747 token / ¥0.0257） |
| T7 | MANIFEST | 57 个组件 SHA 全部一致；全部完成的执行都在开始和结束时校验了身份块；篡改清单后单次执行判为 INTEGRITY_FAIL，运行器也拒绝启动批次 |
| T8 | 零调用与门禁 | 网络尝试 0；重放子进程拿不到任何凭据变量；真实模式在缺少授权变量或 GO 不匹配时一律拒绝 |

套件第一次运行有 2 项失败，原因都是测试预期写错，不是代码缺陷，原始记录保存在 `ACCEPTANCE_RESULTS.attempt1.json`：

- **T3**：一次 130 s 的执行被 L3 正确终止，测试却要求被终止的子进程写出它不可能写出的字段。修正后，对被终止的执行改为检查进度日志。
- **T6**：我原先假设传输超时会触发重试。实际上 A‴ 的语义是：传输错误转为空输出，并产生 D2 信号，DAG 继续执行。这与 192 次基线中失败 E2 调用记录为 `out=0` 且节点仍完成的情况一致。

第二次全量运行全部通过；因清单时间戳重写，又以稳定清单再跑一次，仍全部通过。

## 四、截止期复核（零调用，每格 8 条基线记录）

成功的定义：TP ≥ 12，且在 D − 15 s 之前完成。Static 与 Current-Proposed 直接读各自的基线记录；DAMJS 是推算值：在记录的故障时刻套用冻结门禁，修复则取 Proposed 记录，不修复则取同次重复的 Static 记录。

| 截止期 | 场景 | Static | Current-Proposed | DAMJS 推算 | CP 修复次数 | DAMJS 修复次数 |
|---|---|---|---|---|---|---|
| 110 | S3 | 5/8 | 1/8 | 5/8 | 7 | 0 |
| 110 | S4 | 0/8 | 1/8 | 2/8 | 1 | 2 |
| **130** | S3 | 5/8 | 0/8 | 5/8 | 8 | 0 |
| **130** | S4 | 0/8 | 2/8 | 3/8 | 1 | 3 |
| **150** | S3 | 5/8 | 2/8 | 5/8 | 8 | 0 |
| **150** | S4 | 0/8 | 3/8 | 5/8 | 2 | 4 |
| **240** | S3 | 5/8 | 7/8 | 7/8 | 8 | 8 |
| **240** | S4 | 0/8 | 7/8 | 8/8 | 5 | 6 |

**确认采用 130/150/240 s**：

- 110 s 档中，S4 的 Static 只有 2/8 能在 95 s 的可用时间内完成；130 s 时为 6/8。您指出的问题由此得到证实。
- S4 的 Static 在 7/8 次基线中 TP=8，任何截止期下都达不到 TP ≥ 12。所以 S4 的联合成功完全取决于 FMT 格式修复。
- 以上只是用已有响应做的可行性推算，不是预测。

## 五、预算

- **本批次硬上限**：350 次调用 / 1.25M token / ¥2.30（核算口径），低于剩余授权 377 次 / 1,348,528 token / ¥2.3788。
- **估算**（DAMJS 按 Current-Proposed 计）：均值约 269 次调用 / 0.84M token / ¥1.52；最大约 300 次 / 1.14M token / ¥2.21。
- **零调用彩排**（实际 36 次计划，记录时延，按实际上限机制运行，`damjs_r2/rehearsal/`）：
  - 36 次全部完成，无停批，身份校验 33/33（另 3 次被截止期终止，按设计不写结束时校验），网络尝试 0；
  - 账本合计 **260 次 / 787,482 token / ¥1.392**，其中冒烟 6 次占 **44 次 / 143,703 token / ¥0.260**。
  - 注意：彩排中的 TP 不能当作结果估计。DAMJS 放弃修复时，重放给下游的响应来自"已修复 J1"的记录，会高估 TP。

## 六、本批次能声明什么、不能声明什么

- **能声明**：由经测试的 Scheduler 决策、截止期感知的选择性恢复（J1 的 Z_structure、FMT 的 Z_format），相对 Current-Proposed 在 Q/C/L 上的差异。每格 2 次重复，属探索性证据。
- **不能声明**：
  - Π、X′ 的效果，以及多智能体协同调度；
  - R 的效果——本批次不会执行 R；
  - 任何确认性结论。
- **主比较**：DAMJS vs Current-Proposed，按区组配对；Static 只作参照。各项指标定义已冻结在清单的 `design.metrics` 中。

## 七、待您 GO：6 次真实冒烟（3 臂 × S3/S4 × 240 s）

- **命令**：
  ```
  STAGE_D_REAL_CALLS_AUTHORIZED=1 DAMJS_R2_GO=smoke python3 damjs_r2/damjs_r2_runner.py --mode real --phase smoke
  ```
- **凭据**：只注入子进程环境，绝不打印。DeepSeek 默认取 provider 配置中的 `deepseek` 条目。GLM 需在 GO 时指定来源，三选一：环境变量 `STAGE_D_GLM_KEY`、`DAMJS_R2_GLM_KEY_FILE` 指向的密钥文件、或 `DAMJS_R2_GLM_PROVIDER` 指定的 provider 条目（D3 探针当时用的是 bigmodel-api-6）。
- **预计消耗**：约 44–50 次调用、0.14–0.19M token、核算 ¥0.26–0.37。GLM 免费，实付现金更低。这 6 次计入 36 次总量。
- **冒烟后我会检查**：真实调用、节点完成率、TP、成本、时延、身份记录、预算扣账，汇报后再等您对后续 30 次的 GO（`DAMJS_R2_GO=main`；运行器要求同一目录下 6 次冒烟结果齐全才会放行）。
