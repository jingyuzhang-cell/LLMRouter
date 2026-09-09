#!/bin/bash
# R3 collection one-shot dashboard. Also runs detached to refresh PROGRESS.md.
R=/root/r3_own_pool
TARGET=4999

count_ok() {  # unique ok query_ids per slot
  python3 - "$1" <<'EOF'
import json, sys
try:
    seen = {}
    for l in open(f'/root/r3_own_pool/data/raw/{sys.argv[1]}.jsonl'):
        if not l.strip(): continue
        r = json.loads(l)
        q = r['query_id']
        if q not in seen or (seen[q] != 'ok' and r['status'] == 'ok'):
            seen[q] = r['status']
    print(sum(1 for v in seen.values() if v == 'ok'))
except FileNotFoundError:
    print(0)
EOF
}

echo "=== R3 5000x4 collection status  ($(date '+%H:%M:%S')) ==="
total_remaining=0
declare -A RATE
for slot in large medium small reasoning; do
  n=$(count_ok $slot)
  state=/tmp/r3_cnt_$slot
  now=$(date +%s)
  if [ -f "$state" ]; then
    read pc pt < $state
    now=$(date +%s)
    rate=$(python3 -c "dt=$now-$pt; print(round(($n-$pc)*60/dt,1) if dt>=45 else 0)")
  else
    rate=0
  fi
  echo "$n $now" > $state; echo "$rate" > /tmp/r3_rate_$slot
  rem=$((TARGET - n)); [ $rem -lt 0 ] && rem=0
  total_remaining=$((total_remaining + rem))
  eta="-"
  if [ "$slot" = "reasoning" ]; then
    # API slot runs in parallel with local slots
    if python3 -c "exit(0 if $rate > 0.1 else 1)"; then
      eta="$(python3 -c "m=$rem/$rate; print(f'{int(m//60)}h{int(m%60):02d}m' if m>=60 else f'{int(m)}m')")"
    fi
    echo "reasoning (R1 API): $n/$TARGET  [$rate/min]  ETA $eta"
  else
    echo "$slot (local):      $n/$TARGET  [$rate/min]"
  fi
done

drv=$(grep -E "^\=== " $R/collect/logs/driver_full.log 2>/dev/null | tail -1 | sed 's/=== //')
echo "local driver: $drv"
gpu=$(nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader 2>/dev/null)
echo "gpu: $gpu"

pip=$(tail -1 $R/collect/logs/pipeline.log 2>/dev/null)
echo "pipeline: $pip"

# local line ETA: remaining of current local slot + queued slots at ~40/min
loc_rem=0
for slot in large medium small; do
  n=$(cat /tmp/r3_cnt_$slot 2>/dev/null | awk '{print $1}')
  loc_rem=$((loc_rem + TARGET - ${n:-0}))
done
[ $loc_rem -lt 0 ] && loc_rem=0
python3 - "$loc_rem" <<'EOF'
import sys
m = int(sys.argv[1]) / 40  # observed vLLM rate ~40/min
print(f"local line ETA: ~{int(m//60)}h{int(m%60):02d}m for all 3 slots" if m > 0 else "local line: done")
EOF
echo ""
echo "next after reasoning completes: v2 scoring/freeze/fit path (router_v2; legacy auto-pipeline retired)"
