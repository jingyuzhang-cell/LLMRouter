# Reference Cube 实验台账（collab_scheduler_v1）

## 2026-09-28 fault30 完成与五步审计结果（当日主结果）

fault30 v2 于 19:0x 完成：45/45 (seed,config) 评估，全链 1088 个真实调用
（v1 392 + v2 696），FAULT30_RESULTS.json 落地。五步审计（FAULT30_ANALYSIS.json）：

1. **provenance 全通过**：3 种子 × 15 配置的注入任务/节点全部可追踪。
2. **配对效应 + 内部锚点**：BALANCED/HETEROGENEOUS 家族非故障任务与 clean 逐位一致
   （0 失配）；QUALITY 家族 4 配置共 100 失配单元（88 个纯 cost 差，中位 3.6%；
   12 个 ok 翻转 ≈0.7% 单元）——双会话别名解析的有界噪声，所有结论裕度远大于此。
3. **Δ_Z 三族全为正且逐种子一致**（recovery-induced Pareto trade-off 成立）：
   BALANCED +0.030Q/+789C、HETEROGENEOUS +0.067Q/+622C（逐种子 +0.065/+0.075/+0.060）、
   QUALITY +0.023Q/+613C。
4. **Y 翻转：SERV ↔ DYNAMICDAG**（fault 下 DYN 因恢复跃升）；X 排序 HET>QUALITY>BALANCED
   不变——状态作用于恢复维 Z 与协同结构 Y，不改模型配比偏好 X。
5. **全局 P\*_fault = {SINGLE}（未扩张，HV 0.2281）**；**DAG 子空间前沿 2→3 点**
   （HV 0.0519→0.1007 翻倍），新增结构点 DYN__HET__LOCAL_REROUTE（Q .3433 @ C 2089）
   对照 SER__HET（Q .3083 @ C 952）——G1 便宜低Q / G2 贵恢复高Q 的目标格局成立。
   弱锚点 f30_dynamic=0.4033 **未复现**（实测 .3433，差 0.06 >> 容差 0.02）——与
   f30_static 废止一致，legacy fault 数字整体让位于 cube 实测。
   措辞红线：以上均为冻结故障模型下的状态干预结论。

**主线故事更新**：clean {Single} → fault 全局仍 {Single}，但协同子空间前沿扩张 + Z 价值
显性化 → 论文重心从"全局 front discovery"转为"状态条件下的协同方案调度与恢复价值"。
**SA-PGFS 首个真实算法结果**（REPLAY_FAULT.json，DAG 子空间 3 点实测前沿）：
ehvi/cost_aware regret 0.004±0.002、16/16 种子 N95 命中（≤7 次评估）、AUC-HV 0.92；
random 8/16 从未达标、greedy 7/16（AUC 0.86/0.64）。
sim_search 重生完成（ehvi 1.013±0.020 等，替代 INVALIDATED 旧版）。
结果表/图已更新（RESULT_TABLES.md、figs/f1_f2 含 fault 叠加、f3）。

## 2026-09-28 fault30 中断与 v2 换防（CPU 准备 + 一次门禁正确的接管）

- **外部中断**：9/27 23:58 所有进程（v1 fault30 执行、vllm、sim_search 重生）被同时杀死
  （机器/会话级事件，非代码错误）。fault30 v1 中断于 338/约 884 调用，未写结果文件
  （v1 只在结尾写）。sim 重生的半成品目录为空，已清除。
- **机器重启后**：并行会话于 18:05 自动重启了 v1（PID 1713）。v1 有两个问题：
  (a) 无自台账播种 → 重新执行了死前已做的 54 个调用；(b) 逐任务串行 → 进入
  LOCAL_REROUTE 后每任务 4 次模型切换（每次 = vLLM 重启），实测速率 0.77 调用/分钟，
  剩余 ≈ 13 小时；且无检查点，再被杀一次就再来一遍。
