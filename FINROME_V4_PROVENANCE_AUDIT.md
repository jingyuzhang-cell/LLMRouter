# Fin-RoME v4 Provenance Audit Report

**审计日期**: 2026-08-18
**审计对象**: `run_finrome_v4_development_clean.py`
**数据源**: `formal_100_final_result.json`

## 🔴 CRITICAL FINDINGS

### 1. 模型集合严重不一致 ❌

**发现的问题**:
- **代码中使用的模型**: `['deepseek-chat', 'qwen-plus', 'gemini-2.5-flash', 'claude-3-5-sonnet']`
- **真实数据中的模型**: `['deepseek-chat', 'glm-5.2', 'qwen-plus', 'qwen-turbo']`
- **不一致度**: 50% (2/4 模型完全错误)

**后果**:
- v4选择了`claude-3-5-sonnet`，但frozen matrix中根本没有该模型的outcome
- 这导致utility=0的评价结果不可信
- 违反了"candidate_models must exist in frozen matrix"的基本原则

**修复要求**:
```python
# 当前错误代码
self.models = ['deepseek-chat', 'qwen-plus', 'gemini-2.5-flash', 'claude-3-5-sonnet']

# 必须修复为
self.models = ['deepseek-chat', 'glm-5.2', 'qwen-plus', 'qwen-turbo']
```

### 2. Failure定义完全错误 ❌

**发现的问题**:
- **当前定义**: `failed = run.get('ok', True) == False` (API执行失败)
- **实际数据**: 100% 的任务都是`ok=True`，所以当前Failure Rate = 0%
- **真实情况**: 82.75% 的任务`quality < 0.5`，即回答质量失败

**原始样本分析**:
```
样本1: ok=True, error=None, quality=0.06, objective_score=0.0
样本2: ok=True, error=None, quality=0.06, objective_score=0.0
样本3: ok=True, error=None, quality=0.06, objective_score=0.0
```

**错误后果**:
- 所有方法都显示"Failure=0%"，但这是无意义的
- Fin-RoME的安全机制无法验证，因为没有真实的failure事件
- 论文中的"高风险错误回答率"无法评估

**修复要求**:
```python
# 当前错误定义
model_outcomes[task_id].failed[model] = run.get('ok', True) == False

# 必须修复为质量/正确性failure
quality_threshold = 0.5  # 或者其他论文定义的阈值
model_outcomes[task_id].failed[model] = run.get('quality', 0) < quality_threshold

# 或者基于objective_score
model_outcomes[task_id].failed[model] = run.get('objective_score', 0) < 0.3
```

### 3. Utility计算公式错误 ❌

**发现的问题**:
- **项目标准公式**: `U = quality*0.45 + cost*0.2 + latency*0.15 + reliability*0.2`
- **当前实现**: `U = quality / (1 + cost * 100)` (简化公式)

**项目配置**:
```json
"weights": {
  "quality": 0.45,
  "cost": 0.2, 
  "latency": 0.15,
  "reliability": 0.2
}
```

**手工验证**:
```
样本: deepseek-chat, quality=0.06, cost=1.96e-05, latency=1128.17

错误公式: 0.06 / (1 + 0.00196) = 0.059883
正确公式: 0.06*0.45 + normalized(cost)*0.2 + normalized(latency)*0.15 + reliability*0.2
```

**修复要求**:
```python
def compute_utility(self, quality, cost, latency, reliability):
    """按照论文标准公式计算utility"""
    # 需要正则化到[0,1]范围
    normalized_quality = quality
    normalized_cost = 1.0 / (1.0 + cost * 1000)  # 反向正则化
    normalized_latency = 1.0 / (1.0 + latency / 1000)
    normalized_reliability = reliability

    utility = (normalized_quality * 0.45 +
               normalized_cost * 0.2 +
               normalized_latency * 0.15 +
               normalized_reliability * 0.2)

    return utility
```

### 4. Router Scores来源错误 ❌

**发现的问题**:
- **当前实现**: 使用随机生成的router scores
```python
router_scores[task_id] = FrozenRouterScores(
    knn_scores={model: np.random.rand() for model in ...},
    mlp_scores={model: np.random.rand() for model in ...},
    graph_scores={model: np.random.rand() for model in ...}
)
```

- **真实可用**: `case_results`中有真实的`candidate_scores`

**真实Router Score示例**:
```json
{
  "task_id": "finance_dataset_...",
  "selected_model": "qwen-turbo",
  "candidate_scores": {
    "qwen-turbo": 0.5538,
    "deepseek-chat": 0.551,
    "qwen-plus": 0.5148,
    "glm-5.2": 0.3227
  }
}
```

