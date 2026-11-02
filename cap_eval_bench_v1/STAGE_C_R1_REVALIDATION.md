# STAGE_C_R1_REVALIDATION — 零调用复验报告

## 一、原始文件恢复结果

| 文件 | 恢复方式 | 说明 |
|---|---|---|
| stage_c_r1_engine.py | **RECONSTRUCTED**（非原始） | 原始文件丢失；从 `.pyc` 字节码确认结构后重建 |
| test_stage_c_r1_acceptance.py | **REBUILT**（非原始） | 原始文件丢失；按八项验收需求重建 |

**恢复依据**：
- `__pycache__/stage_c_r1_engine.cpython-312.pyc` 存在（21,879 字节），确认原始模块的确存在且被执行过
- .pyc 反编译确认了全部类/函数名和参数签名（FailureType/NodeState/ResourceSlots/DAGExecutionState/FakeModelAdapter/6 decide函数/ARM_DECIDERS/execute_dag）
- 测试文件的 .pyc 不存在，无法从字节码恢复
- **重建代码不冒充原始代码**

## 二、八项验收结果（40 PASS / 0 FAIL）

| 验收项 | 结果 | 关键证据 |
|---|---|---|
| 1. 六臂接线 | ✅ | 每臂独立决策函数，唯一 rationale |
| 2. 行为分化 | ✅ | **3 个决策组**（≥3 要求）；π-only 用 Flash |
| 3. Transport 恢复 | ✅ | 5/6 臂 COMPLETE；Static 如实不同 |
| 4. Makespan | ✅ | 测量正确；资源约束追踪 |
| 5. 健康缓存 | ✅ | n1/n2 从未重复执行（6/6 臂） |
| 6. 合同一致性 | ✅ | 全部节点合法；含负向断言（无效节点） |
| 7. 异构模型 | ✅ | GLM + Flash 均被使用 |
| 8. 预算/追溯 | ✅ | 含负向断言（低预算停止） |

**负向断言**（原始报告缺失的）：
- Static 不恢复失败节点 ✅
- 非全部臂状态相同 ✅
- 无效节点类型被忽略 ✅
- 低预算导致停止 ✅

## 三、跨进程可复现性

- ✅ 文件真实存在于磁盘（stage_c_r1_engine.py 12,481B / test 7,254B）
- ✅ 从 /tmp 目录（非项目目录）重新运行，结果一致（40/0）
- ✅ SHA256 已记录（engine: 43f32433fbf5b77f...）
- ✅ 测试结果保存为 r1_test_results.json

## 四、决策维度可辨识性

| 维度 | 可辨识 | 证据 |
|---|---|---|
| R | ✅ | 2 种恢复集（空 vs {n3}） |
| π | ✅ | **7 种不同分配方案** |
| Z | ⚠️ | 仅 1 种操作（IDENTITY）在当前测试中；SC-E3 需 factcheck 异常才能触发 ADD_VERIFY |

## 五、结论

**Stage-C-R1 工程验收：PASS（有条件）**

条件：
1. 此 PASS 基于重建代码，非原始 39/39 的复现
2. Z 维度在当前标准测试中仅 IDENTITY；需 SC-E3 场景验证 ADD_VERIFY
3. 3 个决策组来自策略逻辑差异（Static 不恢复 / SimpleDyn+R-only+Joint 用 GLM / π-only 用 Flash）

**Stage-C-R2：可以继续准入流程**（等待授权）
