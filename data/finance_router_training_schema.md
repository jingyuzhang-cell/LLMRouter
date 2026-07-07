# 金融路由训练数据统一格式

这个文件用于规范后续 FinQA、TAT-QA、FinanceBench、FinEval、FinReflectKG 等数据集如何转成路由器训练样本。

本项目训练的重点不是重新预训练大模型，而是训练“路由器”：让系统知道不同金融任务应该调用哪个模型。

## JSONL 样本格式

每一行是一条金融任务样本：

```json
{
  "id": "finqa_000001",
  "domain": "finance",
  "dataset": "FinQA",
  "task_type": "financial_numerical_reasoning",
  "question": "What was the percentage change in revenue from 2018 to 2019?",
  "context": "The company reported revenue of ...",
  "table": [],
  "gold_answer": "12.5%",
  "evidence": [],
  "risk_level": "medium",
  "requires_calculation": true,
  "requires_table_reasoning": true,
  "requires_kg_reasoning": false,
  "requires_verification": true,
  "model_results": {
    "deepseek-chat": {
      "answer": "",
      "quality": null,
      "latency_ms": null,
      "input_tokens": null,
      "output_tokens": null,
      "cost_usd": null,
      "success": null,
      "error": null
    }
  },
  "best_model": null
}
```

## 字段说明

- `domain`：领域。金融实验统一写 `finance`。
- `dataset`：来源数据集，例如 `FinQA`、`TAT-QA`、`FinanceBench`。
- `task_type`：任务类型，例如金融数值推理、表格文本推理、金融开放问答、金融知识图谱多跳问答。
- `gold_answer`：标准答案。FinQA 和 TAT-QA 可以直接用于自动评估。
- `evidence`：证据句、表格位置或文档片段。FinanceBench 和 TAT-QA 更需要这个字段。
- `risk_level`：`low`、`medium`、`high`。金融合规、审计风险、监管类任务通常设为 `high`。
- `requires_calculation`：是否需要数值计算。
- `requires_table_reasoning`：是否需要表格理解。
- `requires_kg_reasoning`：是否需要知识图谱、多跳关系或实体路径推理。
- `model_results`：不同模型真实回答后的表现记录。
- `best_model`：根据质量、成本、延迟和可靠性综合评估后得到的最优模型标签，用于训练路由器。

## 分阶段接入建议

第一阶段：FinQA + TAT-QA

- 目标：跑通自动评估闭环。
- 评价：标准答案匹配、数值误差、真实 token 成本、真实延迟、失败率。

第二阶段：FinanceBench + FinEval

- 目标：扩展到真实财报开放问答和中文金融知识评估。
- 评价：LLM 裁判 + 证据匹配 + 少量人工复核。

第三阶段：FinReflectKG / FinRED

- 目标：引入金融知识图谱推理和关系抽取。
- 评价：实体关系命中率、多跳路径正确率、回答质量、检索证据覆盖率。

## 路由训练标签生成

每个模型都回答同一条样本后，记录：

```text
quality, cost, latency, reliability
```

然后用当前的金融风险自适应非线性效用函数生成候选模型排序：

```text
U = Q^alpha * R^beta * exp(-gamma*C) * exp(-delta*L)
```

得分最高的模型写入 `best_model`，候选排序写入 `model_results`。

