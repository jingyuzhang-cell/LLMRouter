# STAGE_D_FINAL_ADMISSION_REPORT.md — Stage D 最终准入审计与真实实验启动准备

**日期**：2026-11-03
**候选执行器**：`4ab0c47d642e4ec6e19b28f3725024550ea56df5842876434b55deaf5c67c997`（48,385 B）
**本轮**：零 API、零 GPU、零真实调用；不修改冻结合同/Gold/评分器/提示词；不增加预算；不开展 A5；不开发新功能。

---

## 最终结论：**NO-GO**

软件层（执行器修复、测试、Mock、R1 设计）全部就绪；但 **冻结协议的 GLM 执行配置（`thinking: disabled`）已被模型服务端以 HTTP 400 / code 1210 明确拒绝（两次独立证据）**，且本轮纪律禁止"切换推理配置绕过失败"。真实 192-run 在协议冲突解决前**不得启动**。解除条件见 §7。

---

## 第一部分：执行器审计 — **PASS**

### 1.1 三版本保全（未覆盖任何冻结资产）

| 版本 | SHA256 | 字节 | 路径 |
|---|---|---|---|
| 冻结基线（时钟修复版） | `ef50527e2920b42dd51ffec23e8a9f725a54889bc1033204ee517f8bc8f4c9c2` | 43,292 | `archive_freeze_ef50527e/stage_d_executor.py` |
| 未登记中间版（2026-11-02 12:51 部分修复） | `b0d7a58900f8f27a3e6f3451147c44204533c53dd5583ebd207a78edc83fc74a` | 44,419 | `archive_freeze_b0d7a58900f8f27a/stage_d_executor.py` |
| **新候选** | `4ab0c47d642e4ec6e19b28f3725024550ea56df5842876434b55deaf5c67c997` | 48,385 | `stage_d_executor.py` |

历史登记链完整保留：`821bd385…`（未留存）→ `d8164005…`（`archive_f9ceaf54_stage_d_executor.py`）→ `ef50527e…` → `b0d7a589…`（本轮补登记）→ `4ab0c47d…`（候选）。

### 1.2 完整 189 行 diff 核对（`STAGE_D_S5_FIX_DIFF.txt`，sha `deed0c7fb5f7db26519216c4115b5ac31a519802371463c5345aac75bfd1f29c`）

逐 hunk 审计结论——**全部改动落在 S5 结算路径与 Mock 保真，无一处越界**：

| diff 位置 | 内容 | 类别 |
|---|---|---|
| L220-226（`CallHandle._run`，仅 Mock） | `cancel_event` 仅在 `cancel_effective=True` 时提前 break；`False` 时跑到迟到响应 | **Mock 保真**（与 `_RealHandle` 三态语义对齐；`_RealHandle` 未改） |
| L454-463（`FinalExec.__init__`） | 新增 `late_threads / terminal_completed_at_s / j2_winner_completed_at_s / settlement_* / _commit_*` 字段 | S5 结算状态 |
| L680-711（`_exec_s5_j2`） | 双不可解析时先 `_finish_call` 两个句柄再置 Failed；胜者时间戳；`_after_j2(r)` **先于**败者线程 | S5 结算 |
| L711-753（新增 `_settle_loser`） | 后台等待败者、恢复 `model_used`、`s5.late*` 计账、`race_log`、settlement 记录（loser in/out/费用/取消态/异常/结束时间）+ `S5_SETTLEMENTS.jsonl`（append + fsync） | S5 结算 |
| L853-872（`finish`） | **移除败者 join**；记录 `terminal_completed_at_s`（=makespan）、`j2_winner_completed_at_s`、`settlement_pending`、`settlement` | S5 结算（时间分离） |
| L918-952（新增 `settle` / `recommit_with_settlement`） | 批次尾部 join；把迟到成本/token/raw/race/s5 合并回已提交记录（原子重写） | S5 结算 |
| L1053-1074（`main`） | 收集 `execs`；循环后统一 `settle()+recommit` | S5 结算（批次级） |

