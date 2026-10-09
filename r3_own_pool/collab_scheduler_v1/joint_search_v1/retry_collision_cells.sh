#!/bin/bash
# Keep unknown Random reservation charged. Never settle absent-ledger spend as zero.
set -euo pipefail
cd /root/r3_own_pool
exec 9>collab_scheduler_v1/joint_search_v1/collision_relay.lock
flock -n 9 || exit 0
DRIVER_PID=${1:-74546}
while kill -0 "$DRIVER_PID" 2>/dev/null; do
 echo "$(date -u +%FT%TZ) WAITING: main driver PID=$DRIVER_PID is alive"
 sleep 30
done
echo "$(date -u +%FT%TZ) Main driver exited; checking admission and budget for collision retries"
# Existing driver enforces global request headroom including unresolved reservation.
JOINT_SEARCH_EXECUTE=1 python3 -u -m collab_scheduler_v1.joint_search_v1.formal_launch \
 --run --launch collab_scheduler_v1/joint_search_v1/FORMAL_LAUNCH_V2.json \
 --admission collab_scheduler_v1/joint_search_v1/FORMAL_ADMISSION_V2.json \
 --only proposed_state_incremental_20261009,random_20261009
python3 -m collab_scheduler_v1.joint_search_v1.reconcile_formal_campaign
python3 -m collab_scheduler_v1.joint_search_v1.audit_campaign_provenance
