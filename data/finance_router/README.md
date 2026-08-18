# Finance Router Dataset Pipeline

This directory stores finance-domain routing data for the LLMRouter experiment.

The goal is not to pretrain a large language model. The goal is to train and evaluate the router:

```text
finance question + task features + model results -> best model
```

## Directory Layout

```text
data/finance_router/
  raw/
    finqa/
    tatqa/
  samples/
    finance_seed.jsonl
  standardized/
    finance_router_tasks.jsonl
  routing/
    finance_router_train.jsonl
    finance_router_train.csv
```

## Recommended Workflow

1. Put raw FinQA and TAT-QA files under `raw/`.
2. Run `scripts/prepare_finance_router_data.py` to convert them into a unified JSONL format.
3. Run real model calls from the experiment page, or fill `model_results` by batch evaluation.
4. Run `scripts/build_finance_router_training.py` to generate router training labels.
5. Use the generated `routing/finance_router_train.jsonl` to train or evaluate GraphRouter, Bandit, or nonlinear multi-objective routing.

## Commands

Validate the full pipeline without external API calls:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-finance-router-pipeline.ps1
```

Run real model calls on a small sample:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-finance-router-pipeline.ps1 -RealCall -Limit 4
```

Convert raw FinQA:

```powershell
python scripts\prepare_finance_router_data.py --source finqa --input data\finance_router\raw\finqa\train.json
```

Append raw TAT-QA:

```powershell
python scripts\prepare_finance_router_data.py --source tatqa --input data\finance_router\raw\tatqa\train.json --append
```

Run model evaluation after conversion:

```powershell
python scripts\run_finance_model_evaluation.py --limit 20 --models deepseek-chat qwen-plus gemini-2.5-flash glm-5.2
```

Build router labels from evaluated results:

```powershell
python scripts\build_finance_router_training.py --input data\finance_router\standardized\finance_router_tasks.with_results.jsonl
```

## Dataset Stages

Stage 1: FinQA + TAT-QA

- Financial numerical reasoning.
- Table-text reasoning.
- Easy to evaluate automatically with gold answers.

Stage 2: FinanceBench + FinEval

- Open financial QA.
- Chinese financial knowledge.
- Needs LLM judge and sampled human review.

Stage 3: FinReflectKG / FinRED

- Financial KG multi-hop reasoning.
- Relation extraction and graph construction.
- Best for advanced GraphRouter experiments.
