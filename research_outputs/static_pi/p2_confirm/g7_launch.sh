#!/bin/bash
set -a
DEEPSEEK_API_KEY=$(grep -E '^DEEPSEEK_API_KEY=' /root/.env | head -1 | cut -d= -f2-)
export DEEPSEEK_API_KEY
# 操作员2026-11-11提供的GLM-Flash资源包密钥（同模型/端点/参数，仅凭据变更）
export STAGE_D_GLM_KEY=$(cat /root/.g7_glm_key)
export G7_GO=1
set +a
[ -n "$STAGE_D_GLM_KEY" ] && [ -n "$DEEPSEEK_API_KEY" ] || { echo 'CREDENTIALS MISSING'; exit 3; }
echo "credentials loaded (values not shown); launching G7 confirmatory run (80 blocks / 1000 calls / 8M / CNY 15)"
exec python3 g7_runner.py --real
