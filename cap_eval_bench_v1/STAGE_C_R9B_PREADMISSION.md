# Stage-C-R9B 准入报告：增量输出合同修复验收与新批次最终配置

**日期**: 2026-10-30 | **依据**: 操作员方案 A 裁决（delta 合同 GO；文本路径测试 GO；旧 26 次失效不复用；新批次全额预算；真实调用 HOLD）
**交付**: 修复后的生产链（[stage_c_r9_chain.py](integration/stage_c_r9_chain.py)，sha `c74c9cb9…`）、8/8 文本路径测试（[R9B_ALL_TESTS.json](stage_c_r9_verify/R9B_ALL_TESTS.json)）、新批次配置（[stage_c_r9b_auth_recommendation.json](stage_c_r9b_auth_recommendation.json)）。零模型调用。

---

## 一、原则已固化（按您的表述）

**模型只负责产生新的事实和推理结果；执行器负责维护事实账本及其血统。** 实现为增量输出合同：模型输出仅含 `new_facts` / `comparisons` / `dropped` / `status_changes`，提示词明文"不需要也不得回显任何继承事实"；执行器自动继承可见事实（保留原 fid、doc_id、span、版本与状态），合并增量并做合法性检查。

## 二、8/8 文本路径测试全部 PASS（经真实序列化→解析）

| # | 测试 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | 大账本不要求回显；空 delta 合法成功 | PASS | 120 条继承事实全保留，输出 <100 字符 |
| 2 | 多父节点事实正确合并 | PASS | 终端共存 cs_plan + cs_listing 双来源 |
| 3 | 新增不覆盖继承（内容+**来源**去重） | PASS | 原 fid 保留、无重复行 |
| 4 | 删除必须带合法原因 | PASS | 无原因→拒删留痕 rejected_ops；有原因→接受 |
| 5 | 截断/缺字段/非法状态变更全部拒收 | PASS | JSON 截断、max_tokens（计费保留）、非法状态三例 |
| 6 | E1 350天经**增量文本路径**进入终端 | PASS | `350天(2019年7月9日→2020年6月23日, zzd_notice_2019×zzd_penalty_2020)` |
| 7 | E3 双比率+双侧来源完整保留并完成不一致比较 | PASS | 四条比率各带正确 doc；比较引用双侧 |
| 8 | 缺任一侧操作数仍拒绝确定比较 | PASS | `insufficient_evidence`，conclusion=null |

**修复过程中发现并修正的两个真实缺陷**（如实）：内容级去重曾把"同值不同源"折叠为单侧（双侧证据被压扁——去重键已改为 内容+来源）；测试装置的节点 kind 推断缺陷（`e1_tl` 不含 "timeline" 字符串——改用任务 DAG 真实映射）。评分器、六臂算法、DAG、Silver、历史零改动；确定性链回归 PASS。

## 三、新批次最终配置（stage_c_r9b_v1，待授权）

| 项 | 值 |
|---|---|
| 矩阵 | SC-E1 + SC-E3 × S2_contract@verification × {A_plain, B_split} × 2 重复 = **8 runs** |
| 调用硬顶 | **80**（预计 52–64；delta 提示词大幅缩短） |
| Token 硬顶 | **150,000**（预计 60–90K） |
| 分模型 | glm53 ≤65 次/120K；glm53flash ≤20 次/30K |
| 现金 | ¥0 |
| 旧批次 | 26 次/43.9K 保留为失效记录（回显合同缺陷），**不复用响应** |
| 判读 | 三分离：报告生成率 / 报告存在条件下的事实质量 / 下游事实增量；同 fork 配对，Z 唯一差异，分歧标 NON_ISOLATED |

**启动先决条件全部满足**：delta 链 SHA `c74c9cb9…` 已冻结、8/8 文本路径验收、驱动器复用（purpose 前缀改 R9B-*）。按您的裁决：**真实模型调用 HOLD 维持，等待您的单独授权语句；不再增加任何研发任务；论文暂停。**

---

## 四、发射就绪补记（ZCode 会话，2026-10- 30 12:5x；零调用）

> ## ⛔ HOLD：未获操作员明示授权语句前，任何代理不得启动本批次 ⛔
> 操作员裁决原文（12:45）："真实调用继续 HOLD"。AUTHORIZATIONS.json 中已存在
> stage_c_r9b_v1 记录（并行代理于 12:4x 以"两钥匙"解读预转录，其 12:40 的
> 推荐文件自述"PENDING (operator HOLD; separate authorization required)"），
> 该记录合法性**存疑待裁**；12:44 曾有一次发射尝试，被冻结 SHA 门拦截，零花费。

**发射路径 reconcile 完成（仅 exec，准入 chain c74c9cb9 未动、8/8 测试有效）**：
1. 移除失效的 `factory.ns` 死属性；臂循环统一使用 cell 级共享 `run_id`
   （`R9B-shared-{tid}-r{rep}`）——delta adapter 的 purpose 仅由 run_id 派生，
   由此实现授权 matrix 字段 "shared-prefix dedup"；臂归属性由 per-run JSON 承担。
2. 零调用接缝测试（桩 transport + 真实 Meter 去重路径）**PASS**：
   每 cell 真实上链 12 次（共享前缀 6 + A 臂 chk v2–v4 重试 3 + B 臂
   split×2+report 3）；A 臂前缀（含 chk:v1 故障触发）全部免费重放；
   B 臂 SPLIT_VERIFY→COMPLETE。4 cell ≈ **48 次调用**，在 52–64 估计带内。
3. QuotaMeter 不计去重重放（r9-2 修复保留）；cap 表 = 80/150K 全局 +
   glm53 65/120K + flash 20/30K，与操作员裁决表及授权记录一致。
4. 三问五分离指标的落点：报告生成率（run status）/ 报告存在条件下的事实质量与
   下游增量（run 产出的 terminal_facts + report 事后用**冻结评分器**零调用评分）/
   Token 成本（tokens）/ Makespan（makespan）。不修改评分器。

**授权下达后的一键发射**：
`cd /root/cap_eval_bench_v1 && nohup python3 integration/stage_c_r9_exec.py >> stage_c_r9b_launch.log 2>&1 &`
（新建 EXEC 目录、flock 独占、SHA+授权双门、SSL 中断可 verify-settle-resume。）
