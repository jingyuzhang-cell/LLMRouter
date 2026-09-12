#!/usr/bin/env bash
# Live progress monitor for repeat_compatibility_400.
# Usage: bash router_v2/watch_repeat_400.sh [interval_sec]   (Ctrl-C to exit)
INTERVAL=${1:-10}
D=/root/r3_own_pool/data/repeat_compatibility_400
LOG=/tmp/repeat_compatibility_400_resume.log
BAR_W=30
prev_total=-1; prev_t=0

bar() { # done total
  local f=$(( $1 * BAR_W / $2 )) e=$(( BAR_W - $1 * BAR_W / $2 ))
  printf '%*s' "$f" '' | tr ' ' '█'; printf '%*s' "$e" '' | tr ' ' '░'
}
cnt() { [ -f "$D/$1.jsonl" ] && echo $(( $(wc -l < "$D/$1.jsonl") )) || echo 0; }

while true; do
  now=$(date +%s)
  large=$(cnt large); reasoning=$(cnt reasoning); medium=$(cnt medium); coder=$(cnt coder)
  total=$(( medium + coder ))

  # measured rate (items/min) over the last tick window
  rate=0
  if [ "$prev_total" -ge 0 ] && [ "$now" -gt "$prev_t" ]; then
    rate=$(( (total - prev_total) * 60 / (now - prev_t) ))
    [ "$rate" -lt 0 ] && rate=0
  fi
  prev_total=$total; prev_t=$now

  active=""; for m in medium coder; do
    v=$(cnt $m); [ "$v" -lt 2000 ] && active=$m && break
  done

  stage=$(grep -E 'START |FINISHED |ALL_400_EXPERIMENTS_COMPLETE' "$LOG" 2>/dev/null | tail -1)

  printf '\033[H\033[2J\033[3J'
  printf '\033[1;36mrepeat_compatibility_400\033[0m  %s\n' "$(date '+%F %T')"
  echo   '────────────────────────────────────────────────────────'
  for m in large reasoning medium coder; do
    v=$(cnt $m)
    if   [ "$v" -ge 2000 ]; then col='\033[32m'; tail_msg='done'
    elif [ "$m" = "$active" ]; then col='\033[1;33m'; tail_msg='active'
    else col='\033[90m'; tail_msg='queued'; fi
    printf '  %-9s %b%s%b %4d/2000  %s\n' "$m" "$col" "$(bar "$v" 2000)" '\033[0m' "$v" "$tail_msg"
  done
  echo   '────────────────────────────────────────────────────────'
  if [ -n "$stage" ]; then
    printf '  pipeline : %s\n' "$stage"
  elif [ -n "$active" ]; then
    phase=$(grep -o '"phase"[^,}]*' "$D/${active}_STATUS.json" 2>/dev/null | cut -d'"' -f4)
    v=$(cnt $active); rem=$(( 2000 - v ))
    if [ "$rate" -gt 0 ]; then eta=$(( rem / rate )); etas="ETA ~${eta}m @${rate}/min"
    else etas="rate ${rate}/min"; fi
    printf '  pipeline : COLLECTING %s (%s)  remaining %d  %s\n' "$active" "${phase:-...}" "$rem" "$etas"
  else
    printf '  pipeline : collection finished, waiting for rescore/train\n'
  fi
  pgrep -f 'collect_repeat_compatibility_400|run_after_repeat_400' >/dev/null \
    || printf '\033[31m  WARN: collector process not running (check %s)\033[0m\n' "$LOG"

  if grep -q 'ALL_400_EXPERIMENTS_COMPLETE' "$LOG" 2>/dev/null; then
    printf '\n\033[1;32mALL_400_EXPERIMENTS_COMPLETE — monitor exiting.\033[0m\n'; exit 0
  fi
  sleep "$INTERVAL"
done
