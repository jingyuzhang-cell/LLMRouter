# KQA Pro API routing workflow

This workflow evaluates several API models on the same KQA Pro questions and
trains an MLP router to select a model for each new question. It is routing
label generation and router training, not language-model pretraining.

## Environment

Keep provider keys in the repository root `.env`. The scripts never write API
keys to result files. Use the `kqapro` Conda environment for all commands:

```bash
cd /root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main
```

## Collect matched model results

Start with a small matched sample. Re-running the command resumes from JSONL
checkpoints and skips valid results.

```bash
conda run -n kqapro python scripts/kqapro_api_routing.py \
  --per-provider 500 \
  --providers deepseek qwen zhipu
```

To collect the complete 94,376-example KQA Pro training split from DeepSeek,
use a separate output directory so it cannot mix with validation results:

```bash
screen -S kqapro_deepseek_train
conda run -n kqapro python scripts/kqapro_api_routing.py \
  --data data/kqapro/KQAPro_Baselines/dataset/train.json \
  --split train \
  --output-dir data/kqapro/api_routing_train \
  --per-provider 94376 \
  --providers deepseek
```

Detach from `screen` with `Ctrl-A`, then `D`. This command performs 94,376
billable API requests. Check provider quota and estimated cost before starting.
A single provider can be collected first, but router training requires matched
results from at least two providers on the same questions.

## Build labels and embeddings

The builder uses the intersection of valid task IDs from all selected providers,
creates a deterministic 80/20 split, and uses correctness as the main score.
Measured latency only breaks ties between equally correct models.

```bash
conda run -n kqapro python scripts/kqapro_build_api_router_data.py \
  --providers deepseek qwen zhipu
```

Generated data is written under `data/kqapro/api_router_data/`, and the training
configuration is `configs/model_config_train/mlprouter_kqapro_api.yaml`.

## Train the router

```bash
conda run -n kqapro python -m llmrouter.cli.router_train \
  --router mlprouter \
  --config configs/model_config_train/mlprouter_kqapro_api.yaml \
  --device cuda
```

The trained state dictionary is stored at
`llmrouter/saved_models/mlprouter/kqapro_api_mlprouter.pkl`.
