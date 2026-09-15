# Tool-aware v1：40题真实多步金融确认

来源：MultiHiertt dev，UID哈希冻结40题，完整报告上下文、至少两步参考算术。未向模型发送答案、参考程序或标注证据。仅声明本DAG实验新题，不能证明整个工作区及预训练未见。

任务成功 4/40（10.0%），平均质量 0.100；模型tokens 175356；平均实测批任务端到端 212.15s，包含模型加载、排队和live工具收尾。
Tool Node Accuracy（独立解释器核对已执行算术）=1.0，分母30；10题被表达式/前驱有效性检查拒绝或阻断。工具算对不等于模型选对数字或表达式。
Extraction accuracy（参考操作数召回诊断）=55.0%；Semantic accuracy（实际前驱下的最终数值等价代理）=10.0%；LLM Node Accuracy代理均值=32.5%。这些是不同诊断定义，不是同一种通用节点准确率。

| Node Type | #Planned nodes | Small | Medium | Large | R1 | Tool | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---|
| Extraction | 40 | 0 | 9 | 31 | 0 | 0 | 55.0%（诊断定义见上） |
| Semantic reasoning | 40 | 0 | 0 | 40 | 0 | 0 | 10.0%（诊断定义见上） |
| Arithmetic | 40 | 0 | 0 | 0 | 0 | 40 | 已执行30题，解释器核对100% |
| Constraint check | 0 | 0 | 0 | 0 | 0 | 0 | N/A：此自然题图无采购预算约束 |
| Verification | 40 | 0 | 0 | 0 | 0 | 40 | 语法/范围契约；接受30，拒绝/阻断10，不是答案正确率 |

## 候选模型诊断

| Model | Node | Delivered/Requested | Node diagnostic accuracy | Mean tokens | Mean latency s |
|---|---|---:|---:|---:|---:|
| small (Qwen2.5-3B) | unavailable weights/profile | 0/0 | N/A | N/A | N/A |
| medium | extraction | 10/10 | 0.5 | 4109.7 | 7.350275490619242 |
| medium | semantic | 9/9 | 0.0 | 316.8888888888889 | 0.49760166679819423 |
| large | extraction | 10/10 | 0.7 | 3962.2 | 6.913572887517512 |
| large | semantic | 9/9 | 0.0 | 315.8888888888889 | 0.6376316431495879 |
| reasoning | extraction | 10/10 | 0.4 | 4592.7 | 19.944862719997765 |
| reasoning | semantic | 9/9 | 0.0 | 1282.2222222222222 | 19.532600255890024 |
| coder | extraction | 10/10 | 0.5 | 4014.7 | 5.595063245110214 |
| coder | semantic | 9/9 | 0.0 | 321.6666666666667 | 0.6114207491692569 |

候选Q/C/L、加权分数、选择、实际tokens/耗时和缺失原因逐节点保存于CANDIDATE_AUDIT.json/csv。旁路仅冻结的10题；语义节点统一使用实际路由抽取结果，因此不能当作各模型独立端到端效果。

## 路由解释与结论边界

- 沿用原候选池 medium/large/coder，公式 Q−0.05*C_tokens/1000−0.05*L_seconds/10。Small原3B检查点缺失且无本协议可比画像；R1只做旁路诊断，不悄悄加入候选池。
- Q仍为各模型全局均值，没有query条件；C/L只有长度缩放。因此短提示偏large，长提示的耗时惩罚可能令medium获选。这是长度触发的权衡，不是已验证的语义能力路由。
- R1画像来自远程服务，延迟与本地硬件不可直接当作纯模型能力差。tokens是资源用量，不等于跨模型货币成本。
- 本自然任务确认只执行Tool-aware，不存在同题Static/Repair对照，不能把旧采购15%/20%与本结果配对。受控三组比较在controlled目录。
- 不根据旁路结果重选模型，不调Router，不加Local Repair，不启动Dynamic DAG，不推GitHub。

## Router 有效性审计（shadow 20 节点，全候选同输入实测）

| 策略 | Node Quality | 平均 tokens | 平均 latency s | 相对 Router |
|---|---:|---:|---:|---|
| Current Router | 0.250 | 2137 | 3.5 | — |
| Always Medium | 0.250 | 2197 | 3.9 | +0pp |
| Always Large | 0.350 | 2123 | 3.7 | +10pp |
| Always Coder | 0.250 | 2152 | 3.1 | +0pp |
| Always Reasoning (R1 shadow) | 0.200 | 2873 | 18.8 | -5pp |
| Oracle Node（上限） | 0.450 | — | — | +20pp |
Router→Oracle 平均 regret = 0.200（16/20 节点零 regret）。

### 配对 bootstrap（query/node 级，10000 次重采样）

| 对比 | ΔQ [95% CI] |
|---|---|
| router_minus_medium | +0.0pp [-20.0, 20.0] |
| router_minus_large | -10.0pp [-25.0, 0.0] |
| router_minus_coder | +0.0pp [-20.0, 20.0] |
| router_minus_reasoning | +5.0pp [-10.0, 20.0] |

### 预测 Q/C/L 校准（delivered shadow 行）

Spearman：ρ_Q=-0.013，ρ_C=0.917，ρ_L=0.892。
偏差（预测−实际）：tokens +485，latency +40.6s。

| 模型 | 预测Q | 实际acc | 预测tok | 实际tok | 预测lat | 实际lat |
|---|---:|---:|---:|---:|---:|---:|
| medium | 0.687 | 0.263 | 2404 | 2313 | 25.5 | 4.1 |
| large | 0.717 | 0.368 | 2405 | 2235 | 28.6 | 3.9 |
| coder | 0.682 | 0.263 | 2441 | 2265 | 26.8 | 3.2 |
| reasoning | 0.720 | 0.211 | 4527 | 3025 | 112.4 | 19.7 |

### 选择驱动分解

Q(medium)−Q(large) = -0.0291（跨节点恒定）；medium 的 9 次选择全部在 {'extraction': 9} 节点，由 C/L 惩罚项触发（L 项平均差 -3.20pp 分数）。Q_medium - Q_large is a profile constant; a medium selection happens exactly when the combined C/L penalty gap exceeds that constant, i.e. selection is length/latency driven, not query-conditioned semantic routing。

### 结论边界

- Small：unavailable / not required（不在冻结候选池 medium/large/coder 内），未阻塞本分析。
- shadow 仅 10 题 20 节点，全部为 Medium/Large/Coder/R1 四候选 delivered；结论受此规模限制。
- 语义节点路由实际全选 Large（40/40）；Medium 的选择只出现在提取节点。

## Node-level GAP 存在性审计（零生成）

| 节点类型 | n | medium | large | coder | R1 | Oracle | Oracle−最优固定 |
|---|---:|---:|---:|---:|---:|---:|---:|
| extraction | 10 | 0.5 | 0.7 | 0.5 | 0.4 | 0.9 | +0.2 |
| semantic | 10 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | +0.0 |
语义失败分解（shadow 10 题）：提取过+语义过 0；提取过+语义败 5（内在语义失败）；提取败 5（上游继承）。

判定：提取节点存在异质可学习空间（oracle 0.9 vs large 0.7，n=10 CI 宽）；语义节点是全模型统一能力墙（oracle 0.0），其中一半以上为内在失败而非上游继承——这不是路由问题，是能力/分解问题。Node-conditioned routing 目前只在提取型节点有信号。

