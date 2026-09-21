# P3 跨领域泛化：预注册方案（2026-09-21 草案，未执行）

## 目的
回应审稿人核心质疑之三："是否只对财务表格有效"。检验三个核心发现在非财务复杂任务上是否成立：
1. Stage-wise complementarity（阶段级互补性真实存在）；
2. Conditional ≠ Propagated（条件能力不等于传播能力）；
3. Selective Dynamic > Aggressive Switching（选择性动态适应安全且随结构深度增益）。

## 本地可用数据（已盘点，2026-09-21）
`/root/autodl-tmp/llmrouterbench_r2_data/bench-release/`：27 个域的逐模型应答库（aime、math500、gpqa、humaneval、mbpp、livecodebench、bbh、mmlupro、finqa、medqa、korbench 等）。
- 首选域：**math500（多步数学）** 与 **humaneval 或 mbpp（代码）**——与财务表格差异最大、且自带确定性执行器（数学表达式/单元测试）。
- 多跳文本（HotpotQA/MuSiQue）本地无原始数据，若需引入必须先下载数据集本体并记录 sha256，不用 bench-release 的应答库代替题目。
- 第一步（下一轮，零调用）：核实 bench-release 文件 schema 是否包含题目文本与 gold；若只有应答与分数，则改用原始数据集文件。

## 冻结协议（执行前提交，one-shot）
1. 任务选取：每域按 sha256("xdomain:"+id) 升序取前 N=100，排除任何与本工作区重叠的条目；tokenizer 长度守卫。
2. 模型池：沿用 medium/large/coder（不换池，保证与主链可比）。
3. DAG 映射（域特定，冻结后不改）：
   - math500：parse(题面与条件, large) → solve(表达式, medium) → verify(重算, coder)；
   - code：read(题面与签名, large) → implement(代码, medium→coder) → execute(确定性单元测试, 本地执行器, 零调用)。
   - 失败检测：math 用执行器对拍（非 gold、可部署）；code 用单元测试（天然可部署）——两域的检测信号都比财务域更强，是对 P2 的直接补强。
4. 主实验链（每域六臂）：Always Best / Query Router / Type Router / Static DAG / Dynamic DAG / Oracle。预算规则、生成配置、选择性更新规则与 multidag_dynamic_120 逐字一致。
5. 预注册读出：三发现各自的可复现判据在冻结文件中写死（例如发现 2 = 同模型链 Oracle 与条件口径 Oracle 的差值方向一致性；发现 3 = ΔQ CI 与选择性更新审计）。
6. 禁止事项：不在任何新域数据上调阈值；负结果原样报告；每域运行完成后 24h 内写入正文。

## 状态
- [x] 数据盘点
- [ ] bench-release schema 核实（零调用）
- [ ] 冻结文件 + 提交
- [ ] 运行（GPU，预计每域 <1h）
- [ ] 分析 + 写入论文
