#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p run_logs/finrome_300
previous=-1
while true; do
  python scripts/collect_finrome_300_judges.py --workers 6 --retries 3
  complete=$(python - <<'PY'
import json
from pathlib import Path
p=Path('data/finance_router/finrome_300/judges.jsonl')
rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
print(len({(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model']) for x in rows if x.get('parsed')}))
PY
)
  [[ "$complete" -ge 1800 ]] && break
  if [[ "$complete" -le "$previous" ]]; then
    echo "Judge made no progress ($complete/1800 parsed); stopping instead of retrying forever." >&2
    exit 2
  fi
  previous="$complete"
done
python scripts/build_finrome_300_matrix.py
python scripts/run_finrome_300_research.py
python scripts/rerun_finrome_300_m5.py
python scripts/analyze_finrome_300_final.py