**数据统计**:
- 总case_results: 1200
- 有多个candidate_scores的case: 500
- 有metrics的case: 1200

**修复要求**:
```python
def extract_real_router_scores(self, case_results):
    """从真实的case_results提取router scores"""
    router_scores = {}
    for case in case_results:
        task_id = case['task_id']
        candidate_scores = case.get('candidate_scores', {})

        if candidate_scores:
            # 这里需要推断出KNN/MLP/Graph各自的贡献
            # 目前case_results中只给出了综合score
            # 需要找到原始的OOF router输出文件
            router_scores[task_id] = self.parse_router_scores(candidate_scores)

    return router_scores
```

### 5. Baseline M1/M3/M5不是真实的 ❌

**发现的问题**:
- **当前实现**: 基于简化的router scores计算M1/M3/M5
- **真实情况**: M1应该是项目中正式训练的KNN/MLP/Graph OOF结果

**Case Results统计**:
```python
# 真实项目的模型选择分布
deepseek-chat: 720 (60%)
qwen-plus: 248 (20.7%)
qwen-turbo: 205 (17.1%)
glm-5.2: 27 (2.3%)
```

**修复要求**:
- 不能基于当前实现的结果称为"M1 baseline"
- 必须标记为"prototype baseline"
- 或者找到项目中的真实OOF router输出

## 🟡 MODERATE FINDINGS

### 6. Task Split逻辑可能错误 ⚠️

**发现的问题**:
- task_set包含144个任务
- raw_model_runs只包含100个任务的完整数据
- 当前代码简单取前20个作为calibration，可能不对应真实数据

**数据对应关系**:
- task_set unique task_id: 144
- raw_model_runs unique task_id: 100
- 交集: 100 (真实的金融任务)
- 只在task_set中: 44 (其他类型的任务)

**修复要求**:
```python
# 只使用有完整数据的100个金融任务
real_finance_task_ids = set(run['task_id'] for run in raw_model_runs)
real_finance_tasks = [t for t in task_set if t['id'] in real_finance_task_ids]

# 确保split只在这100个任务中进行
```

### 7. Calibration Task分布不均 ⚠️

**真实100个金融任务的分布**:
- Task types: 100% 都是"专业问答"
- Risk levels: 主要集中在risk=0.62 (75 tasks) 和risk=0.86 (37 tasks)

**后果**:
- Calibration可能无法覆盖不同的任务类型
- 高risk任务的分布不均匀

## 🟢 POSITIVE FINDINGS

### 8. 数据依赖审计通过 ✅

- **leakage_detected**: false
- **suspicious_accesses**: []
- **audit_status**: PASS

这证明在脚本执行层面，预测值与真实结果确实实现了分离。

## 📋 修复优先级

### P0 (Critical - 必须立即修复)
1. ✅ 修复模型集合：使用正确的4个模型
2. ✅ 修复Failure定义：基于quality而非API error
3. ✅ 修复Utility计算：使用正确的weighted sum公式

### P1 (High - 重要)
4. ✅ 修复Router Scores来源：使用真实数据或标记为prototype
5. ✅ 修复Task Split：确保数据对应关系正确

### P2 (Medium)
6. ⚠️ 标记当前baseline为prototype
7. ⚠️ 重新审视calibration task分布

## 🎯 修复后的期望结果

修复后，我们预期看到：
- **真实的Failure Rate**: ~40-80% (取决于quality threshold)
- **真实的Utility分布**: 不再是0或接近0的值
- **真实的Model Selection**: 4个正确模型之间的选择
- **有意义的Risk Gate**: 真实能过滤掉高risk的failure

## 🚫 后续禁止操作

直到所有P0问题修复完成前：
- ❌ 禁止调整任何v4参数
- ❌ 禁止运行test split
- ❌ 禁止基于当前结果进行论文撰写
- ❌ 禁止声称任何"baseline性能"

## 📝 审计结论

**当前状态**: ❌ **NOT READY FOR DEVELOPMENT**

**主要原因**:
1. 模型集合完全不匹配
2. Failure定义无意义
3. Utility计算公式错误
4. Router来源不可信

**建议下一步**:
1. 修复所有P0问题
2. 重新运行development pipeline
3. 验证结果的合理性
4. 只有在所有问题解决后，才开始参数调优

---

**审计员**: Claude (Automated Provenance Audit)
**审计版本**: v1.0
**状态**: 需要修复后重新审计