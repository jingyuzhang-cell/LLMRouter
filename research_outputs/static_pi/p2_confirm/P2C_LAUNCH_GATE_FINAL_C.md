# P2-C 启动门禁最终报告（方案 C 落实版，2026-11-08，全程零模型调用）

## 结论

**所有技术门禁已通过，FREEZE_P2C.json 已生成。剩余阻断项只有一项：真实实验 GO 授权。**

按您的裁决完成的最终修复与验收如下。本轮未修改模型配置（max_tokens、路由均维持原样），未改动冻结的随机化表，未重复已通过的 2,849 个对抗测试与 619 个变体测试（本轮改动不触及评分逻辑；昆机 v1.3 只改谓词语义，其 g11 评分规格与 v1.2 逐字段一致，仅重跑了该合同的 A/B/C 小门禁，94 个对抗样本全部拒绝）。

## 一、三处 Gold 裁决落实

| 合同 | 落实 | 版本 |
|---|---|---|
| *ST广道 | F13 = 2025-06-13（v1.1 中已改正，本轮批准生效）| v1.1 |
| *ST昆机 | F16 = 2017-11-14（v1.2 中已改正，本轮批准生效）| v1.2→**v1.3** |
| *ST昆机 F20/F21 | 谓词改为"D1拟采取市场禁入措施"；证据仅 D1；dual_stage 标 `d2_final=UNKNOWN（D2未载禁入决定）`、`change=final_unknown`；market_bans 记 proposed / final=UNKNOWN；不加计分槽，N=20 不变 | **v1.3**（新发） |

昆机 v1.3 的值、关键槽、UNKNOWN、g11 逐字段与 v1.2 一致（脚本内断言核对），只改谓词与阶段标记；修订记录入 `P2C_GOLD_REVISIONS.jsonl`。
任务清单同步为 **`P2C_FINAL_GOLD_MANIFEST_V3.json`**（仅昆机行变更；26 家任务集合与 v2 完全相同——因此按预登记生成的随机化表仍然有效，未重抽，符合您的指令）。

## 二、G-9 方案 C 落实（运行器）

`p2c_runner.py` 由冻结的 P2-B 运行器（`p2_runner.py`，sha256 `ef2f3089…`，未改动）经 `make_p2c_runner_c.py` 的 30 处带断言替换生成。各臂内部逻辑不变，新增的只有故障分类与处置：

| 故障类别 | 处置 |
|---|---|
| 模型输出故障（truncated / abnormal_stop / empty / json_invalid / schema_invalid）| 抛 `ModelFault`，按臂处理，**不停批** |
| 恢复节点（J2R/恢复SINK）ModelFault | 记 `RECOVERY_FAILED_TRUNCATED::<详情>`；回退 G2 终端；回退输出正常评分但不记作恢复成功；调用/token/成本照实记账；不重试 |
| 共享上游（E/J1/J2）ModelFault | G2–G6 记 `EXECUTION_FAILED::shared_upstream`，Q=0；**G1 独立照常执行**；区组登记后继续下一区组；不重试、不删除 |
| G1/G2 自身 ModelFault | 该臂记 `EXECUTION_FAILED::<详情>`，Q=0，其余臂不受影响 |
| 传输错误 / 预算门禁触发 / 任何其他异常 | **整批停止**，现场保留（台账先写 sent 再调用，落盘不间断）|

区组结果 `P2C_RESULTS.json` 每臂记录 `execution_failed` 与 `status`（OK / OK_NO_TARGET / RECOVERY_FAILED_* / EXECUTION_FAILED_*），执行可靠性指标（截断率、回退率）可由台账直接统计。

## 三、三项截断测试 + 预算门禁测试（零调用，假传输）

| 测试 | 结果 |
|---|---|
| **T1 J2R 截断**（受控打桩使全部槽位成为 S2 目标，四个恢复臂都走 J2R 路径）| **通过**。52 区组全部完成（不停批）；G3–G6 状态均为 `RECOVERY_FAILED_TRUNCATED::J2R fault: truncated`；回退终端与 G2 终端逐字节一致；208 条 J2R 截断调用全部记账（fault=truncated、out=12000、费用入账）|
| **T2 共享 J2 截断** | **通过**。52 区组全部登记并继续；每区组 `shared_fault='J2 fault: truncated'`；G2–G6 全部 `execution_failed=true`、Q=0.0；G1 在 52 个区组全部正常执行 |
| **T3 传输故障** | **通过**。第 1 次调用即整批停止（`E_D1/ds transport: ...`），无后续区组，台账含 transport_error 记录 |
| **T4 预算调用上限**（上限设为 3）| **通过**。第 3 次调用后触发 `calls cap reached`，整批停止，无重试 |

## 四、预算门禁（发送前硬限制）

