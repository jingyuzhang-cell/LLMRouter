# Stage 3 A/B v2：服务Schema修复与交错恢复准备

本轮真实HTTP请求0，模型加载0。284/284零调用测试通过（原275项+9项）。新的离线PREFLIGHT通过；不启动完整真实实验，尚无下一轮调用授权。

## 1. 根因审计

实际环境vLLM 0.11.0、xgrammar 0.1.19、jsonschema 4.25.0。SerialModelService.activate 的服务命令显式 `--structured-outputs-config '{"backend":"xgrammar","disable_any_whitespace":true}'`，不是根据历史环境猜测后端。

上一轮A第一题的完整HTTP400响应在 stage3_ab_real_01/A.log、A/RESULTS.json及A/GENERATION_EVENTS.jsonl，原始消息：

```json
{"error":{"message":"The provided JSON schema contains features not supported by xgrammar.","type":"BadRequestError","param":null,"code":400}}
```

A/HTTP_INPUTS.jsonl保留实际发送的Schema和请求。A/DISPATCH.jsonl只有1条reserved=2496，没有response；实际Token未知，预留保留，不能结算为0。29个历史文件的逐字节SHA核验一致（OLD_RUN_SHA256.json），未修改原失败记录。

实际vLLM `v1/structured_output/backend_xgrammar.py` 的 has_xgrammar_unsupported_json_features 明确拒绝数组uniqueItems/contains/minContains/maxContains、字符串format、对象minProperties/maxProperties/propertyNames/patternProperties、数值multipleOf。validate_xgrammar_grammar先编译，再调用该检查，所以单独xgrammar编译通过仍可能HTTP400。后端文件hash在SCHEMA_AUDIT.json，版本与源码已冻结。

递归审计结果：A规划/修复共享完整Schema有6处嵌套uniqueItems；B规划/修复0处；原coverage_review和source_selection代表Schema均无上述不支持项。四类传输Schema分别通过实际vLLM纯检查函数和xgrammar编译。未假设其他任意Schema均支持；未来变更后重新检查，未知不支持项拒绝。

## 2. 双层Schema实现

新增service_schema.py：

- unsupported：递归定位实际后端拒绝的关键字，返回path/keyword/value。
- to_service_schema：仅确定性移除array中的uniqueItems，原完整Schema不变；返回完整/服务Schema哈希、差异和副本。不对contains、format等其他关键字自动删改，明确失败。
- full_validate：Draft202012Validator完整Schema验证，错误转成PLANNING_SCHEMA反馈。
- backend_precheck：读取实际部署vLLM后端，仅运行其纯检测函数AST，并调用xgrammar编译；不导入模型执行器，不请求服务、不用GPU。
- classify_http：Schema HTTP400分类为SERVICE_SCHEMA_UNSUPPORTED，其他为HTTP_SERVICE_ERROR。

修改fresh_acceptance.response_format，HTTP采用服务Schema；派发日志SCHEMA_TRANSPORT.jsonl保存两层哈希及差异。HTTP_ERRORS.jsonl记录完整错误体/类别，失败用量UNKNOWN继续保留，不自动重试。

修改generation.InitialDAGGenerator：增加strict_planning_schema。真实入口显式True，在JSON解析后、生产者和合同装配前验证完整Schema。旧诊断Stub默认False保留历史协议兼容，不冒充真实准入。生成与修复使用同一完整Schema；A/B均如此。原唯一引用/producer重复、类型冲突、悬空引用、循环、最终输出连通性及执行血统检查保留。

这只减小服务“输出约束表达能力”要求，最终合法性没有放宽。重复列表可能从服务返回，但完整Schema和compile_producer_plan仍会拒绝。未改冻结48配置、评分器或历史任务gold。

## 3. 测试与离线服务能力证据

typed266项+原evaluator/runtime18项=284/284。新增9项覆盖嵌套uniqueItems转换且原Schema不变、其他已知不兼容特性拒绝、合法无变化转换、转换后重复仍被严格拒绝、A/B完整Schema合法样例、生成/修复同服务Schema、HTTP400分类、required字段不丢、旧账本保持未知预留且未改。

原未知失败预算隔离测试继续通过。服务端实际后端A/B独立编译见SCHEMA_AUDIT.json，不是手写“支持”断言。审查/事实选择的实际Schema构造器也编译通过；候选/事实候选数量改变时是动态Schema，真实请求前仍保留检查和严格程序验证，不能由代表样例保证所有未来动态内容有效。

没有发送任何诊断HTTP请求，因此本次不会生成任务成功证据。若以后需要单独验证真实round-trip，可申请2请求（A/B各1）诊断信封，任务结果必须标诊断、独立保留未知Token；本轮没有该授权，也未进行。

## 4. 新冻结版本与任务角色

