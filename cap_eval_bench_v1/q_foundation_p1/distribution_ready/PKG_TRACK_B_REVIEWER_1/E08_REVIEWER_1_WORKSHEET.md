# E08-中铁装配 事实级 Gold 核验工作副本 —— 评审者 1

状态：SILVER_SOURCE_ANCHORED / PENDING_DUAL_BLIND_REVIEW（人工双人确认前不得记 GOLD）。
盲化：不可见模型身份/策略来源；独立作答。溯源：原始 PDF sha256=84fe84cb…（草案冻结值）。
来源公告：2026-09-18 立案告知书公告（页1）。

## 逐事实确认（每行必填）

| fact_id | 关键性(拟) | 主体 | 谓词 | 值 | 原文跨度/引文 | 溯源 | 结论 | 跨度核对 | 依据留言 |
|---|---|---|---|---|---|---|---|---|---|
| F1 | 否 | 中铁装配式建筑股份有限公司 | 证券代码 | 300374 | 证券代码：300374 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F2 | 否 | 中铁装配式建筑股份有限公司 | 证券简称 | 中铁装配 | 证券简称：中铁装配 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F3 | 否 | 中铁装配式建筑股份有限公司 | 本公告编号 | 2026-037 | 公告编号：2026-037 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F4 | 是 | 中铁装配式建筑股份有限公司 | 收到立案告知书日期 | 2026-09-18 | 于2026 年9 月18 日收
到中国证券监督管理委员会 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F5 | 否 | 中铁装配式建筑股份有限公司 | 立案告知书发文机关 | 中国证券监督管理委员会 | 中国证券监督管理委员会（以下简称“中国证监会”）下发的《立案告知书》 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F6 | 是 | 中铁装配式建筑股份有限公司 | 立案告知书编号 | 证监立案字0142026049号 | （编号：证监立案字0142026049 号） | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F7 | 是 | 中铁装配式建筑股份有限公司 | 立案原因（涉嫌事项） | 涉嫌信息披露违法违规 | 因公司涉嫌信息披露违法违规 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F8 | 是 | 中铁装配式建筑股份有限公司 | 立案对象 | 中铁装配式建筑股份有限公司（公司本身） | 中国证监会
决定对公司立案 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F9 | 否 | 中铁装配式建筑股份有限公司 | 自查所述立案涉及业务时点 | 实际控制人变更前开展的相关业务（公司自查表述为'可能涉及'） | 本次立案可能涉及公司实际控制人变更前开展的相关业务 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |
| F10 | 否 | 中铁装配式建筑股份有限公司 | 最终调查结论收取状态（截至公告日） | 尚未收到 | 目前，公司尚未收到中国证监会
的最终调查结论 | official_structure | ☐CONFIRM ☐CORRECT_TO__ ☐REJECT ☐UNKNOWN | ☐匹配 ☐不符 |  |

## UNKNOWN（保留，不得自行补全）
- U?: 最终调查/处罚结论及其金额、责任认定（截至 cutoff 证据无法确认；立案≠处罚） —— ☐保持UNKNOWN ☐（误）补全

## 易错点（草案冻结）：F4 收件日≠公告日≠处罚日；F7'涉嫌'不升级；F9'可能涉及'保留限定；U1 最终处罚/金额=UNKNOWN。

评审者签名：________ 日期：______ 置信度：☐low ☐medium ☐high

## 仲裁粒度与 UNKNOWN 规则（操作员 2026-10-30 确认，逐条事实为单位）

1. **单条事实为仲裁单位**（不以整份文件为单位）：
   - 两名评审者均 CONFIRM → 该事实进入确认候选；
   - 任一评审者提出 CORRECT_TO / REJECT / UNKNOWN → **仅该事实**进入分歧/仲裁处理，
     其余事实不受影响。
2. **U1（最终处罚/金额）恒为 UNKNOWN**：不因其他事实全部通过而自动转为 GOLD，
   任何"补全"均按违规处理。
3. 仲裁人可见双方理由，不可见模型身份；仲裁结论粒度同样为单条事实。