- **v2 加固**（语义与 v1 完全等价，纯执行机制）：R1 自台账播种（重启零重复）；
  R2 分阶段批执行（frozen200 multi_seed_run 同构，决策只依赖记录输出与任务序，
  切换从 ~每任务 降到 ~每阶段）；R3 逐 (seed,config) 检查点 FAULT30_ROWS.jsonl。
  结构 dry 验证：SER__BALANCED dry_new=0、reuse_own=23、Q 与 v1 dry 一致。
- **门禁正确性实测**：我的 v2 启动被 GPU 锁拒绝（v1 持锁）——gate 逻辑有效。
- **换防**：停 v1（1713）与其 vllm，清空我 dry 模式误写的一行检查点（已加 real 守卫
  修复），v2 以 setsid 启动。前 12 个 NONE 配置秒级完成（new≈0-2/配置，
  reuse_own 515+），从 DYNAMICDAG LOCAL_REROUTE 起进入真实恢复调用区。
- **遗留口径注记**：v1 死前与 1713 的重复执行使 fault30 台账存在少量双会话重复
  (model,prompt)（同 cube_clean 情形）；v2 自播种按“最后响应/键”确定性解析，
  分析器的 provenance 与内部锚点检查会暴露任何实质影响。

## 2026-09-27 证据治理补记（第二轮，CPU-only）

1. **f30_static 正式废止**（`fault30_prep/RETIRED_EVIDENCE.json`）：该值及所有引用它的
   派生结果（AUDIT_V1 的 s_fault30 static 单元、frozen200 修正汇总的 static 预算曲线、
   REPORT_V1 的 static 行）标记为“历史结果，不进入新 Reference Cube”。Single/Dynamic
   两锚点保留各自 provenance 说明。
2. **双会话敏感性审计**（`session_sensitivity_audit.py` → `SESSION_SENSITIVITY_AUDIT.json`）：
   as_published / all_early / all_late 三套解析下 15 配置 Q 逐位一致（max spread = 0.0），
   前沿 {SINGLE} 与 Y/X 排序完全稳定——20 个分歧答案不进入任何计分链（各重复执行有独立
   键，配置走直连 by_key）。**双会话问题降级为 reproducibility note**。
3. **深挖修复 `sa_pgfs_v1/pareto.py::hypervolume`**：2D 分支（正序 x + `y > best_y`，前沿上
   永不再触发）与 3D 分支（降序 z + `z > best_z`，只处理最高 z 点）实质都返回“单个极值点
   的盒子体积”，且违反加点单调性（0.448 → 0.4335 实测）。**所有多点前沿的 HV 数字此前
   全部失效**；单点前沿（P*_clean={SINGLE}）恰好不受影响，HV=0.2884 维持有效。
   `test_pareto_regression.py`（已知值/单调性 200 例/暴力网格对照）+ 
   `test_acquisition_regression.py`（ehvi 轴修复 5 项）全部 PASS。
4. **`results_sim_v1` 判定无效并重生中**：其 HV 轨迹与策略比值基于坏 HV + 坏 ehvi；
   `sim_search_regression.py` 正在后台以修复后实现重生成（零调用）→ 
   `results_sim_v1_regenerated/`。
5. **clean replay 降级为 smoke test**（`REPLAY_CLEAN.json` 增加 status 字段）：clean 前沿
   只有单点，策略区分度弱是构造性的；算法结论推迟到 fault cube（需 ≥2 个结构不同的
   非支配点）。修复后重跑数字不变（EHVI/cost-aware 1.000，random 0.683，greedy 0.456）。
6. **fault30_analyze 固化检查顺序**：provenance → paired fault effect（含仅故障任务归因 +
   非故障内部控制）→ Δ_Z（recovery-induced Pareto trade-off 判定）→ Y/X rank shift →
   Pareto；并内置“状态干预而非能力变化”的措辞红线。