ab_preparation_v2独立保存TASK_MANIFEST、四个单题manifest、EVALUATION_ONLY、原完整SCHEMA_A/B、SERVICE_SCHEMA_A/B、源码/模型配置/后端hash、service_versions、8份实际Prompt及hash、两组预算和cell预算、交错cells、TASK_ROLES、历史文件hash、测试及PREFLIGHT。PROTOCOL状态PREPARED_NOT_AUTHORIZED。

四道题public内容/gold从v1字节复制，未为了通过结果改题。第一题A曾发送失败HTTP，未获得候选；其余三题未发送HTTP，B未运行。没有基于这些题输出调Prompt或语义策略；本轮仅做任务无关Schema传输修复。该面板正式登记为“冻结恢复A/B面板”，不再把首题称为从未接触过的新任务，也不将重测当作全新独立抽样。其他题仍无真实结果暴露；离线Prompt序列化不获得模型答案。

Gold只最后score_v21读取；完整Schema/服务Schema及Prompt不包含独立gold文件。模型路径/served ID及配置/tokenizer hash继承原绑定；真正执行前依然需要完整权重和三模型服务身份检查。

## 5. 按任务交错入口

新增ab_interleaved.py，默认仅离线check；将来获准--execute才调用原fresh_acceptance，一题一个独立进程/目录/预算，顺序冻结为：

```text
task1_A -> task1_B -> task2_B -> task2_A
 -> task3_A -> task3_B -> task4_B -> task4_A
```

每cell创建独立账本、作用域及输出目录，无跨组答案缓存、预算借用或resume。模型和分配策略一致；A/B各4cell，费用全量累计。每cell都走同样三模型Stage A和执行前预检，因此模型核验/加载开销公平记录，但会比两组整块运行多重复加载。实际加载次数及服务/墙钟分列；交错缓解时间混杂，不证明墙钟差全由方法造成。

旧ab_acceptance整组入口保留，不作为v2执行入口。原v1源码hash自然因本轮授权修改失效，禁止按旧冻结包再启动。

## 6. 重新计算预算（仅建议，未授权）

Token与请求包络保持相同：每题每组最多12请求/34000 Token；生成修复审查20000、执行验证恢复14000。最坏定义路径10请求/33536 Token：规划3840、一次修复6912、两次审查8960、五个节点11520、一次恢复2304。输入上限plan3072/repair6144/review4096/node和recovery2048；输出768/768/384/256/256。程序评分0请求，无HTTP重试；未知失败预留不释放。

| 范围 | 请求硬限 | Token硬限 | 墙钟硬限 |
|---|---:|---:|---:|
| 每task-arm cell | 12 | 34000 | 4000秒 |
| 每组四cell | 48 | 136000 | 16000秒累计cell信封 |
| 两组 | 96 | 272000 | 32400秒（含400秒编排余量） |

每cell最多3次Stage A激活+7次执行激活，加载/卸载上限320秒/次；Stage A预留960秒，Stage B 7×320+10×30+30清理=2570秒；合计3530，cell4000剩470用于审计/CPU等。八cell最坏80次激活、80次已定义路径请求，服务与清理28240秒；硬上限32400秒（9小时），不是预计实际时长。每次Stage A后重新检查剩余墙钟，无法满足则停止。请求/Token总额与v1相同，但交错版墙钟重新建议上限，不擅自沿用或扩大旧授权。

cell之间不借用任何余量，比仅两组独立更严格；每组4×caps确保48/136000上限，总额96/272000。旧失败1次请求/2496未知预留另列历史，不从原信封中释放或清零；新信封是待批准的独立信封，不是旧运行免费重试。

输入随着候选和节点输出增长，超过硬边界必须派发前拒绝，不能为完成而截断。包络保证有界派发，不保证每题成功。货币单价仍未冻结，不报告美元。

## 7. 复现与剩余阻塞

离线已通过：

```bash
/root/autodl-tmp/r3_venv/bin/python -m collab_scheduler_v1.typed_dag_v1.ab_interleaved \
 --packet collab_scheduler_v1/typed_dag_v1/ab_preparation_v2
```

将来独立授权、核验hash/回归/GPU空闲后才可使用：

```bash
/root/autodl-tmp/r3_venv/bin/python -u -m collab_scheduler_v1.typed_dag_v1.ab_interleaved \
 --packet collab_scheduler_v1/typed_dag_v1/ab_preparation_v2 \
 --output collab_scheduler_v1/typed_dag_v1/stage3_ab_real_02 --execute
```

当前离线Schema兼容阻塞已解除；真实HTTPround-trip仍未验证，真实Goal IR生成能力、异构节点完整执行和最终正确性都未由本轮证明。新的资源授权仍是执行前置条件。不因“编译通过”保证所有服务请求成功，也不把新模式的额外声明当作算法性能结果。

未启动真实模型/HTTP，未自动提交或推送Git，完成后停止等待确认。
