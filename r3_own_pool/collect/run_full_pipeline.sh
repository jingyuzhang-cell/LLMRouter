#!/bin/bash
# Autonomous full pipeline: waits for BOTH collection lines, then runs
# metrics -> judge -> freeze -> validate -> A1-A3 analysis -> router train/eval.
# Detached; survives session exits. Logs to r3_own_pool/collect/logs/pipeline.log.
set -a; source /root/.env; set +a
cd /root/r3_own_pool/collect
LOG=logs/pipeline.log
PY=/root/autodl-tmp/llmrouterbench_r2_venv/bin/python
say() { echo "[$(date +%H:%M:%S)] $*" >> $LOG; }

say "pipeline watcher started"

# stage 0: wait for local driver done + reasoning full quota
while true; do
  local_done=$(grep -c "full driver done" logs/driver_full.log 2>/dev/null || echo 0)
  n_reason=$(python3 - <<'EOF'
import json
from collections import Counter
try:
    rows=[json.loads(l) for l in open('/root/r3_own_pool/data/raw/reasoning.jsonl')]
    ok=len({r['query_id'] for r in rows if r['status']=='ok'})
    print(ok)
except Exception:
    print(0)
EOF
)
  if [ "$local_done" -ge 1 ] && [ "$n_reason" -ge 4999 ]; then
    say "collection complete (local driver done; reasoning ok=$n_reason)"
    break
  fi
  sleep 300
done

# stage 1: assemble + auto metrics (CPU)
say "stage1 assemble+metrics"
python3 runner.py --assemble --metrics >> $LOG 2>&1
say "stage1 exit=$?"

# stage 2: arenahard judge (API, ~2-3h for ~2800 slots)
say "stage2 judge"
python3 judge.py >> $LOG 2>&1
say "stage2 exit=$?"

# stage 3: freeze full
say "stage3 freeze"
python3 freeze.py --version full_v1 >> $LOG 2>&1
say "stage3 exit=$?"

# stage 4: validator B-level
say "stage4 validate"
python3 validate_dataset.py ../data/frozen/full_v1.jsonl --split ../data/frozen/split.json \
  --require-trainability >> $LOG 2>&1
say "stage4 exit=$?"

# stage 5: A1-A3 pre-registered analysis on judged pool
say "stage5 A1-A3"
cd /root/r3_own_pool
python3 analyze_full.py --input data/judged.jsonl --tag full >> $LOG 2>&1
say "stage5 exit=$?"

# stage 6: router training + baselines (GPU is free by now)
say "stage6 router"
$PY train_router.py --frozen full_v1 >> $LOG 2>&1
say "stage6 exit=$?"

say "PIPELINE COMPLETE - see FULL_OPPORTUNITY.md and ROUTER_RESULT_full_v1.json"

# stage 7: judge reliability audit (user-flagged top risk: label noise)
say "stage7 judge reliability"
python3 judge_reliability.py --sample 200 >> $LOG 2>&1
say "stage7 exit=$?"
say "PIPELINE COMPLETE v2 (incl. reliability audit)"
