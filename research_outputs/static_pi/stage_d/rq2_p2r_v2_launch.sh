#!/bin/bash
# RQ2_P2R_V2 real batch launcher. Credentials passed in-process only; never printed.
set -euo pipefail
cd /root/research_outputs/static_pi/stage_d
set -a
DEEPSEEK_API_KEY=$(grep -E '^DEEPSEEK_API_KEY=' /root/.env | head -1 | cut -d= -f2-)
export DEEPSEEK_API_KEY
export STAGE_D_GLM_KEY=$(python3 -c "
import json
cfg=json.load(open('/root/.zcode/v2/provider_config.json'))
print(next(r['config']['access']['apiKey'] for r in cfg['config']['providerConfigRules']['providerRules'] if r['providerId']=='bigmodel-api'))
")
export STAGE_D_REAL_CALLS_AUTHORIZED=1
set +a
[ -n "$STAGE_D_GLM_KEY" ] && [ -n "$DEEPSEEK_API_KEY" ] || { echo 'CREDENTIALS MISSING'; exit 3; }
echo "credentials loaded (values not shown); launching RQ2_P2R_V2 (B,C; 800 calls / 5M / CNY 40)"
python3 -u rq2_p2r_runner.py --real --arms B,C \
  --config rq2_p2r_v2_config.json --out rq2_p2r_v2_runs
