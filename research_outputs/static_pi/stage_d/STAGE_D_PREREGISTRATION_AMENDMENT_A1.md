# STAGE_D 预注册修订 A1（执行配置修正；GO）

**状态：FROZEN / GO（操作者 2026-11-03 "授权"）。**
**上位**：V1.3.2(A)（sha `1001da54…`，未覆盖）+ `STAGE_D_FINAL_ADMISSION_REPORT.md` §7 解除条件。
**执行器（A1 版）**：`d4acad3736934d440ebc33e2e6f5965fb44770cf24aa18554cd04be9cbf26067`

---

## 一、授权范围（对应准入报告 §7 五项）

| # | 准入条件 | 本修订 |
|---|---|---|
| 1 | 批准候选执行器 | S5 修复候选 `4ab0c47d…` 获批；A1 在其上仅追加真实传输适配与预检命令 |
| 2 | 协议冲突三选一 | **采纳 (a) 的最小子集**：GLM 真实请求 = `reasoning_effort="low"`、**无 thinking 字段**（同操作者 2026-11-03 为 A5 批准的修正 schema）；**其余一切冻结项不变**。V2.0 DRAFT 的 profiling/pilot/功效重算**不在本次授权内**——由预登记的预检决策表与首批 24 次监控替代（见 §四） |
| 3 | R1 stop-gate | 确认：首批 24 次 → `protection_set_audit.py runs_final` → **FAIL(≥2) 立即全停** |
| 4 | GLM key 注入 | 仅环境变量 `STAGE_D_GLM_KEY`（桥接 `/root/.config/a5/glm.env` 中 2026-11-03 实测可用 key；值不落盘、不进对话、不写入代码）；DS key 从 provider_config 桥接至 `DEEPSEEK_API_KEY` |
| 5 | 一次受控预检 | 最坏节点 J2、冻结历史提示词、冻结 4000 上限；按 §四决策表判定 |

## 二、A1 代码变更（相对 `4ab0c47d…`，全部在 stage_d_executor.py 内）

1. `glm_low_call()`：Anthropic 端点、GLM-5.3-Flash、`reasoning_effort="low"`、无 thinking；凭据仅 `STAGE_D_GLM_KEY`，缺失即报错（不静默回退未验证 key）。
2. `stage_d_real_transport()`：GLM→low 适配层；deepseek→冻结 `transport.call_model`。**冻结共享件 `transport.py`（`7a423eb3…`）零改动。**
3. `main() --real` 注入 `transport_fn=stage_d_real_transport`。
4. `precheck` 子命令：1 次真实 J2 调用（`runs_x/run1/J2X.json` 冻结提示词，system sha `7ca250ac…`；MAXTOK 4000；GO 门 `STAGE_D_REAL_CALLS_AUTHORIZED=1`）。

回归证据：主套件+v2 transport **52 passed, 1 skipped**；192 Mock（`runs_a1_mock`）192/192 COMPLETE、1,451 calls、与 `runs_s5fix_mock3` **逐 run 零差异**（Mock 路径不受 A1 影响）。

## 三、不变项

六臂矩阵/策略定义/任务/Gold/提示词/评分器/预算（2,688 / 9.5M / ¥34.56）/截止期（S0–S4 180s、S5 90s、SLO 9.5s）/种子与分块随机化/R1 保护规格/统计方案（exact_perm 精确符号翻转）。预检 1 次计入 2,688 总额。

## 四、预登记决策表（预检与首批）

**预检（1 次 J2 真实调用）**：

| 结果 | 动作 |
|---|---|
| HTTP 错误 / 429 / 401 / 1210 / 超时 | **STOP**：不重试、不换端点/模型/配置 |
| 200 + `stop=max_tokens`（截断） | **STOP**：冻结 4000 上限不足；不得自动提高（提高=新授权+预算重算） |
| 200 + end_turn/null + JSON 可解析 + **J2 时延 > 90s** | **STOP**：证据表明冻结截止期体系（180s/90s/SLO 9.5s）在 low 模式下不可行 → 需 V2.0 全链重预注册，报告操作者 |
| 200 + end_turn/null + JSON 可解析 + **J2 时延 ≤ 90s** | **PROCEED_FIRST_BATCH_24** |

依据：A5 实测 low 模式 J1 65s / J2 108s（8192 上限）——若 J2 在 4000 下仍 >90s，串行链 E→J1→J2→SINK 大概率越过 180s 截止期，届时绝大多数执行将 INCOMPLETE_DEADLINE，臂间比较失去意义；宁可在 1 次调用处停止，不烧 2,688 预算。

**首批 24 次（R1 stop-gate 前）**：

- 命令：`STAGE_D_REAL_CALLS_AUTHORIZED=1 python3 stage_d_executor.py run --real --out runs_final --limit 24`（覆盖 S3/S4/S5 各一个完整六臂块 = 144/1,152 保护槽-run）。
- R1 门：`python3 protection_set_audit.py runs_final` → **FAIL（≥2 倒退）立即全停**。
- 附加监控（预登记）：首批 24 中 **INCOMPLETE_DEADLINE ≥ 8（1/3）→ 停止并报告**（截止期体系失效的批量证据；单例边界翻转不触发）。
- 通过则断点续跑剩余 168 次 → `build-analysis-input`（R1 计数由脚本从真实记录计算）。

## 五、边界与不可宣称事项

- A1 是**执行配置修正**（disabled→low 迁移的最小可行路径），绝对 Q/C/L 与 D2/Stage C 历史（disabled 模式）**不可直接比较**；六臂内部相对比较有效。
- 若预检/首批暴露上限或截止期不可行，正确结论是"冻结协议在当前模型服务上不可执行"，**不是**策略失败；不得借改截止期/上限"救活"批次。
- Mock 结果不作科学结果；R1 真实计数为唯一正式保护证据。
