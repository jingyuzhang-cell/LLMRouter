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
echo "credentials loaded (values not shown); launching RQ_DYN_V1 (HomDS vs DYN; 20 execs; 200 calls / 600k tokens / CNY 6)"
python3 -u rq_dyn_v1_runner.py --real --config rq_dyn_v1_config.json --out rq_dyn_v1_runs
