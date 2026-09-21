# P3 MBPP（代码域）协议草案（基于 schema 审计，未冻结）

状态：草案。零调用、零 GPU。推荐第二跨域选 MBPP（而非 HumanEval）。

## 数据
- 来源：bench-release mbpp/test（974 题，`origin_query` = 任务描述，prompt 内嵌 3 条 `assert` 单元测试，index 1..974 唯一）。
- 源文件 sha256：`e80e9a5a...bb11ed`。
- `ground_truth`（参考解）在 release 中为 NULL——可接受且更干净：运行时本来就禁止读 gold，离线评分 = 单元测试通过率，连泄漏 gold 的可能性都不存在。
- 与历史实验重叠：0（精确交集）。
- 清洗规则（选择时确定性排除）：
  - 4 对近似重复题（indices 175/810、199/455、410/680、700/920）只保留 hash 序靠前者；
  - 2 题（idx 64、609）的测试引用了 prompt 中未定义的辅助函数（Pair、lobb_num 等），排除。

## 测试用例（部署可得的失败信号——本域最强项）
- 2,922 条 assert 全部通过 Python AST 解析（0 不可解析），平均 3.0 条/题，每题 ≥2 条。
- 提取规则：从 prompt 中按行正则 `^assert .+$` 提取（与模型看到的 prompt 完全一致）。
- 执行：sandbox 子进程（timeout，禁网，只运行生成函数 + 测试），全部 assert 通过 = 正确。
- 失败信号（动态触发只能使用）：**syntax error / runtime error / test pass-fail / 输出格式检查**。
- 禁止：运行时读取 reference solution / gold（本 release 中根本不存在，杜绝泄漏）。

## 建议 DAG（自然四节点链 + 修复环）
```
description ──► plan ──► implement ──► execute(tests) ──► 结果
                                 ▲              │
                                 └── repair ◄────┘（仅失败时，有界）
```
- **plan**（模型可分配）：复述需求、设计函数签名与算法。输出 JSON。
- **implement**（模型可分配）：编写 Python 函数（可为 coder 主选）。
- **execute**（确定性，零调用）：在沙箱里运行提取的测试。这是三域里唯一真正确定性的正确性信号。
- **repair**（动态专属，有界次数）：仅把错误信息与失败断言喂回生成模型，禁止 gold；预算按财务域规则（1.2×静态消耗）封顶。

## 六臂含义（本域）
- Always Best / Query Router / Type Router：节点级与整题级基线，含义清晰。
- Static DAG：plan→implement→execute + 局部回退（同节点换模型一次）。
- Dynamic DAG：测试失败触发的选择性修复——**触发信号天然部署可得且确定性**，是三域中最有说服力的"选择性动态"复现点。
- Oracle：有限候选（已执行节点-模型矩阵）内的上界。

## 调用量估算（100 题、共享缓存六臂）
- plan/implement × 3 模型 × 100 ≈ 600；repair 有界循环 ≈ +100~300；总计约 **700–1,000 次**。
- 全部本地 vLLM（medium/large/coder，checkpoint 与主链一致，SHA 钉死）。

## 待用户决定
- 是否选 MBPP（本审计建议：是，HumanEval 的官方测试不在 release 内、需外取数据）；
- 题数（建议 100 fresh，sha256('xcode:'+index) 升序）；
- 是否六臂全跑（本域建议全跑：动态信号最强）。
