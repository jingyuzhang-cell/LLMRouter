# 第三阶段结果：实现完成，真实生成准入未通过

## 实际修改
新增 generation.py（既有 Graph 上的初始生成、语义覆盖审查、0–2 次 LLM 修复、域匹配回退、计量、执行桥接）、generation_schema.py（既有 Graph JSON Schema 与节点输出提示）、test_generation.py（12 项新增测试）、real_generation_smoke.py（隔离真实测试入口）。修改 execution.py 仅补明确输出格式提示；__init__.py 导出生成器；README 记录边界。未改固定48搜索、冻结结果，未提交或推送 GitHub。

## 自动验证
原45项 + 新12项 = 57/57 PASS。记录 STAGE3_TEST_RESULT.json（完整测试日志与源码哈希）。Stub 覆盖3/5节点任意ID生成、严格验证、非法候选修复、语义拒绝、匹配回退并执行、不匹配域停止、缓存零物理开销、预算中止、gold字段派发前拒绝。生成模型不能接收评分答案；分配回调只接收合法Graph。

命令：
```
cd /root/r3_own_pool
python3 -m unittest collab_scheduler_v1.typed_dag_v1.test_typed_dag collab_scheduler_v1.typed_dag_v1.test_generation collab_scheduler_v1.joint_search_v1.test_evaluator collab_scheduler_v1.joint_search_v1.test_runtime -v
```

## 真实测试（开发诊断，不是确认实验）
模型 Qwen2.5-7B-Instruct，temperature=0，两个独立合成公共任务；重复开发测试不增加独立任务数。每轮单独目录、代码/任务协议，最多16请求、65536 Token、1800秒服务预算（模型校验/加载单列），持有GPU独占锁。所有旧失败原件保留。

| 轮次 | 完成的任务测试 | 合法生成图 | 回退 | 执行COMPLETE | 请求尝试 | 已知Token |
|---|---:|---:|---:|---:|---:|---:|
| 01 | 2 | 0 | 2 | 0 | 8 | 7083 |
| 02 | 2 | 0 | 2 | 2 | 12 | 8121 |
| 03 | 0（HTTP500中止） | 未完成 | 无 | 无 | 1 | 未知 |
| 04 | 1 | 0 | 1 | 1 | 6 | 4660 |

全账本共 27 次尝试，已知 19864 Token；HTTP500另保留 8192 Token预留，不声称实际Token为0。不同代码版本不合并为正式合法率；逐版已完成测试的合法生成率均为0，回退率均为100%，样本过小不估计总体率。

真实原始候选见 REAL_CANDIDATE_INVALID.json：LLM自行生成5节点 n1(extraction)、n2(reasoning)、n3(transformation)、n4/n5(verification)，不是固定e1/e2/r/v。候选虽有节点引用，但声明依赖为空、field写成n1.output.facts，n4接口不兼容；验证器拒绝。没有合法真实生成样例，不能用固定回退图冒充。

02轮回退完成的总收入题输出20；差值题也输出20（题面7→11，应求4），因此COMPLETE只是所有最终输出产生，不代表任务正确。01轮输出合同不符阻断后继。03轮服务端schema请求HTTP500立即中止并保留派发预留，04轮用兼容JSON对象传输，仍未获得合法图。

生成/修复/回退逐阶段事件、Token、物理请求、缓存标记、服务/墙钟落在各目录GENERATION_EVENTS/GENERATED_GRAPHS及DISPATCH/TRAJECTORY；完整字段在STAGE3_REAL_SUMMARY.json。每个完成轮次RESULTS含加载和总体墙钟。新版generate_and_execute增加生成在内的pipeline_accounting；这些汇总字段没有反写旧轮次结果。

## 闭环及下一关口
Stub：用户公共任务→LLM接口候选→现有验证器→覆盖审查→类型执行器，已完成（3/5节点）。真实：公共任务→LLM非法候选→有限修复失败→匹配固定回退→执行，已完成；真正的合法LLM生成图→真实执行闭环尚未证明。语义审查仅模型启发式，不能保证覆盖/正确性；当前真实候选在结构阶段已失败，不能宣称语义审查真实验收通过。

下一关口仅是改善合同约束生成及接口修复，在至少一个合法生成图上完成真实执行验证。不要启动结构搜索或Pareto联合优化，不将本次结果称为生成DAG优于固定DAG的证据。当前执行仍串行，真实模型分配仅统一medium的机械验证，并非异构分配收益实验。
