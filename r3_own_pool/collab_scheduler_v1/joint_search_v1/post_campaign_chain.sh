#!/bin/bash
# Post-campaign chain: wait until no formal_launch driver is running and the
# retry driver has finished, then run the zero-call campaign analysis.
cd /root/r3_own_pool
LOG=collab_scheduler_v1/joint_search_v1/formal_campaign_v2/RETRY_DRIVER.log
# phase 1: main driver alive?
while pgrep -f "formal_launch --run" > /dev/null 2>&1; do sleep 120; done
# phase 2: retry waiter may still be mid-run (it launches its own formal_launch);
# wait until it has appeared AND finished, or 20 min passed without appearing
for i in $(seq 1 20); do
  [ -f "$LOG" ] && break
  sleep 60
done
while pgrep -f "formal_launch --run" > /dev/null 2>&1; do sleep 120; done
sleep 30
python3 -m collab_scheduler_v1.joint_search_v1.analyze_formal_campaign \
  >> "$LOG.analysis" 2>&1
