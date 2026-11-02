# P0 Terminal Quality — 证据级预审（2026-10-31，零调用）

**目标**：为独立复审准备证据清单——哪些评价能力已有充分证据支持、哪些仍阻碍可信质量信号、
达到什么条件才能进入 P1/P2。**本预审不冒充外部独立复审。**

---

## 一、当前实际状态

| 项 | 值 |
|---|---|
| 代码 | `/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4/terminal_quality.py`（865 行） |
| 测试 | `test_terminal_quality.py`（810 行，**64 个测试**） |
| 版本 | v1.2.3（经 v1.0→v1.1(F1-F6)→v1.2(F7-F10)→v1.2.1(H1/M1-M7/L1-L3/L7-L8)→v1.2.2(L5)→v1.2.3(收尾)六轮迭代） |
| 真实执行 | **本次预审实际复跑：64/64 PASS，两次运行输出一致**（Python 3.12.3） |
| PR | #5 保持 DRAFT，未合并、未批准 |
| 模型调用 | 0（代码审读确认，仅 stdlib re/unicodedata/decimal/typing） |
| 身份 | IMPLEMENTED_OFFLINE / NOT_HUMAN_CALIBRATED / NOT_PRODUCTION_INTEGRATED |

## 二、已验证的评价能力（测试有真实断言覆盖）

### 护栏类
- SILVER 不得产生正式 Q（GOLD 门禁 + min_gold_coverage）
- 哈希绑定来源跨度（_span_is_valid 重算 page sha256，不一致即拒）
- 交付失败与语义分离（Q_final=NULL / Q_delivered=0 / R_delivery 独立记录）
- 零 Gold 合同不出正式 Q（NO_FORMAL_GOLD blocking）
- 未校准 Judge 拒绝授权语义等价（F2 修复 + 测试）
- claim 抽取不完整 blocking
- 关键词短引文不算证据支持

### 事实匹配类
- 主体/谓词/值/单位/日期类型五要素匹配（类型不匹配不出 TP）
- 换算/派生事实需全部输入为正式 Gold（F6 递归校验 + 环安全）
- 日期使用真实日历校验（含闰年，F5）
- NaN/Infinity 不崩溃（F3 + M3）
- 重复不虚增 TP（F4 标签分类）

### 关键事实硬门禁（F1 三态）
- PASS → Q_final = Q_raw
- FAIL（关键事实确认错误/遗漏/证据未满足）→ Q_final = 0
- UNKNOWN（关键事实缺正式 Gold）→ Q_final = NULL
- Q_raw 恒输出（诊断保留）

### 对抗加固（v1.2 → v1.2.3）
- 合同结构门禁（重复 fact_id、不可解析派生输入在匹配前阻止）
- 数值配置校验（权重有限正数、覆盖有限 [0,1]、容差有界）
- Judge 凭据=注册表绑定 judge_id+64-hex 工件哈希+盲标+绑定 claim_id
- UNMAPPED_SUPPORTED_CLAIM 独立状态（超 Gold 的真实断言既不 TP 也不 fp，Q=NULL）
- 非物质性 claim 记录审计不静默丢弃
- 严格 JSON 输出（allow_nan=False，非有限 Q 终端守卫）

## 三、仍阻碍可信质量信号成立的问题

| # | 问题 | 严重性 | 状态 |
|---|---|---|---|
| G1 | **NOT_HUMAN_CALIBRATED**：Judge 校准、语义等价、问题相关性维度全部依赖人工 Gold——目前为 0 | **致命** | P1 Track A 等待人类评审者 |
| G2 | **NOT_PRODUCTION_INTEGRATED**：未接入任何真实流水线；零真实文档端到端评价（E08 自检为手动注入） | 高 | 需 P2 校准后在真实任务上验证 |
| G3 | **PR 未合并**：独立代码复审 + 最终审批未完成 | 高 | 流程性——外部 reviewer |
| G4 | 物质性判定（material=true/false）由抽取阶段冻结规则决定——评估器信任抽取完整性 | 中 | P2 需验证抽取不变式 |
| G5 | L4 边界：原生标注证据语义（数据集级 vs 合同级 hash 绑定）待 P2/P3 冻结前裁定 | 中 | 记录在案，不阻塞预审 |
| G6 | L9 边界：blocking-vs-veto 优先级（扣留 > 零否决）已文档化但未经操作者正式裁定 | 低 | 记录在案 |

## 四、进入 P1/P2 的条件

### P2（机器评分校准）的前置条件
1. P0 PR 通过独立代码复审并合并
2. P1 Track A（C9 双人盲审）完成→人类 Gold 校准
3. 至少一批真实文档上的端到端评价合同建立（E08 V3.1 已就绪为首个此类合同）
4. 机器评分 vs 人类 Gold 的对照实验设计冻结

### P1 Track A 的前置条件
1. 两名独立人类评审者到位
2. 按 C9_HUMAN_CALIBRATION_PROTOCOL 执行 123 候选双盲评分
3. 分歧仲裁 + 加权 Kappa 一致性计算

## 五、预审结论

**评价器代码的工程可靠性已充分验证**（64/64 真实执行、确定性、零调用、隔离性、六轮对抗加固）。
**可信质量信号尚不成立**——瓶颈不在代码而在人类校准（G1）和生产集成（G2）。
P0 的下一步是完成独立代码复审与合并审批，然后等待 P1 的人工 Gold 建设为 Judge 凭据系统提供校准基准。

**这份清单供独立复审者直接使用。**
