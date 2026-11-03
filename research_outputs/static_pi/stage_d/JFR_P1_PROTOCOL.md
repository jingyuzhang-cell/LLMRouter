# JFR-P1 冻结协议（测试前）

## 机制
- 基础分配：B–E 使用 all-DS（最大化修复预算）；A 为历史 V-CR（base m）。
- 修复单元：节点（一次尝试可修复该节点的 1–2 个 DEC 事实）。优先级 r → t → p → m → v → e0 → e1。
- 联合修复 D/E：对每个事实依次检查 fact recovery、localization、support；**三者全部成功才提交 TP∧loc∧sup**；任何一项失败不写回（mechanism gate），不做“失败状态直接覆盖为成功”。
- B：只改 fact（out=TP），loc/sup 保持实际；C：只对已是 TP 的事实修 loc/sup，不做事实补全；E：D + 一次上游父节点联合修复。
- 验证器：坏节点以 sens=.75 标记，好节点以 1−spec=.15 误报；Sham 以固定 0.30 随机标记且修复为 no-op（仍计成本/时延）。
- 修复参数：p_fact=.70, p_loc=.70, p_sup=.70, p_gate=.70；joint 成功概率按顺序相乘。
- 成本/时延（节点价格/时延单位）：B .10/.08；C .15/.10；D .25/.12；E .30/.15；每次尝试计入预算与 Makespan；成本 cap 与 strict 1.10 / matched 1.20 在每次尝试前检查。

## 五组
A = 原始 V-CR（历史 Q 57.16%，m base）
B = 只修事实（DS base）
C = 只修定位+支持（DS base）
D = 事实+定位+支持 联合（DS base）
E = D + 上游恢复（DS base）

## 对照
- stable H1 .20（200 任务 pilot；通过后 800）
- H0 pure null（200）
- Sham verifier（stable H1 .20，200；no-op 修复）
- A 使用历史结果，不重跑；B–E 同任务/同 CRN。

## 验收门
1. 机制门：D/E 不允许部分提交；审计 committed 状态必须满足 TP∧loc∧sup。
2. 质量门：终端 Q≥70%，且 24 任务 bootstrap 95% CI 下界>70%。
3. 归因门：stable D − H0 D ≥5pp；Sham Q 与 base Q 差 ≤0.5pp。
4. 资源门：成本≤对应 cap；strict 1.10 或 matched 1.20 不突破；修复成本/时延计入。
5. 不通过则停止，不跑 800，不跑 J-MO，不调参数追 70。

## 纪律
零真实 API；192 HOLD；不改评分/Gold/DAG/MVS/任务；不改 R3/R4/R5 数据。
