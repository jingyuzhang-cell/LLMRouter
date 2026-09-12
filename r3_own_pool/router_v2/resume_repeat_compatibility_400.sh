#!/usr/bin/env bash
set -euo pipefail
cd /root/r3_own_pool
/root/autodl-tmp/r3_venv/bin/python -u -m router_v2.collect_repeat_compatibility_400
/root/autodl-tmp/r3_venv/bin/python -u router_v2/run_after_repeat_400.py
