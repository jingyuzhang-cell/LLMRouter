# Stage-C-R1 启动前最终冻结摘要（PREADMISSION）

**日期**: 2026-10-30
**依据**: 操作员最终授权前指令（七项闭环，一次零调用冻结，不另开研发阶段）
**结论**: 七项门禁 **ALL PASS**（`stage_c_r1_runs/STAGE_C_R1_FINAL_FREEZE.json`）。**未发送任何模型请求；等待用户对 `stage_c_r1_v1` 的单独授权。**

本轮为闭环三项必须事项所做的**最小工程改动**（无算法变更，验收测试 8/8 无回归）：
① 故障注入从适配器移入执行器 `inject_result()`——真实 Meter 路径与确定性路径现在拥有**完全相同**的故障语义（此前注入只在模拟器里，是"生产路径真正接入"的实际缺口）；② MeterAdapter purpose 构造修复（`run_id:node:version`，按 kind 输出上限 768/1024）；③ 分裂节点共享端口的评分覆盖修复（逐节点值拼接，双核验分支都进入评分输入）；④ 共享前缀 fork 设计——跨臂相同初始故障的最强保证。

---

## 七项门禁逐项结论

**1. 48-run 矩阵与执行指纹 — PASS**。2 任务（SC-E1/SC-E3）× 2 场景（S1 transport 瞬断@timeline、S2 contract 持续@verification）× 6 臂 × 2 重复 = 48 runs，逐 run 冻结任务/故障/臂/重复/π₀/K_m=2,2/deadline=1800s 与确定性决策指纹（全部 48 条在 FREEZE JSON `matrix.runs`）。指纹汇总：S1 下五自适应臂 COMPLETE、Static INCOMPLETE_NO_RECOVERY；S2 下**仅 Joint(Z,R,π) COMPLETE**（SPLIT_VERIFY:e1_chk / e3_chk），其余全部 INCOMPLETE_RECOVERY_EXHAUSTED。共享前缀内故障恰好触发一次（8/8 cell）。

**2. 真实调用入口接线 — PASS**。Meter 路径与确定性路径共用同一执行器/决策器/内核/注入；适配器仅替换模型传输层。静态检查：新 Runner 无 stage_c_v2 代码依赖（评分函数为逐字复制，出处注明）、`ARM_DECIDERS[arm]` 为唯一决策入口、适配器仅经 Kernel 调用。动态负面测试：`--adapter meter --authorize` 无七字段记录时 auth gate 拒绝启动（rc=1，零调用）。

**3. SC-E3 持续 contract 下 SPLIT_VERIFY 闭环 — PASS**。合法性依据：e3_chk 为 verification 合同、双亲 e3_param_check(reasoning)+e3_timeline(timeline) 异类且健康（负例：e1_fin 双亲同为 extracts → 非法）。重构语义：e3_chk 移除，e3_chk_a/_b 各验证一条血统，report 重接为双必经父——原合同失败未被隐藏（两分支都必须成功，report 才执行；任一失败即阻塞）。评分覆盖：双分支输出经端口安全拼接进入评分输入。新增成本全额计账：JointZ 12,080 > JointRP 11,498 tokens（同一 cell）。

**4. 预算与分模型配额 — PASS**。共享前缀设计下确定性扫描实测 **144 次调用**、按实测字符/Token 比 0.6295 + 输出上限估算 **227,245 Token**（×1.3 余量 = 295K）——远低于 550 次 / 600K 硬顶。分模型实测：glm53 124 次 / 193.5K；flash 20 次 / 33.7K。**建议配额**：glm53 ≤ 160 次 / 266K；glm53flash ≤ 30 次 / 50K（各 +25-35% 余量）。未以截断证据换预算：DOC_CAP=500/父上限 2,000 沿用 v2 冻结值。

**5. 计费与现金 — PASS**。模型池 = {glm53, glm53flash}（订阅，¥0 边际），现金硬顶 ¥0。注入失败保留真实 usage/latency（失败与重试全部计费）；扫描中 76 次失败调用全部入账。

**6. 配对公平性 — PASS**。每 cell 六臂从**同一**共享前缀 fork（初始故障态逐字节相同，断言通过）；健康前缀节点在任何臂中零重执行（健康缓存合法性）；重复间使用独立前缀实例（真实路径下 r1/r2 前缀 purpose 不同 → 独立采样）。

**7. SHA256 冻结 — PASS**。runner `stage_c_r1.py`、决策器 `six_arm_scheduler.py`、验收测试、tasks.json（含 DAG）、event_dags、4 份 silver、9 份证据文本、manifest、评分器源摘录、冻结配置（π₀/K_m/衰减/系统失效集/PROFILE_Q/故障规则/矩阵维度）全部入冻（完整值见 FREEZE JSON `shas`）。

## 七字段授权配置（待您授权）

```json
{"batch_name": "stage_c_r1_v1", "max_calls": 550, "max_tokens": 600000,
 "max_cash": 0, "allowed_models": ["glm53", "glm53flash"],
 "tasks": ["SC-E1","SC-E3"] × S1_transport/S2_contract × 6臂 × 2重复（48 runs）,
 "issued_by": "PENDING",
 "per_model_quota": {"glm53": {"calls": 160, "tokens": 266000},
                     "glm53flash": {"calls": 30, "tokens": 50000}}}
```

## 研究边界（重申）
48 runs 的真实事件数仍为 2；S1 回答"Joint(R,π) 是否优于有恢复能力的强基线"，S2 提供机制假设"合法结构调整能否在 Q/C/L 权衡下带来额外收益"——后者能否测出取决于真实模型条件下 SC-E3 证据对 SPLIT 分支的支持与评分覆盖，均为待验证项而非既定结论。确定性适配器的质量分层不构成真实 Q 的证据。

**全部完成，停止。等待用户对 stage_c_r1_v1 的单独授权；论文暂停。**