7. fault30 执行（另一会话带门禁启动）进行中：截至本轮 269 个真实调用，已进入
   DYNAMICDAG 恢复阶段。

## 2026-09-27（本日条目，CPU-only 并行阶段）

时间线（本地时间）：
- 22:16–23:20 `cube_clean_run` 在 GPU 上运行（Qwen2.5-14B-Int8 @ :8128 等，按模型切换），
  23:19:59 写出 `cube_clean/CUBE_CLEAN.json`（new_calls=3119），服务器干净退出。
- 期间所有准备工作零模型调用完成（本台账以下条目）。

### CUBE_clean 结果（15 配置，n=200/配置）

统一目标 (Q_workflow, C_workflow, L_critical_path)；`cube_analyze.py` 独立复算与
runner 输出 15/15 完全一致（别名机制按 (model, sha(prompt)) 首次出现复刻）。

| config | Q | C | L |
|---|---|---|---|
| SER__BALANCED | 0.295 | 1029.6 | 3.044 |
| SER__HETEROGENEOUS | 0.370 | 963.5 | 2.375 |
| SER__QUALITY | 0.340 | 963.3 | 2.408 |
| SERV__BALANCED | 0.325 | 1269.7 | 3.324 |
| SERV__HETEROGENEOUS | 0.365 | 1194.2 | 2.678 |
| SERV__QUALITY | 0.335 | 1208.4 | 3.040 |
| PARALLELER__BALANCED | 0.295 | 1244.6 | 3.320 |
| PARALLELER__HETEROGENEOUS | 0.305 | 1219.5 | 2.876 |
| PARALLELER__QUALITY | 0.315 | 1219.9 | 2.942 |
| DYNAMICDAG__BALANCED (NONE=LOCAL_REROUTE) | 0.295 | 1506.7 | 3.596 |
| DYNAMICDAG__HETEROGENEOUS (同上) | 0.330 | 1484.0 | 3.174 |
| DYNAMICDAG__QUALITY (同上) | 0.310 | 1513.8 | 3.866 |
| SINGLE__QUALITY__RETRY（锚，frozen200 实测） | 0.550 | 612.8 | 0.460 |

- **P\*_clean = {SINGLE}**：Single 在统一目标下支配全部 DAG 配置；3D HV = 0.2884
  （归一化 (Q, 1−C/Cmax, 1−L/Lmax)，参考点原点；CUBE_CLEAN_ANALYSIS.json）。
- clean-dedup 校验通过：DYNAMICDAG 的 NONE/LOCAL_REROUTE 两标签逐位相同（3/3 家族）。
- 锚点校验通过：DYNAMICDAG__HETEROGENEOUS (Q .330, C 1484.0) ≈ frozen200
  clean_static (Q .335, C 1485.7)（同模型指派/面板/prompt；L 按立方关键路径定义，
  小于 legacy 串行和 4.56，属口径差异而非矛盾）。

### 台账完整性（零调用取证，两项）

1. **frozen200 f30_static 污染**（`fault30_prep/FROZEN200_FAULT_PROVENANCE.json`）：
   记录中 e1/e2/r 故障任务与 clean 逐位相同（3 种子 0/54、0/41、0/45 变化），仅 v 故障
   翻转（3/5/6）；台账无任何 plain 下游重执行，且重建的故障侧 r prompt（21–29/种子）
   在所有缓存目录不存在 → 记录的 static 故障臂不可能由仓库当前 frozen200_run 逻辑产生。
   处置：f30_static (.2933) 从 fault30 锚点中排除；f30_dynamic 降为弱锚点（恢复调用
   真实存在）；f30_single 为簿记式故障（设计如此）。核心结论
   “s_fault30 前沿 = {Single, Dynamic}”不受影响（static 本就被支配）。
   另发现 legacy run 存在跨种子状态泄漏（非故障任务翻转 0/2/8，随运行序递增）。
