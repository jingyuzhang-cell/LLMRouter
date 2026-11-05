#!/bin/bash
set -euo pipefail
cd /root/research_outputs/static_pi/stage_d
set -a
DEEPSEEK_API_KEY=$(grep -E '^DEEPSEEK_API_KEY=' /root/.env | head -1 | cut -d= -f2-)
export DEEPSEEK_API_KEY
QWEN_API_KEY=$(grep -E '^QWEN_API_KEY=' /root/.env | head -1 | cut -d= -f2-)
export QWEN_API_KEY
export STAGE_D_REAL_CALLS_AUTHORIZED=1
set +a
python3 -u rq_val_qcl_runner.py --real --config rq_val_qcl_config.json --out rq_val_qcl_runs
