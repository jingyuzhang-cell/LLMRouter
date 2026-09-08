#!/bin/bash
# Detached FULL 5000x4 local-slot collection driver (survives Claude session exits).
# Sequential per protocol; reasoning slot runs separately via DashScope (no GPU).
set -a; source /root/.env; set +a
cd /root/r3_own_pool/collect
# clear any orphaned engine core from a previous run
for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do
  if ! ps -o ppid= -p $pid 2>/dev/null | grep -qv " 1$"; then kill -9 $pid 2>/dev/null; fi
done
sleep 3
echo "=== full driver start $(date)" >> logs/driver_full.log
for slot in large medium small; do
  echo "=== [full:$slot] start $(date)" >> logs/driver_full.log
  /root/autodl-tmp/r3_venv/bin/python runner.py --collect $slot >> logs/driver_full.log 2>&1
  echo "=== [full:$slot] exit=$? $(date)" >> logs/driver_full.log
done
echo "=== full driver done $(date)" >> logs/driver_full.log
