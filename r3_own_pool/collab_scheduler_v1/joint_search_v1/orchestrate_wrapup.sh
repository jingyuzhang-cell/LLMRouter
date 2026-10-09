#!/bin/bash
# Single shared relay; missing ledger never permits zero settlement.
set -euo pipefail
cd /root/r3_own_pool
LOG=collab_scheduler_v1/joint_search_v1/formal_campaign_v2/ORCHESTRATOR.log
echo "$(date -u +%FT%TZ) Delegating to singleton relay; unknown reservation stays charged" >> "$LOG"
exec bash collab_scheduler_v1/joint_search_v1/retry_collision_cells.sh "${1:-74546}" >> "$LOG" 2>&1
