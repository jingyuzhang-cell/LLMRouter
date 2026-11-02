# P1 评审者执行手册（轨道 A：C9 Judge 校准 / 轨道 B：E08 事实级 Gold）

> 目的：两名独立人工评审者到位后，**零依赖工程侧**即可开工。本手册只描述既有冻结材料的使用方式，不引入新评分逻辑。
> 铁律：禁止 LLM 代替人工评审；盲于模型、盲于调度策略；SILVER/合成数据/未校准 Judge 不得冒充人工 Gold。
>
> **评审者资格（操作者 2026-10-30 界定）**：不必是高校教授或独立机构——其他部门有相关业务/专业知识的同事、未参与本项目算法设计与 Gold 构建的专业人员、符合要求的外部专家均可。核心是能独立判断且不接触模型身份、调度策略与模型生成答案。无合格人员则保持 BLOCKED；**严禁自答自审包装成独立 Gold**。
>
> **一次性汇总流程（操作者指令）**：两轨并行，评审者交回 `C9_HUMAN_REVIEWER_{A,B}_SCORED.jsonl` + `REVIEW_CONFIRMATION_{A,B}.json`（如有分歧加 `ADJUDICATION_E08.json`）后，一次性运行汇总，不再拆零碎授权。

## 轨道 A：C9 双人盲审（→ Judge 校准用 Gold）

**材料（只读，SHA-256 已核封）**：`/root/phase_c9_0/human_judge_calibration/`
- `C9_HUMAN_REVIEWER_A.jsonl` / `C9_HUMAN_REVIEWER_B.jsonl`：各 30 组、共 123 候选（A/B 内容相同，模板未打分）
- `C9_HUMAN_REVIEW_INSTRUCTIONS.md`：0–4 盲评规则；`HUMAN_REVIEW_COMPLETION_GUIDE_ZH.md`：填写说明
- `C9_HUMAN_CALIBRATION_MANIFEST.json`：30 组构成（能力维度×上下文长度分层，种子冻结）
- `C9_HUMAN_CALIBRATION_SEALED_MAPPING.jsonl`：盲标→模型映射（**评审期间严禁查看**，评审完成后才可开封）

**步骤**：
1. 评审者 A、B 各自独立：逐候选打 0–4 整数分 + 证据性理由；逐组填 `reviewer_confidence`（low/medium/high）。
2. 分别另存为 `C9_HUMAN_REVIEWER_A_SCORED.jsonl`、`C9_HUMAN_REVIEWER_B_SCORED.jsonl`（放同目录；模板原文件不动）。
3. 分歧处理：分差 >1 的候选由第三裁决者终裁（可看双方理由、不得看模型身份）；分差 ≤1 按冻结规则取保守均值。
4. 完成后汇总命令（默认参数即约定文件名）：`python3 /root/analyze_c9_human_calibration.py`
   —— 输出含 within-one 一致率、MAE、**二次加权 Kappa（quadratic weighted kappa）**、Spearman、逐组/逐候选分歧清单与裁决准备材料。

**下游门槛（P2 Judge 校准，C9 冻结值）**：解析成功 ≥0.95；human within-one ≥0.80；human MAE ≤0.75；重复一致 ≥0.80；顺序扰动 MAE ≤0.50；模型家族偏差必审。**评审者间一致性本身不足时，人工标签不得当作绝对真值使用。**

## 轨道 B：E08 事实级 Gold 确认（→ 资本市场终端质量评价用 Gold）

**材料**：`/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie/`
- `TASK_CONTRACT_E08_SILVER_DRAFT.json`：10 事实 + 1 可选 + 1 UNKNOWN 的 SILVER 草案合同（全部机器锚定、双哈希绑定、偏移精确）
- `FACT_SHEET_E08.md`：逐事实核验单（含易错点：收件日≠公告日、"涉嫌"不得升级、"可能涉及"保留限定、立案对象=公司本身）
- `source_pages.json` / 原始 PDF：`/root/capital_opinion_pilot/benchmark_v1/docs/E08-zhongtie.pdf`（sha256 与冻结 manifest 一致）
- `REVIEW_CONFIRMATION_TEMPLATE.json`：确认记录模板

**步骤**：
1. 评审者 A、B 各自复制模板为 `REVIEW_CONFIRMATION_A.json` / `REVIEW_CONFIRMATION_B.json`，独立填写。
2. 逐事实核对四件事：① 事实本身是否成立（对照公告原文，非对照任何模型答案）；② 原文跨度（引文/起止/双哈希）是否与事实一一对应；③ 值/单位/日期类型/主体关系是否正确；④ `critical_proposed`（F4 收件日 / F6 编号 / F7 涉嫌原因 / F8 立案对象）是否同意列为关键。
3. verdict 逐项取 CONFIRMED / CORRECTED / REJECTED / DOWNGRADE_UNKNOWN；U1 确认确属证据不足。
4. 分歧由第三裁决；晋升由工具一次性完成（已预建并全路径验证）：
   ```
   python3 /root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie/promote_e08_gold.py
   ```
   工具规则：双人 CONFIRMED（或第三方裁决 CONFIRMED，裁决人须区别于两位评审者且盲模型盲策略）→ GOLD_CONFIRMED + critical 冻结 + 版本/sha256 冻结；双 REJECTED → EXCLUDED（留痕）；双 DOWNGRADE → 转 unknown_items；CORRECTED 或无裁决分歧 → **拒绝晋升并指出事实号**（修正后须重走双人确认）；关键性（F4/F6/F7/F8）须双方同意或裁决同意；晋升后自动跑否决自检（满分答案=1.0/PASS、关键编号损坏=0/FAIL），自检不过不产出。已验证路径：无文件拒绝 / 合成自检（仅 /tmp、SYNTHETIC 标记）/ 分歧拒绝 / 裁决晋升，全部符合预期。
5. 晋升产出 `TASK_CONTRACT_E08_GOLD_v1.json` 后，即形成**第一批来源完整、经独立人工裁决的事实级 Gold**。

**禁止**：看到任何策略/模型的答案之后反过来补充 Gold；用 SILVER 记正式分；跳过裁决直接晋升；自答自审。

## 两轨汇合 → P2 启动条件

1. 轨道 A：两份 SCORED 文件齐 + 一致性统计出炉（含加权 Kappa）；
2. 轨道 B：E08 首份 GOLD 合同冻结（或诚实记录未通过项）；
3. 满足后 P2 启动：机器评分器（Qwen-Max/GLM/Doubao 等）在**留出人工标签**上过六项冻结门槛 + 事实级指标 + 稳定性扰动，未过者不得产生正式质量标签。

## 状态查询

研究状态与纪律见 `/root/q_foundation/QF_GOVERNANCE_PLAN.md`（P0 已 CLOSED 于 terminal_quality_v1.2.3；PR #5 待操作者合并审批）。