**未改动**（逐项确认）：`detect/policy/apply_action`（质量选择、重执行、模型分配）、臂定义、矩阵/种子/分块随机化、预算与预留台账、槽管理、截止期、`RealProvider/_RealHandle`（真实传输）、评分调用、断点仓库。删除的 9 行全部是被上述逻辑替换的旧同步结算代码。

### 1.3 测试证据

| 套件 | 结果 | 证据 |
|---|---|---|
| 主套件（p0 + executor + clock + protection） | **48 passed, 1 skipped**（修复前 44+1；新增 4 项 S5 结算测试后 48+1） | `STAGE_D_S5_FIX_TEST.log` |
| `test_stage_d_v2_transport.py` | **4 passed** | 同上 |
| 新增 S5 结算测试 | 4/4：finish 先返回（`settlement_pending=True`、makespan<败者延迟、结算时间>终端时间）；败者不覆盖胜者（state/outputs/score/status 不变）；双分支成本全额（`settled==Σraw`、`late>0`）；双不可解析回退（`S5_BOTH_UNPARSEABLE`） | `test_stage_d_executor.py::T07S5Settlement`（sha `56614a8f371e2ce5…`） |
| 既有回归 | winner-only makespan、SLO 等待、非 race 臂、迟到成本、槽上限、预算上限、时钟 5 项、R1 审计器单元 | 含于 48+1 |
| 192 Mock（控制流，非科学结果） | **192/192 COMPLETE**；1,451 calls / ¥2.358712 / 2,423,553 tokens；24 条 settlement；`settlement_pending` 清零 | `runs_s5fix_mock3/`、`STAGE_D_S5_FIX_MATRIX.json`（192、六臂各 32） |

测试文件改动披露：`test_stage_d_executor.py`（新增 T07 + `run_one` settle 参数）sha `56614a8f371e2ce5812a302219c36ec6bb1665b56d7b685abf66ccc5cdfbe913`；`test_stage_d_p0.py`（`run_one` 增 settle 步骤）sha `9349d2f91e5afe7a19ed2d6dd6498571f6c2b28d82d9acc2fe5165bcf5fcde3a`。

**第一部分判定：PASS**（候选 `4ab0c47d…` 与 diff 一致；范围未越界；测试全绿；冻结资产零覆盖）。
遗留：候选执行器**尚未获操作者正式批准**（见 §7-1）。

---

## 第二部分：已知 S5 边界 — **PASS（继承既有裁定，无需新批准）**

既有裁定（`QF_GOVERNANCE_PLAN.md` L314，2026-11-02）：

> **容差裁定（操作者）——接受 S5 ±1 例，定级 PASS WITH KNOWN NONDETERMINISM（有条件通过）**……两条 S5 差异（`Static|S5|r1`、`R-only|S5|r4`）全部保留不删不选择性重跑；Makespan 为 S5 主要连续指标；按时率辅助描述不宣称确认性优效；容差仅用于执行器 Mock 回归退化判定，不进入正式实验统计规则。

本轮 192 Mock（`runs_s5fix_mock3`）与该裁定**同两条目、同方向区间**：

| exec_id | 旧 run1 | 旧 run2 | 新（S5 修复后） |
|---|---|---|---|
| `Static|S5|r1` | INCOMPLETE_DEADLINE（131.8s） | COMPLETE（125.6s） | COMPLETE（128.0s） |
| `R-only|S5|r4` | COMPLETE（126.5s） | INCOMPLETE_DEADLINE（170.5s） | COMPLETE（126.7s） |

两例均为**非 race 臂**（Static/R-only，不经过 S5 竞速代码路径），S5 结算修复不可能影响它们；翻转属 D=90s 与期望总时延重合的亚秒抖动，即原裁定所接受的同一现象。其余 190/192 逐 run 一致（status/tp/calls）。

**第二部分判定：PASS——继承 2026-11-02 操作者裁定，不重复要求批准。** 报告纪律四条继续沿用（COMPLETE 一律按边界如实报告；两例保留；makespan 为主；容差不进正式统计）。

---

## 第三部分：DD-V4 / DD-V5 — **N/A（无共享代码依赖）**

