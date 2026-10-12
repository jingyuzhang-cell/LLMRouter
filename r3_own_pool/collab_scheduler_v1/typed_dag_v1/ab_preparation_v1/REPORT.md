# Goal IR / input_producers 真实 A/B 验收准备

准备完成；真实请求0，未加载权重或启动服务。275/275零调用测试通过：原270项 + 新5项。PREFLIGHT.json通过；这不等于真实LLM生成Goal IR或实验已经批准。PROTOCOL.json状态PREPARED_NOT_AUTHORIZED。

## 真实接线核查与修改

此前 InitialDAGGenerator 的 goal_ir 仅在通用生成接口及Stub上接通；fresh_acceptance 没有planning-mode参数，HTTP只对旧plan/repair采用JSON Schema；prepare_metered_request只识别旧操作，Goal IR会误归入node阶段并使用256输出上限。本轮修复这些真实入口缺口，没有扩大验证器功能。

修改 generation.py：增加结构验证PASS事件（审查之前），以区别首次结构合法和最终非回退接受。
修改 heterogeneous_models.prepare_metered_request：plan_goal_ir/repair_goal_ir归入plan/repair，768输出上限，与A相同。
修改 fresh_acceptance.py：可选 --planning-mode semantic/goal_ir；一至四题；从预算配置载入StageBound；HTTP response_format测试函数覆盖A/B Schema和语义审查；保存planning_mode、首次/修复结构合法及审查状态；串行服务激活上限由7×题数生成。原两题默认入口仍为semantic，不修改旧冻结包。
新增 ab_acceptance.py：默认只预检；执行时先核对所有输入和源码/模型配置哈希，再依次调用原fresh_acceptance，两组完全独立输出、预算和缓存；服务错误或未知终局停止，不重试/续跑。新test_ab_acceptance.py五项验证HTTP Schema、Goal IR阶段计量、共同最坏包络、两组模式、未知失败预留隔离。

真实路径为：

```text
ab_acceptance --execute（将来新授权）
 -> 源码/任务/评分/Schema/模型配置/预算hash检查
 -> fresh_acceptance --planning-mode semantic 或 goal_ir
 -> 三模型真实加载检查（本轮未运行）
 -> PreparedExecutor -> prepare_metered_request -> ScopedBudget.reserve
 -> SerialModelService + 带Schema的真实HTTP（无重试）
 -> InitialDAGGenerator
    A: compile_producer_plan
    B: compile_goal_ir -> compile_producer_plan
 -> 同一assemble_semantic / Graph / validate
 -> 同一coverage_review（启发式，不是语义正确性证明）
 -> 同一异构类型基线allocate
 -> 同一TypedExecutor/source_selection/事实血统/调用账本
 -> 独立EVALUATION_ONLY + 同一score_v21
```

执行能力已零调用接线验证，模型是否能输出Goal IR、服务是否支持真实该Schema仍未验证。

## 新任务冻结与评分隔离

TASK_MANIFEST.json四个public任务：

1. stage3-ab-independent-charity-net-fund-20261011-1：两类捐赠汇总、扣处理费；独立gold373。
2. stage3-ab-independent-seminar-seats-20261011-2：两房间行列座位汇聚、加入额外椅子；独立gold191。
3. stage3-ab-independent-library-license-20261011-3：两类许可证费用、固定设置费和返款；独立gold220。
4. stage3-ab-independent-lab-mean-mass-20261011-4：两组净质量分支汇聚、等分；独立gold40。

具体数值和内容hash见清单，gold仅在EVALUATION_ONLY.json；规划Prompt、调度器和执行器只接收public任务。所有任务和内容在冻结前扫描 /root/r3_own_pool 精确UID/问题/表/文本匹配为0，未用于历史调试或Stub结果验收，非太阳能/行程/库存/产能任务。该扫描不保证跨仓库或语义近重复；任务是人工构造简单算术诊断，不是benchmark独立泛化样本。

冻结后只对初始Prompt做离线序列化和本地Tokenizer计数，派发前强制中断、未得到模型/Stub规划响应，未依据任何任务结果调参或改题。Gold文件不进入Prompt捕获。Source SHA覆盖typed模块、原计量/evaluator、评分器和静态执行基础；MODEL_BINDINGS冻结三个实际路径/served ID及config/generation/tokenizer哈希，实际权重仍必须在未来Stage A全文件核验。

## 公平性与口径

A/B同四题、同顺序、规划medium、温度0、同各阶段Token硬限、最多1次修复/1次恢复、5节点，同异构分配规则、source_selection、Graph最终验证/语义审查和score_v21。两组无跨组缓存及预算借用。固定回退可记录，不执行、不计为接受。

A/B唯一预期变化是规划协议及对应Prompt/Schema，完整8份Prompt落盘。A直接选择节点producer refs，B声明typed data symbols并由程序解析唯一生产者；两方得到完全相同任务输入，不提供gold或额外数值提示。B有IR特定类型/单位声明前置检查，A有producer声明前置检查；共同准入层是原Graph验证/语义审查/执行。不能称两个前置语法协议完全相同，也不能将IR额外约束本身当作质量收益。