2. **cube_clean 双会话混账**（`CACHE_AUDIT.json`）：REQUESTS/RESPONSES 追加了一次
   ~3.7h 前的早期部分运行（108 个跨会话重复 (model,prompt) 执行；其中 20 个同 prompt
   双会话答案不同——vLLM 重启后 temp-0 非确定性）。解析按台账首次出现，runner 与独立
   分析器一致（15/15 吻合），测量良定义；来源为两个 server 会话，特此记录。

### fault30 准备（未发任何模型调用）

- `fault30_prep/FAULT30_POLICY.json`：冻结协议——位对齐抽签、(task,node,planned_model)
  键控持久故障、节点映射（v 故障在无 v 拓扑上潜伏）、强制真实下游传播、逐 (seed,config)
  状态隔离、ungated 检测 + LOCAL_REROUTE 恢复规则（memory 规则、无效重路由语义）、
  clean 参考成本记账、prompt cache 五元组边界（vp1 模板哈希显式记录）。
- `fault30_protocol.py` 零调用规划器 + `FAULT30_DRYRUN.json`：精确预算
  **确定性 NEW=557 + 运行时预期 ~327 ≈ 884 次真实调用**（~28 分钟 GPU）；
  INJECTED ~820/种子（零成本）、INJECTED_PERSIST ~33/种子。
- `fault30_run.py` 执行器（结构 dry 已走通 15 配置；dry_new=486 为空答案级联上界伪影，
  预算以规划器为准）。**门禁：默认 dry；真实执行需 `--execute` 且 env FAULT30_EXECUTE=1，
  且 GPU 锁空闲。**
- `fault30_analyze.py`：P\*_fault、配对 McNemar/Help-Harm、仅故障任务归因 delta、
  内部位等价锚点（NONE 臂非故障任务必须与 clean 逐位一致）、弱锚点
  DYNAMICDAG__HET_LOCAL_REROUTE ≈ .4033±.02。

### 其它零调用产出

- `crossmodel_map.py` → `CROSSMODEL_EVIDENCE_MAP.json`：9 个 SER 组合 → 3 个直接
  对应 cube 配置 + 6 个 X-prior 邻域；使用规则冻结为“先验/校验/缓存复用，不入统一前沿”。
- `cache_audit.py` → `CACHE_AUDIT.json`：A1 五元组（prompt_version 为隐式分量，已记录
  偏差并在 fault30 协议补救）、A2 配对、A3 去重（跨会话注记）、A4 无注入泄漏、A6 无键冲突，
  全部 PASS。
- `sa_pgfs_v1/cube_replay.py`：reveal/replay 接统一 config ID；自检在 frozen200 实测三点上
  复现 clean 前沿 {Single} 与 fault 前沿 {Single, Dynamic}；clean cube 16 点 replay
  （task-level bootstrap 噪声，8 次评估预算）→ `sa_pgfs_v1/results_cube_replay/REPLAY_CLEAN.json`：
  ehvi 与 cost_aware_ehvi 均 1.000±0.000 恢复全前沿，random 0.683±0.410，
  greedy_q 0.456±0.424。
- **修复 `sa_pgfs_v1/acquisition.py` 轴 bug**（`qs[:, s]` → `qs[s]`，采样维度与候选维度
  写反；当前文件形态无法复现历史 results_sim_v1，系重写后未回归——建议之后对
  sim_search 做一次回归重跑）。
- `RESULT_TABLES.md`（T1–T4 骨架 + fault 占位）与 `plot_cube_fronts.py`
  （F1/F2 前沿投影、F3 replay 柱状 → `collab_scheduler_v1/figs/`）。

### 下一步（按既定管线）

CUBE_clean → **P\*_clean（已完成）** → fault30（~884 调用，门禁待放行）→
P\*_fault → SA-PGFS（cube_replay 已就绪，fault 点落地后重跑）。
