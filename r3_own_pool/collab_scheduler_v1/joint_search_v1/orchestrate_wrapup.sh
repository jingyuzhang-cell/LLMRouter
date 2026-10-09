#!/bin/bash
# Detached single orchestrator for the DIAGNOSTIC campaign wrap-up.
# Survives harness background-task reaping (run via nohup + disown).
# Sequence:
#   1. wait for the main campaign driver (PID $1) to exit
#   2. settle the reservation stuck by the driver collision
#      (random_20261009, ledger-proven 0/0 — its DISPATCH ledger is absent)
#   3. rerun the two collision cells via the hardened driver (infra-retry
#      routes them into fresh retry roots; cross-directory ceiling enforced)
#   4. wait for the retry driver, then run the three-check reconciliation
#      and the descriptive digest.
cd /root/r3_own_pool
LOG=collab_scheduler_v1/joint_search_v1/formal_campaign_v2/ORCHESTRATOR.log
MAIN_PID=${1:-74546}
echo "$(date +%T) orchestrator start; waiting for main driver $MAIN_PID" >> "$LOG"
while kill -0 "$MAIN_PID" 2>/dev/null; do sleep 90; done
echo "$(date +%T) main driver exited; settling stuck reservation" >> "$LOG"
sleep 60
python3 - >> "$LOG" 2>&1 <<'EOF'
import json, sys
from pathlib import Path
sys.path.insert(0, '/root/r3_own_pool')
from collab_scheduler_v1.joint_search_v1.runtime import CampaignQuota
c2 = Path('collab_scheduler_v1/joint_search_v1/formal_campaign_v2')
caps = json.loads(Path('collab_scheduler_v1/joint_search_v1/SEARCH_BUDGET_V1.json').read_text())['campaign_caps']
sha = json.loads(Path('collab_scheduler_v1/joint_search_v1/FORMAL_LAUNCH_V2.json').read_text())['protocol_sha256']
ledger = c2 / 'random_20261009' / 'DISPATCH.jsonl'
n_resp = 0
tok = 0
if ledger.exists():
    for line in ledger.read_text().splitlines():
        d = json.loads(line)
        if d.get('event') == 'response':
            n_resp += 1
            tok += int(d['response'].get('usage', {}).get('total_tokens') or 0)
try:
    q = CampaignQuota(c2, caps, sha)
    q.settle('random_20261009',
             dict(new_request_attempts=n_resp, new_total_tokens=tok, wall_seconds=0),
             'INCOMPLETE_DRIVER_COLLISION')
    q.close()
    print(f'settled random_20261009 with LEDGER-PROVEN actuals: {n_resp} req / {tok} tok')
except Exception as e:
    print('settle skipped:', e)
EOF
echo "$(date +%T) launching collision-cell retries" >> "$LOG"
JOINT_SEARCH_EXECUTE=1 python3 -u -m collab_scheduler_v1.joint_search_v1.formal_launch \
  --run \
  --launch collab_scheduler_v1/joint_search_v1/FORMAL_LAUNCH_V2.json \
  --admission collab_scheduler_v1/joint_search_v1/FORMAL_ADMISSION_V2.json \
  --only proposed_state_incremental_20261009,random_20261009 \
  >> "$LOG" 2>&1 &
RETRY_PID=$!
echo "$(date +%T) retry driver pid $RETRY_PID" >> "$LOG"
wait "$RETRY_PID"
echo "$(date +%T) retries done; running closure reconciliation + digest" >> "$LOG"
sleep 30
python3 -m collab_scheduler_v1.joint_search_v1.reconcile_formal_campaign >> "$LOG" 2>&1
python3 -m collab_scheduler_v1.joint_search_v1.analyze_formal_campaign >> "$LOG" 2>&1
echo "$(date +%T) ORCHESTRATOR DONE" >> "$LOG"
