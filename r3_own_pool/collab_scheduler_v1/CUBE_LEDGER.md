# Reference Cube 实验台账（collab_scheduler_v1）

## 2026-10-08 P1 统计验证 + 文档同步（复核后收尾，零调用）

- **恢复效应任务聚类 bootstrap**（DELTA_Z_BOOTSTRAP.json，任务重采样、种子在任务内
  平均以保留依赖）：HETEROGENEOUS ΔQ +6.67pp **CI[+2.5,+10.8] p=0.0016 显著**；
  QUALITY +2.33pp CI[+1.2,+3.7] p=0.0002 显著；**BALANCED +3.17pp CI[−0.2,+6.7]
  p=0.072 不显著（跨零，如实报告）**；三族 ΔC 均紧致为正（+613~+770 tokens）。
- 草稿同步 V2_1 AUC（EHVI 0.865 / qNEHVI 0.866 / scalarized 0.852 / qnparego 0.848，
  预算 2–8）；"有代理 vs 无代理"分组措辞更正（Greedy ≥4 观测后也用 GP，不作严格
  分组结论）；Scalarized 命名更正为固定权重线性标量化（实现为 arc @ w，非 Chebyshev）。



## 2026-10-08 残留协议问题修复（v2_1，审计复核后第二轮，零调用）

- **B1 重做为真"同样本状态特征"对照**（旧版实为分状态训练 vs 混合训练，数据组织不同）：
  联合 GP 同样本，输入 X vs [X, state]。结果：aware gap +0.0018 vs blind +0.0040，
  **gap p=10⁻⁴ 显著；AUC p=0.213 检不出差异**——准确表述："状态信息改善最终前沿
  恢复；全程搜索效率优势未检出（no statistically significant difference）"。
- **AUC/N95 计入初始设计**（预算 2–8）：REPLAY_V2_1.json gap 逐位不变（修复仅影响
  记账），AUC 整体下移、排序与全部结论不变。消融曲线与 v2 主表因 GP 启用时机不同
  （B 自 2 点拟合、v2 自 4 点）不可横向数值比较——已注明。
- 版本化：MECHANISM_ABLATIONS_V2_1.json / REPLAY_V2_1.json，旧件保留未覆盖。



## 2026-10-08 工作包 B 机制消融（修正协议，200 配对种子，零调用；MECHANISM_ABLATIONS.json；取代 6e9702e 旧消融）

- **B1 状态感知 vs 状态盲**（同跨状态观测流、同数据量、仅状态信息不同）：
  aware gap +0.0019 vs blind +0.0040，**Holm 显著**（gap/AUC 均 p=0.0007）——
  状态信息在公平设计下有可测搜索收益（效应量小，限两状态离线设定）。
- **B2 表示**（同 GP+EHVI）：integer 优于 onehot（Holm p=0.0007）；
  **structural 对 onehot 在 Holm 后不显著（p=0.118/0.129），且未超简单整数编码**
  ——图结构特征的独立贡献在此空间未获支持，如实降级该主张。
- **B3 代理必要性**（同 EHVI）：GP 优于常数预测器（gap Holm p=0.0007；AUC 检不出
  差异，p=0.206）；采集必要性已由 v2 覆盖（scalarized≈EHVI on gap）。
- 措辞规则：n.s. 一律写 "no statistically significant difference was detected"，
  不写 equivalence。
- 定位含义：SA-PGFS 框架中**状态条件化是当前证据最好的机制**；图结构表示主张降级。



## 2026-10-08 外部审计（裁定 D）响应

- **接受裁定 D**：定位收缩为"协同配置权衡 + 恢复价值的实证研究"；SA-PGFS 不作
  "已验证新算法"主张（最终搜索无状态输入/图特征/DualArchive/Outer 闭环）。
- **已核实的实现/解释问题与修复**（零调用）：qNParEGO 权重约掉、NSGA-II 拥挤度
  反向、recall 索引错位、MCTS 缺 DYN NONE 叶 → replay_v2.py 修复；跨状态"HV 翻倍"
  撤回（共尺度 0.119→0.101，只保留前沿成员 2→3）；"Y 翻转"改为恢复驱动的 DYN
  相对价值变化（Z 受控无翻转，已入 FAULT30_ANALYSIS）；BALANCED Δ_Z 更正
  +3.17pp/+770.1 tok。
- **REPLAY_V2.json（200 配对种子，真值评价，故障种子相关噪声，(count+1)/(B+1)+Holm）**：
  唯一稳健分界 = 有代理 vs 无代理（GP 系五法 gap 不可区分：qNEHVI/cost-aware/EHVI/
  qNParEGO/scalarized = +0.0024~+0.0048；MCTS/NSGA-II/greedy/random = +0.031~+0.093，
  Holm P≤0.004；AUC 微弱利于 EHVI 系）。v1 表全部胜负主张作废。
