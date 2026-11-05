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
[ -n "$DEEPSEEK_API_KEY" ] && [ -n "$QWEN_API_KEY" ] || { echo 'CREDENTIALS MISSING'; exit 3; }
echo "launching RQ_DYN_V3 (36 execs; 400 calls / 1.6M tokens / CNY 6)"
python3 -u rq_dyn_v3_runner.py --real --config rq_dyn_v3_config.json --out rq_dyn_v3_runs
