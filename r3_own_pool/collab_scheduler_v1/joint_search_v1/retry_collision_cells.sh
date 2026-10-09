#!/bin/bash
# Wait for the active campaign driver (other session) to exit, then:
#   1. settle the reservation stuck by the driver collision (random_20261009)
#      with its actual spend (zero dispatches -> 0/0);
#   2. rerun the two cells lost to the collision
#      (proposed_state_incremental_20261009, random_20261009) — the hardened
#      driver's infra-retry routes them into fresh retry campaign dirs.
# No budget expansion: the driver enforces the cross-directory request ceiling;
# per-session caps unchanged.
cd /root/r3_own_pool
DRIVER_PID=${1:-74546}
while kill -0 "$DRIVER_PID" 2>/dev/null; do sleep 60; done
sleep 60  # let cleanup release locks
python3 - <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, '/root/r3_own_pool')
from collab_scheduler_v1.joint_search_v1.runtime import CampaignQuota
c2 = Path('collab_scheduler_v1/joint_search_v1/formal_campaign_v2')
caps = json.loads(Path('collab_scheduler_v1/joint_search_v1/SEARCH_BUDGET_V1.json').read_text())['campaign_caps']
sha = json.loads(Path('collab_scheduler_v1/joint_search_v1/FORMAL_LAUNCH_V2.json').read_text())['protocol_sha256']
try:
    q = CampaignQuota(c2, caps, sha)
    q.settle('random_20261009',
             dict(new_request_attempts=0, new_total_tokens=0, wall_seconds=0),
             'INCOMPLETE_DRIVER_COLLISION')
    q.close()
    print('settled stuck random_20261009 reservation: 0/0')
except Exception as e:
    print('settle skipped:', e)
EOF
JOINT_SEARCH_EXECUTE=1 python3 -u -m collab_scheduler_v1.joint_search_v1.formal_launch \
  --run \
  --launch collab_scheduler_v1/joint_search_v1/FORMAL_LAUNCH_V2.json \
  --admission collab_scheduler_v1/joint_search_v1/FORMAL_ADMISSION_V2.json \
  --only proposed_state_incremental_20261009,random_20261009 \
  >> collab_scheduler_v1/joint_search_v1/formal_campaign_v2/RETRY_DRIVER.log 2>&1
