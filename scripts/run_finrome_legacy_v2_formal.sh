#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
data="data/finance_router/finrome_legacy_v2_confirmatory"
test -f "$data/FORMAL_AUTHORIZATION.json"
test -f "$data/EXECUTION_SEAL.json"
previous=-1
while true; do
  status=$(python scripts/collect_finrome_legacy_v2_formal.py --data-dir "$data" --dry-run)
  echo "$status"
  phase=$(python -c 'import json,sys;print(json.loads(sys.argv[1])["phase"])' "$status")
  [[ "$phase" == "complete" ]] && break
  current=$(python -c 'import json,sys;x=json.loads(sys.argv[1]);print(x["answers"]["completed"]+x["judges"]["completed"])' "$status")
  if [[ "$current" -eq "$previous" ]]; then
    echo "No valid-key progress across a full batch; stopping." >&2
    exit 3
  fi
  previous="$current"
  python scripts/collect_finrome_legacy_v2_formal.py --data-dir "$data" --batch-size 60
done
python scripts/build_finrome_300_matrix.py --data-dir "$data"
echo "FORMAL_COLLECTION_COMPLETE"
