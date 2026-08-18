#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
data="data/finance_router/finrome_300_confirmatory_v3"
mode="${1:---dry-run}"
if [[ "$mode" == "--dry-run" ]]; then
  python scripts/collect_finrome_300_resilient.py --data-dir "$data" --dry-run
  python scripts/collect_finrome_300_judges.py --data-dir "$data" --dry-run
  exit 0
fi
if [[ "$mode" != "--execute" ]]; then echo "usage: $0 [--dry-run|--execute]" >&2; exit 2; fi
previous=-1
while true; do
  python scripts/collect_finrome_300_resilient.py --data-dir "$data" --workers 7 --retries 2
  complete=$(python -c "import json,pathlib;p=pathlib.Path('$data/responses.jsonl');r=[json.loads(x) for x in p.read_text().splitlines() if x.strip()];print(len({(x['task_id'],x['model'],x['repeat']) for x in r if x.get('success')}))")
  [[ "$complete" -ge 3600 ]] && break
  [[ "$complete" -le "$previous" ]] && { echo "answers made no progress: $complete/3600" >&2; exit 3; }
  previous="$complete"
done
previous=-1
while true; do
  python scripts/collect_finrome_300_judges.py --data-dir "$data" --workers 6 --retries 3
  complete=$(python -c "import json,pathlib;p=pathlib.Path('$data/judges.jsonl');r=[json.loads(x) for x in p.read_text().splitlines() if x.strip()];print(len({(x['task_id'],x['candidate_model'],x['repeat'],x['judge_model']) for x in r if x.get('parsed')}))")
  [[ "$complete" -ge 1800 ]] && break
  [[ "$complete" -le "$previous" ]] && { echo "judges made no progress: $complete/1800" >&2; exit 4; }
  previous="$complete"
done
python scripts/build_finrome_300_matrix.py --data-dir "$data"