初始Prompt实测（medium本地Tokenizer完整chat模板）：A1728/1738/1735/1748；B1599/1609/1606/1619，均≤3072。Prompt长度差是协议开销差异，应报告，不是额外测试信息。

当前最小入口采用整组顺序A→B，避免另建资源调度系统。这会引入时间/服务器状态混杂；因此墙钟比较仅诊断，服务需求和模型加载/切换分列，不宣称严格随机交错因果时延收益。若要严格任务级交错，须在新实现和授权协议中明确，不能在运行中改变顺序。

## 两组独立资源包络（建议，未批准）

| 阶段/每题 | 最多请求 | 最大输入/请求 | 最大输出/请求 | 最坏Token |
|---|---:|---:|---:|---:|
| 首次规划 | 1 | 3072 | 768 | 3840 |
| 一次规划修复 | 1 | 6144 | 768 | 6912 |
| 语义审查（首次和修复后） | 2 | 4096 | 384 | 8960 |
| 最多五个LLM节点（保守，工具不计请求） | 5 | 2048 | 256 | 11520 |
| 一次执行恢复 | 1 | 2048 | 256 | 2304 |
| 合计 | 10 | — | — | 33536 |

验证请求已包含节点/恢复；最终评分为程序score_v21，零模型调用。验证节点实际输出上限160，表使用256的保守预留；失败未知使用量不释放。每次调用使用分配模型自身Tokenizer，严格检查上下文8192。

每题硬限12请求/34000Token：生成修复审查20000、执行验证恢复14000，互不挪用。每组4题硬限48请求/136000Token/12000秒；最坏已定义路径40请求/134144Token，逐题执行预留保护其余任务。两组总上限96请求/272000Token/24400秒，A/B余量不可转移。

每组加载Stage A最多3激活，预留960秒（3×300加载+20卸载）；Stage B最多28激活（7×4题），最坏10190秒（28×320 + 40×30请求 + 30清理）；合计11150秒，12000秒余量850用于文件核验、CPU和其他开销。加载/切换是受限上限，不是保证耗时；Stage A后还要按剩余墙钟再次检查Stage B能否完整容纳，不能则停止。全局24400秒包括两组及400秒编排余量。这是约6小时47分的硬上限，不是预计耗时。

本包不是过去24请求/56k/90分钟信封的延用。实际repair/review/node Prompt依赖候选和节点输出，不能提前证明任意模型响应均能放入输入边界；超过边界会在派发前停止，绝不截断或扩大预算。包络保证有界派发和预留保护，不保证两组都完成或模型生成成功。未冻结美元单价，只报告Token；加载、服务、墙钟分别记录。

## 指标与停止规则

逐题逐组保留原始候选、修复、审查响应、结构PASS事件、错误、Graph/assignment、HTTP输入/输出、DISPATCH/预算及TYPED轨迹。

首次结构合法：attempt0 structural_validation PASS；修复结构合法：attempt1 PASS；二者与semantic_review PASS、GENERATED/REPAIRED非回退接受分别统计。审查未执行为NOT_EVALUATED，不能当0次审查通过率。节点数、边集取实际Graph，不采用固定模板。新字段first_structural_legal/repair_structural_legal与旧first_legal（最终接受语义）区别保留。

仅非回退完整准入图执行；每节点分配及实际模型身份/权重、Token、服务时延、状态与事实血统保留。COMPLETE不等于答案正确；评分仅最后读取独立gold。恢复额外开销单列。无法执行/评分保留失败，不从分母中悄悄排除。样本4题只报原始计数、比例和配对案例，无显著/泛化提升结论。

任意阶段请求、Token、输入/输出、上下文、墙钟、服务身份或不可恢复错误触发停止；无HTTP重试、无自动追加任务和预算。失败未知用量按预留保留；账本缺失消费UNKNOWN，不推断0。独立两组预算限制使总请求/Token有界；一组出基础设施错误主入口停止，不自动启动另一组。

## 测试与可执行入口

257项typed + 18项原evaluator/runtime =275/275。日志见TYPED_TESTS.log、FIXED_TESTS.log；PREFlIGHT及Prompt预检均零调用。

本轮允许且已执行：

```bash
python3 -m collab_scheduler_v1.typed_dag_v1.ab_acceptance \
  --packet collab_scheduler_v1/typed_dag_v1/ab_preparation_v1
```

以后获得本包独立预算授权且重新核验hash/测试/GPU空闲后，才能执行：

```bash
/root/autodl-tmp/r3_venv/bin/python -u -m collab_scheduler_v1.typed_dag_v1.ab_acceptance \
  --packet collab_scheduler_v1/typed_dag_v1/ab_preparation_v1 \
  --output collab_scheduler_v1/typed_dag_v1/stage3_ab_real_01 --execute
```

结果将在新目录A/、B/、AB_RESULTS.json以及组日志中保存；不覆盖历史数据，不允许resume重复派发。入口--execute表示未来获准执行的显式行动，不是当前准备请求给予授权。

准备已结束，等待独立真实调用预算授权。
