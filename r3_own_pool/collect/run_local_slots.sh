#!/bin/bash
# Detached local-slot pilot collection driver (survives Claude session exits).
# Sequential per protocol: one vLLM server on the GPU at a time.
set -a; source /root/.env; set +a
cd /root/r3_own_pool/collect
echo "=== driver start $(date)" >> logs/driver_local.log
for slot in large medium small; do
  echo "=== [$slot] start $(date)" >> logs/driver_local.log
  /root/autodl-tmp/r3_venv/bin/python runner.py --pilot --collect $slot >> logs/driver_local.log 2>&1
  echo "=== [$slot] exit=$? $(date)" >> logs/driver_local.log
done
echo "=== driver done $(date)" >> logs/driver_local.log
