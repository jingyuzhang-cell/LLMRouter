#!/bin/bash
# Overnight watchdog: keep both collection lines alive until the pipeline takes over.
# - reasoning: restart if process dead AND file stale
# - local driver: restart if process dead AND local slots incomplete
# - progress daemon: restart if dead
# Exits when all 4 slots are complete (ok-unique >= 4990 each) or pipeline stage1 seen.
R=/root/r3_own_pool
LOG=$R/collect/logs/watchdog.log
say() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> $LOG; }
say "watchdog started"

ok_count() {
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
    print(len(seen))  # any terminal row (ok/truncated/failed) counts as collected
except FileNotFoundError:
    print(0)
EOF
}

while true; do
  # completion check
  done_all=1
  for s in large medium small reasoning; do
    n=$(ok_count $s)
    [ "$n" -lt 4990 ] && done_all=0
  done
  if [ "$done_all" = "1" ]; then
    say "all 4 slots complete - watchdog exiting"
    exit 0
  fi
  if grep -q "stage1" $R/collect/logs/pipeline.log 2>/dev/null; then
    say "pipeline stage1 seen - watchdog exiting"
    exit 0
  fi

  # reasoning line
  if ! pgrep -f "runner.py --collect reasoning" >/dev/null; then
    say "reasoning runner DEAD - restarting"
    cd $R/collect
    set -a; source /root/.env; set +a
    setsid nohup /root/autodl-tmp/r3_venv/bin/python runner.py --collect reasoning \
      </dev/null >>logs/reasoning_full.log 2>&1 &
    disown
  fi

  # local line (one GPU owner; only restart if slots incomplete)
  loc_incomplete=0
  for s in large medium small; do
    n=$(cat /tmp/r3_cnt_$s 2>/dev/null | awk '{print $1}')
    [ "${n:-0}" -lt 4990 ] && loc_incomplete=1
  done
  if [ "$loc_incomplete" = "1" ] && ! pgrep -f "run_full_local.sh" >/dev/null; then
    say "local driver DEAD with slots incomplete - restarting"
    for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do
      ppid=$(ps -o ppid= -p $pid 2>/dev/null | tr -d ' ')
      [ "$ppid" = "1" ] && kill -9 $pid 2>/dev/null
    done
    setsid nohup $R/collect/run_full_local.sh </dev/null >/dev/null 2>&1 &
    disown
  fi

  # progress daemon
  if ! pgrep -f "r3_progress_daemon" >/dev/null; then
    setsid nohup /tmp/r3_progress_daemon.sh </dev/null >/dev/null 2>&1 &
    disown
    say "progress daemon restarted"
  fi

  sleep 300
done
