#!/bin/bash
# RQ3_STAT_V1 real batch launcher. Credentials passed in-process only; never printed.
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
echo "credentials loaded (values not shown); launching RQ3_STAT_V1 (HomDS vs HetQR; 40 execs; 280 calls / 800k tokens / CNY 8)"
python3 -u rq3_stat_v1_runner.py --real --config rq3_stat_v1_config.json --out rq3_stat_v1_runs