- 统计口径修正：p=(count+1)/(B+1)、AUC 自初始设计计、N95 含初始点、"bit-for-bit"
  降级为"汇总一致"；协议补记：实际为整数编码特征（非 one-hot）。
- 遗留（预注册）：state-aware/blind、图表示、surrogate 必要性三项机制验证（工作包 B）
  与共尺度统计细节（任务聚类推断）为后续项，未启动。



## 2026-09-28 实验链正式收口（最终状态）

- **不再新增实验**。主张层级锁定为 qNEHVI ≈ SA-PGFS > {其余}；统计表述统一
  p < 10⁻⁴ 与 signed normalized HV gap（不写 p=0.000 / regret）；三句主结论锁定
  （见 ALGORITHM_TABLE.md）。
- qNEHVI 区分措辞：框架统一性（G(s)/恢复动作/档案相对状态定义），不写"qNEHVI
  不能处理状态"，不声称跨状态迁移（replay 为逐状态独立）。
- **P2 scale-up（small→medium→large 复杂度边界）记为审稿人应对预案**，未启动：
  若被要求，须先做零调用 cache coverage audit、preregister 空间/预算/基线/指标，
  成败条件（medium/large 上 AUC 与 N95 的配对显著优于 scalarized）与停止条件
  （若仍输则降级 SA-PGFS 定位）已在此预定。559-config 模拟仅作 algorithm-
  development sanity check，不承担"真实大空间胜出"结论。
- 下一步：写 Results（冻结数据已定），再反推 Method。



## 2026-09-28 外部基线横向对比（冻结 cube 上零调用，投稿前补齐）

四个外部搜索机制在**同一冻结 harness**（200 配对种子、同初始设计、同噪声抽样、
预算 8、双 recall、置换检验）下与 SA-PGFS 对比（ALGORITHM_TABLE.md /
FINAL_ALGORITHM_TABLE.json；机制为诚实适配，非原系统复现）：

| Method | HV gap | AUC-HV | N95 达标 | Recall(dedup) |
|---|---|---|---|---|
| Random | +0.085 | 0.842 | 91/200 | 0.133 |
| Greedy-Q | +0.070 | 0.840 | 107/200 | 0.233 |
| NSGA-II | +0.081 | 0.828 | 109/200 | 0.158 |
| qNParEGO | +0.058 | 0.857 | 117/200 | 0.217 |
| **qNEHVI** | **−0.006** | **0.922** | **165/200** | 0.177 |
| AFlow-style MCTS | +0.014 | 0.881 | 140/200 | 0.218 |
| **SA-PGFS (EHVI / cost-aware)** | **−0.006** | **0.922** | 160/162/200 | 0.173/0.158 |

配对置换检验：SA-PGFS 对 NSGA-II/qNParEGO/AFlow-MCTS/random/greedy 全部 **p=0.000**；
**对 qNEHVI 不可区分**（regret p=0.885/0.979，AUC p=0.457/0.581）——noisy-EHVI 家族
是本问题上的第一梯队。论文表述：SA-PGFS 与最强 noisy-MOBO 基线持平、显著优于其余，
其差异化在于状态条件搜索能力（跨 s 的 G(s)/P*(s)）而非单状态有限表上的采集函数本身。
SA-PGFS 200 种子重跑与冻结汇总逐位一致（冻结可复现性 PASS）。


## 2026-09-28 冻结与 200 种子 robustness（当日收尾）

- **f30_dynamic = 0.4033 正式退役**（重测 0.3433±0.0047，差 0.060 >> 容差）；
  "fault 使 Dynamic 进入全局前沿"主张永久撤回：修正后 P*_clean = P*_fault = {Single}。
- **REFERENCE_CUBE_FREEZE.json / PROTOCOL_SAPGFS_FREEZE.json 落盘**（关键工件 sha256
  全记录；freeze 后规则：不再对本 cube 发真实调用，扩展需新版本目录）。
- **200 种子配对 robustness**（REPLAY_FAULT_ROBUST.json，冻结协议、同初始设计、
  逐种子实测噪声、双 recall、置换检验）：ehvi/cost_aware regret −0.006、AUC 0.922、
  N95 达标 160+/200；random regret 0.085、达标 91/200；六项置换检验全部 p=0.000。
- SA-PGFS 修复与冻结已提交 git；collab 侧由并行会话提交（d7a2896）。
- 方法结构定稿：Outer Scheduler (s→{Single, Collab, Reuse}) + Inner Optimizer
  (SA-PGFS over G_collab)；全局与协同结果永久分表。


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
