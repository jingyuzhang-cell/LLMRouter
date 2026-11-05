# 三臂动态恢复实验预注册（QP9：Static / R-only / R+π）

**状态**：预注册完成，等待授权。

---

## 1. 科学问题

> 当 DAG 节点出现可观测的执行异常时，动态切换到能力互补模型（R+π），是否比使用原模型重新执行（R-only）获得更好的终端质量？

**关键对比**：C(R+π) vs B(R-only)——分离异构模型切换的增量收益与普通重试的收益。

## 2. 跨窗口核查结果

未发现已有的 Static/R-only/R+π 三臂实验。QP7 四臂（single/static/dynamic_pi/joint）无 R-only 对照。本实验无重复。

## 3. 任务与数据条件

| 任务 | 严格候选 | 方向 | E 数据来源 | 需补测 |
|---|---:|---|---|---|
| MVR1 | 4 | DS 更好（GLM→DS） | QP8R（两者干净） | 无 |
| KANGMEI | 2 | GLM 更好（DS→GLM） | QP8R（两者干净） | 无 |
| ZEDA | 11 | GLM 更好 | QP4 GLM（干净）+ QP7 DS（污染） | **DS E 补测（4 次）** |
| ZIJING | 6 | GLM 更好 | QP4 GLM（干净）+ QP7 DS（污染） | **DS E 补测（4 次）** |

补测使用与 QP8R Stage 1 相同的修复提示（`E_SYS`，无重复 EVIDENCE_REQ），确保与 MVR1/KANGMEI 的数据条件一致。

## 4. 设计

### 三臂

| 臂 | 初始分配 | 异常触发后 | 恢复范围 |
|---|---|---|---|
| A: Static | DS（全节点） | 不恢复 | — |
| B: R-only | DS | 原模型（DS）重执行 | 异常节点 + 下游 |
| C: R+π | DS | 切换到互补模型重执行 | 异常节点 + 下游（与 B 完全相同） |

**B 与 C 的唯一差异**：恢复时使用的模型（DS vs GLM）。

### 异常触发规则（金盲，预注册冻结）

```python
# E 节点：证据完整率 < 0.5 或解析失败
if evidence_completeness(e_output) < 0.5 or not parseable:
    trigger_recovery(node)

# M 节点：事实保留率 < 0.7
if fact_retention(m_output, e_entries) < 0.7:
    trigger_recovery(node)

# SINK：答案完整率 < 0.6
if answer_completeness(sink_output, contract) < 0.6:
    trigger_recovery(node)
```

### 模型选择规则（基于预测量能力画像）

```python
# 对 E 节点：GLM 在 ZIJING/ZEDA 上历史能力更强 → 切换到 GLM
# 对 E 节点：DS 在 MVR1 上历史能力更强 → 切换到 DS
# 运行时不使用 Gold
model_profile = {
    'MVR1':  {'e': 'DS_better'},   # DS 修复 GLM 的错误
    'KANGMEI': {'e': 'GLM_better'},
    'ZEDA':  {'e': 'GLM_better'},
    'ZIJING': {'e': 'GLM_better'},
}
```

### 恢复范围

- 异常节点本身 + 必要下游节点（m/r/v/p 中受影响的）
- B 和 C 使用完全相同的恢复范围计算

## 5. 终点

| 层级 | 指标 |
|---|---|
| 节点 | 恢复成功率（值正确率） |
| 传播 | 下游事实消费成功率 |
| 终端 | **ΔQ（主）**、关键 TP、错误断言 |
| 资源 | Cost、Makespan |
| 核心 | **C vs B 的 ΔQ 配对差** |

**支持判据**：C vs B 的宏 ΔQ ≥ +0.03 且 ≥2/4 任务非负。
**安全性**：C 的错误断言不高于 B +2。

## 6. 预算

| 项 | 调用 | 费用 |
|---|---:|---:|
| DS E 补测（ZEDA+ZIJING） | 8 | ¥0.04 |
| SINK（3 臂 × 4 任务 × 2 重复） | 24 | ¥0.12 |
| 恢复重执行（估 ~30% 触发） | ~14 | ¥0.08 |
| **合计** | **~46** | **~¥0.24** |
| **硬停止** | **55 次** | **¥0.32** |

## 7. 统计

- 4 任务为统计单元，重复嵌套
- 任务级配对分析（C vs B，C vs A，B vs A）
- 符号翻转检验（n=4 最小 p=0.125）
- 定位为**机制验证**，不宣称普遍有效

## 8. 执行约束

- 运行时无 Gold 泄漏
- B 和 C 恢复范围完全一致
- 不修改冻结评分器
- 不使用 P3 身份绑定
- 负结果如实保留
