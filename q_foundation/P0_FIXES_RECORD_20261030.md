# P0 修复记录 — F1–F6 按操作者裁定实现（2026-10-30 第二轮）

依据：操作者 2026-10-30 裁定（F1 三态事实级否决；F2 确定性优先；F3 非有限数值；F4 标签；F5 日历；F6 GOLD 派生纯度；PR #5 保持 DRAFT 至独立复审 + 最终审批）。

## 交付物

- **PR #5 分支 commit 30ce7b6a**（已推送）：`terminal_quality.py` 六项修复，版本升至 `terminal_quality_v1.1`；`test_terminal_quality.py` 新增 12 项回归；协议新增 §9 关键事实硬门禁、§10 确定性优先；README 护栏更新；审计文档追加修复记录。PR 评论：issuecomment-6523406590。
- **真实执行**：`python -m unittest -v` → **Ran 30 tests in 0.007s — OK（exit 0）**（18 原 + 12 新）；py_compile OK；零模型调用；历史产物零改动。

## 修复明细（对照裁定）

| # | 裁定 | 实现 | 回归测试 |
|---|---|---|---|
| F1 | 三态否决（非封顶/NULL 简单化） | `critical_gate`：PASS→Q_final=Q_raw；FAIL（任一关键事实错误/遗漏/evidence_required 未满足）→0；UNKNOWN（关键事实缺正式 Gold 且无已确认错误）→NULL；FAIL 优先；Q_raw 恒输出 | 关键金额错10×（Q_final=0/Q_raw=0.625）、关键遗漏、SILVER 关键→UNKNOWN、证据要求未满足→FAIL |
| F2 | 确定性核验优先 | `_semantic_core_matches`：unit/date_type/subject(+别名)/typed 值/派生先于 SUPPORTED；fact_id 显式路径同受约束；Judge 仅授权谓词与文本类同义 | SUPPORTED+错日期→fp（不再 TP）；SUPPORTED+同义谓词+正确值→仍 TP |
| F3 | NaN/±Inf 明确处理 | `_decimal` 拒绝非有限（候选→fp 不崩溃）；Gold 合同非有限/容差不可解析/非法日历日期→`GOLD_CONTRACT_INVALID_VALUE` blocking；算术异常兜底 | NaN+Infinity 候选不崩溃；Gold NaN→blocking |
| F4 | 只改标签不动判定 | 值正确重复一律 `DUPLICATE_CLAIM`+warning（含无引用）；错误值重复仍 `WRONG_GOLD_FACT_VALUE_OR_RELATION`；fp 记数不变 | 无引用正确重复→DUPLICATE 标签、无 blocking |
| F5 | 真实日历含闰年 | `_date` 用日历构造校验 | 2024-02-29 有效；2023-02-29、2026-02-31 无效 |
| F6 | GOLD 派生仅 GOLD 输入 | `_formal_gold` 递归校验输入（防环）；违规派生事实退出正式 Gold（warning），关键时→UNKNOWN→NULL | SILVER 输入三变体：非关键→退出评分；关键→UNKNOWN→NULL；min-coverage=1→覆盖门禁 |

测试先行设计捕获：silver 派生回归测试首跑失败，暴露基础夹具 F1 自带 `critical=True`——「关键派生事实+SILVER 输入→UNKNOWN→NULL」恰为裁定的正确交互，测试现同时钉住两面。

## 轨道进展（同轮）

- **轨道 A**：C9 包 6/6 SHA-256 完整性 OK；冻结协议核读（30组/123候选/裁决规则/六门槛/judge 选择禁入项）。待人类评审者。
- **轨道 B**：E08-中铁装配首份 SILVER 草案合同（10 事实+1 可选+U1 UNKNOWN；双哈希+精确偏移锚定；`KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie/`）。确定性自检三连通过；并抓到两个真实集成坑：manifest pool_id 不唯一（按 sha256 反查）、provenance 必须用评分器冻结枚举（`official_structured_record`）。**三态门禁在真实文档上闭环验证：F6 编号写错→Q_final=0 / Q_raw=0.94 保留。** GOLD 数量：0。

## PR #5 检查单状态

- [x] 18 项测试真实执行（47668268）
- [x] 确定性与隔离性验证
- [x] F1–F6 最小用例复现
- [x] F1–F3 修复及回归测试（30ce7b6a）
- [x] F4–F6 修复及回归测试（30ce7b6a）
- [x] 完整测试重新执行（30/30 OK）
- [ ] 独立代码复审
- [ ] 最终合并审批

状态不变：IMPLEMENTED_OFFLINE (v1.1) / NOT_HUMAN_CALIBRATED / NOT_PRODUCTION_INTEGRATED。
