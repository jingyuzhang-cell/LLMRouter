#!/bin/bash
set -a
DEEPSEEK_API_KEY=$(grep -E '^DEEPSEEK_API_KEY=' /root/.env | head -1 | cut -d= -f2-)
export DEEPSEEK_API_KEY
export STAGE_D_GLM_KEY=$(python3 -c "
import json
cfg=json.load(open('/root/.zcode/v2/provider_config.json'))
print(next(r['config']['access']['apiKey'] for r in cfg['config']['providerConfigRules']['providerRules'] if r['providerId']=='bigmodel-api'))
")
export G7_GO=1
set +a
[ -n "$STAGE_D_GLM_KEY" ] && [ -n "$DEEPSEEK_API_KEY" ] || { echo 'CREDENTIALS MISSING'; exit 3; }
echo "credentials loaded (values not shown); launching G7 confirmatory run (80 blocks / 1000 calls / 8M / CNY 15)"
exec python3 g7_runner.py --real
