#!/bin/bash
# Restart the reasoning (DashScope) collection line. Kept as a file so launching
# shells don't contain the runner cmdline (watchdog pgrep false-positives).
cd /root/r3_own_pool/collect
set -a; source /root/.env; set +a
export PYTHONFAULTHANDLER=1
exec /root/autodl-tmp/r3_venv/bin/python -u runner.py --collect reasoning