| 项 | 硬上限 | 依据 |
|---|---:|---|
| 调用 | **1,300** | 25×52（六臂上限 21 + 共享上游 4）；代码路径结构最大 728 |
| tokens | **15,000,000** | 最坏情形 14,957,371（各节点输入按 P2-B 实测最大×文书长度比 1.128，输出取满 max_tokens）|
| 核算金额 | **¥24.00** | 最坏 ¥23.20（边际仅 DeepSeek 部分，最坏 ¥12.76；GLM 订阅边际 ¥0）|
| 预期 | — | 按实测外推：约 604 万 tokens、核算 ¥10.02、边际 ¥3.93 |

每次调用前 `Budget.preflight` 检查三项上限，超限即停；失败尝试计入计数，无重试。

## 五、最终 SHA256 清单

| 文件 | sha256 |
|---|---|
| **FREEZE_P2C.json**（最终冻结件）| `77ea17d5d50fec9a6dd62f041549ac72716a803c2d73028a1df70327b4f257cd` |
| P2C_FINAL_GOLD_MANIFEST_V3.json | `27ed4d14cdc847afeb9a7197503d66ed994bfff42abc832564bdb21b3f0d7e3a` |
| p2c_runner.py | `7396f432007f768bf4705ef0959c868e1f193c49a70682683f3b9fb061742d66` |
| make_p2c_runner_c.py | `e770ee16b6185858fb2c943338aaab6aeeff5ba7fca4bb03b7977f214eeee3b0` |
| p2c_runner_tests.py | `a79e271abd929338ad48f7ea018e36ca3f65c82be6e10f1e1049b9859add7143` |
| p2c_scorer.py | `3e18e87632436ae06cbd5be9b47858ca7a80a388705b49cf64accb2eed7854e1` |
| p2c_gate_check.py | `82b91e5d528cf77b582003fdd76d02e47dac8d24412d6d074edcf5264dad4d55` |
| p2c_g11_build.py | `4c1f08cc457d5b8790283ce2f43bc997b7325dd4a9dc44b3ae728a8a00013a79` |
| P2C_RANDOMIZATION_PREREG.json | `5805c42cd8da0a11cf9281cedd1c3a6879dfc0e1c4cfbcc96c2af7693ea92814` |
| P2C_RANDOMIZATION_TABLE.json（52区组，种子 2756364533）| `5166565169f31325f011c1d293aa75da7e204173cf4a1713ca3d132fd5d29688` |
| p2c_randomize.py | `340e2298e427b4ac4143b038101932dd22f24419707f8aac7698065f79001e44` |
| TASK_CONTRACT_KJ_600806_v1.3.json | `547e103d285b9919d2dd671d0d9747670d4b3ff56a741ceacb6e027c219eb718` |
| P2C_GOLD_REVISIONS.jsonl | `34c77fefa52bc181f42555d1e5fff347533e53849423f880aabd414a81b67600` |
| P2_STATISTICAL_POWER_V2.1.md | `a385f0f3378a249ad8ab845c65a17509d277e6e531f340d71b54d559668e9024` |
| p2_runner.py（P2-B 冻结，未改）| `ef2f3089d1600cfe46cdaadd96a1d706bcc179b4bf4536cab652e4b9ce512965` |
| qs_scorer.py（冻结，未改）| `332ce5763de318dac05941352e69e31f3db098dfb49cda33bdde8fc742e91164` |

完整性核对：FREEZE_P2C.json 覆盖 30 个文件（运行器+生成器无关项+清单+随机化表+评分器+26份合同），逐文件 sha256 一致；manifest v1/v2/v3 所列全部合同文件均未被改动；随机化表与其预登记一致；昆机 v1.2、v1.1、v1 原件均在。

## 六、实验解释边界（按裁决写入论文口径）

- P2-C 确认性结论解释为：**在当前模型配置、执行可靠性（含 50% 历史截断率量级）及预设回退机制下，动态协同调度的实际综合效果**，不是纯理论恢复收益。
- 功效区间 0.55–0.80 为条件功效，不构成考虑截断后的执行功效保证；截断率、恢复成功率、回退率作为执行可靠性指标单独报告。
- P2-B 重评分仅作敏感性分析，不并入确认样本。

## 七、剩余阻断项

**仅剩：P2C_GO=1 的授权决定（由您单独作出）。**

启动命令（供您授权后使用，本轮未执行）：
```
P2C_GO=1 python3 p2c_runner.py --real --freeze 77ea17d5d50fec9a6dd62f041549ac72716a803c2d73028a1df70327b4f257cd
```
（另需已配置的 `DEEPSEEK_API_KEY` 与 `STAGE_D_GLM_KEY` 环境变量；运行器会校验冻结哈希后才发起任何调用。）