| 检查 | 结果 | 证据 |
|---|---|---|
| `/root/zcode_wt_deadline_audit` | **不存在**（`ls` 返回 ABSENT；`/root/.worktrees/` 下亦无同名） | 本轮 `ls` 实测 |
| `/root/cap_eval_bench_v1` | 存在，含 `DD_V51_JOINT_EXPERIMENT_*`、`dd_v51_joint_experiment.py` 等 | 目录清单 |
| Stage D 候选对 cap_eval/worktree 的依赖 | **零**：`stage_d_executor.py` 的 import 仅 `d2_executor`（本地）、`stage_a/executor`、`capital_opinion_pilot/transport`、标准库 | 源码 L17-33 |
| cap_eval / DD worktree 对 Stage D 的依赖 | **零**：`grep -rl "stage_d_executor\|static_pi"` 在 `/root/cap_eval_bench_v1`、`/root/.worktrees/codex-dd-v51-*` 无命中 | grep 实测 |
| 共享中间层 | `capital_opinion_pilot/transport.py`（sha `7a423eb38d07592a…`）为两边各自独立使用的传输库，属基础设施而非 DD-V4/V5 测试 | 源码 |

**依据**：Stage D 与 DD-V4/V5 代码库互不引用、无共享被测对象；DD-V5.1 是独立项目（cap_eval_bench_v1）的联合实验，不构成 Stage D 执行器的回归测试。将其测试冒充 Stage D 回归违反纪律。

**第三部分判定：N/A**——Stage D 新候选无 DD-V4/V5 共享代码依赖，该项不构成本实验准入条件。（若操作者认为存在应跑的跨项目回归，请指认具体文件，我将另行执行。）

---

## 第四部分：R1 真实保护门禁 — **PASS（设计就绪；执行 BLOCKED 于真实数据，属预期）**

### 4.1 冻结规格（未修改）

`STAGE_D_PROTECTION_SET_SPEC.md`（sha `080ccc4d578a92f6822b7b62d112872d35cac5166ad001d53aaa7707de894d`）、`PROTECTION_BASELINE.json`（`652f3ea4…`）、`protection_set_audit.py`（`e9974f0e…`，单元测试 PASS）。

### 4.2 真实 SINK 输出必须覆盖的保护槽位（8 槽）

| 槽 | 期望 | 参考正确范围 |
|---|---|---|
| B1 / B2 | `证监立案字01120260037号` | 六臂 × S3/S4/S5 |
| B4 | `证监立案字0262026012号` | 同上 |
| E1（critical） | `1`（跨文档同一份文书） | 同上 |
| F3 | `2026-10-09`（收到日） | 同上 |
| U2 | **保持 UNKNOWN**（断言具体日期 = 倒退） | 同上 |
| F1 | `2026-10-09`（D1 落款日） | **仅修复臂**（R-only/Fixed/Proposed）× S3/S4/S5 |
| F2 | `2026-10-10`（D2 落款日） | 同上 |

审计输入 = 每条真实记录的 `score.claim_results`（值层 CORRECT 判定）+ U2 断言检查；总分母 1,152 = 8 槽 × 8 重复 × 6 臂 × S3/S4/S5。

### 4.3 最小首批真实覆盖（冻结顺序，seed `20261102`，不改任务顺序）

`build_order(cfg)` 计算：前 **24 次执行**恰好包含 S3(r4)、S4(r8)、S5(r8) 三个**完整六臂块**（位置 6-12 / 0-6 / 18-24），另有 S1 一块。即首批即覆盖 **8 槽 × 6 臂 × 1 重复 × 3 场景 = 144/1,152 槽-run（12.5%）**，且 S3/S4/S5 三场景各得 48。

### 4.4 Stop-gate 设计（预登记）

1. 预检通过后，先执行 `--real --limit 24`（约 ≤192 次调用，预算占比 ≤7%）。
2. 对 `runs_final/` 运行 `protection_set_audit.py`：**真实 verdict = FAIL（≥2 槽-run 倒退）→ 立即停止整个真实实验**，保留现场，逐四元组报告；PASS / PASS WITH REGRESSION（≤1）→ 继续剩余 168 次执行。
3. 后续每完成一个场景块可复查；最终 `FINAL_RUNS.json` 的 `protection_regressions` 由脚本从真实记录计算，不得手工填数。
4. Mock 审计结果（864 regressions）**不得**作为 R1 证据——已确认系 mock SINK 只输出 D_1/D_2 的 fixture 限制。

**第四部分判定：PASS（设计与最小覆盖已定）；真实计数 BLOCKED 于真实执行（预期内，非缺陷）。**

---

## 第五部分：真实实验准备 — **BLOCKED（协议兼容性冲突，非配置缺失）**

### 5.1 端点 / 模型 / 参数 / 凭据核对

| 项 | 冻结值 | 状态 |
|---|---|---|
| GLM 端点 | `https://open.bigmodel.cn/api/anthropic/v1/messages`（`transport.py` L11，sha `7a423eb38d07592a…`） | 已核 |
| GLM 模型 | `GLM-5.3-Flash`（alias `glm53flash`） | 已核 |
| **GLM thinking** | **`{"type":"disabled"}`（transport.py L33 固定）** | **✗ 已被服务端拒绝（见 5.2）** |
| max_tokens | E 2000 / J1 3000 / J2 4000 / SINK 4000（`d2_executor.py MAXTOK`） | 已核 |
| temperature | 透传（默认省略） | 已核 |
| DS 端点/模型 | `api.deepseek.com` / `deepseek-flash` / `thinking disabled` | 已核 |
| DS 凭据 | provider_config `deepseek` 规则（len 35，在册） | 已核（不显示值） |
| **GLM 凭据** | `transport.glm_key()` 取 provider_config **第一个** `bigmodel-api` 规则（suffix FSAK）；**2026-11-03 实测可用的 key（A5 线，suffix Fhzp）不在 provider_config 中**，两者不是同一把 | **待预检裁决** |

### 5.2 阻塞：冻结执行配置与模型服务冲突（两次独立 1210 证据）

| 日期 | 请求 | 结果 | 现场 |
|---|---|---|---|
| 2026-11-02 | Anthropic 端点 + `thinking:disabled`（资源包 key） | **HTTP 400 / code 1210**"该模型始终思考，不支持关闭思考；请使用 low、high 或 max" | `runs_a5_planA/precheck/precheck.json` |
| 2026-11-02 | 同端点 + `thinking:disabled`（新订阅 key） | **HTTP 400 / code 1210**，同文案 | 治理记录 L350 |
| 2026-11-03 | 同端点 + `reasoning_effort=low`（无 thinking 字段） | **成功**（end_turn，2 次真实调用） | `runs_a5_planAPrime_v2/run1/C/J1.json` |

即：**V1.3.2(A) 冻结的 `glm53flash + thinking disabled` 在当前 GLM-5.3-Flash 服务上不可执行；任何预检都会以 1210 失败。** 治理记录 L327/L350 已声明此协议迁移需重新预注册；`STAGE_D_FINAL_PREREGISTRATION_V2_0_DRAFT.md`（thinking=low 路线）**仍是 DRAFT，未冻结**。本轮纪律明确禁止"切换模型、端点或推理配置来绕过失败"——故不能以改 transport 的方式放行。

### 5.3 预算核对（未增加）

| 项 | 冻结值 | 本轮消耗 |
|---|---|---|
| 调用 | 2,688 | 0 |
| Token | 9,500,000 | 0 |
| 现金 | ¥34.56 | ¥0 |
| 预检预留 | **1 次真实预检计入 2,688 总额**（单次 ≤4,000 out ≈ ¥0.003 级） | 未执行 |

### 5.4 正式执行命令与分批停止方案（仅授权后生效）

```bash
# 预检（1 次，计入总额；失败即停，不重试/不换配置）
python3 /root/research_outputs/static_pi/stage_d/precheck_real.py   # 需先按 §7-2 裁定结果定参数

# 首批 24 次（R1 stop-gate 前置）
cd /root/research_outputs/static_pi/stage_d
STAGE_D_REAL_CALLS_AUTHORIZED=1 python3 stage_d_executor.py run --real --out runs_final --limit 24
python3 protection_set_audit.py runs_final          # FAIL(≥2) → 全停

# 通过后继续（断点续跑，自动跳过已完成）
STAGE_D_REAL_CALLS_AUTHORIZED=1 python3 stage_d_executor.py run --real --out runs_final
python3 stage_d_executor.py build-analysis-input --out runs_final
```

停止规则不变：任何 HTTP 非 200 / 429 / 401 / 1210、截断、预算触顶、R1 FAIL → 立即停止、保留现场、不重试、不换端点/模型/推理配置。

### 5.5 六臂矩阵

未改动：`Static / R-only / π-only / Simple-Dynamic / Fixed-Composite / Proposed-Dynamic` × 32；策略定义零变更（diff 审计 §1.2 佐证）。

**第五部分判定：BLOCKED**（§5.2 协议冲突 + §7-1 候选未批准 + 预检未执行）。

---

## 第六部分：汇总表

| 部分 | 判定 | 关键证据 |
|---|---|---|
| 1. 执行器审计（三版本/diff/范围/测试） | **PASS** | §1.1-1.3；diff sha `deed0c7f…`；48+1 & 4 passed |
| 1b. 候选执行器正式批准 | **BLOCKED（待操作者）** | `4ab0c47d…` |
| 2. S5 边界两例 | **PASS（继承 2026-11-02 裁定）** | 治理 L314；§2 表 |
| 3. DD-V4/V5 | **N/A** | 目录缺失 + 零共享依赖（§3） |
| 4. R1 真实门禁设计 | **PASS**（数据侧 BLOCKED 属预期） | §4；首批 24 执行 =144 槽-run |
| 5. 真实实验准备 | **BLOCKED** | §5.2 两次 1210；V2.0 仍 DRAFT |
| — 预算 | 未增加（2,688/9.5M/¥34.56） | config sha `11e52032…` |
| — `runs_final/` | 不存在 | `ls` 实测 |

---

## 第七部分：剩余阻塞与解除条件（全部满足前维持 NO-GO）

| # | 阻塞 | 解除条件 |
|---|---|---|
| 1 | 候选执行器未批准 | 操作者批准 `4ab0c47d…`（或指定修改后重审） |
| 2 | **冻结协议 `thinking:disabled` 被模型服务拒绝（1210×2）** | 操作者三选一：**(a)** 授权按 `STAGE_D_FINAL_PREREGISTRATION_V2_0_DRAFT.md` 走 thinking=low 重新预注册（预检→profiling→pilot→功效重算→新预算→新冻结，V2.0 目前 DRAFT 不可直接执行）；**(b)** 指定支持 disabled 的模型/端点（同为协议变更，需新冻结）；**(c)** 裁定不运行 Stage D 真实批次，保留 D2/Stage C 历史证据 |
| 3 | GLM 凭据身份未验证（transport 默认 key ≠ 已实测可用 key） | 预检时裁决；若需改用已验证 key，属配置变更，需操作者确认注入方式（环境变量，值不落盘不进对话） |
| 4 | 真实 R1 stop-gate 方案待确认 | 操作者确认 §4.4（首批 24 执行 + FAIL 即全停） |
| 5 | 真实预检未执行 | 以上解除后执行 1 次预检；失败即停 |

---

## 最终结论：**NO-GO**

软件与审计链全部就绪（执行器修复 PASS、边界继承 PASS、DD-V4/V5 N/A、R1 设计 PASS）；**唯一硬阻塞是冻结执行配置与模型服务的协议冲突（`thinking:disabled` → 400/1210，两次独立证据），以及由此派生的重新预注册/凭据/预检未完成。** 在操作者对 §7-2 作出裁定并完成相应冻结与预检之前，Stage D 192-run 真实实验不得启动。

**本轮零 API、零 GPU；未修改冻结合同、Gold、评分器、提示词；预算未增加；`runs_final/` 未创建。等待操作者正式授权。**
