#!/usr/bin/env bash
set -euo pipefail
cd /root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main
mkdir -p run_logs/nvidia_confirm_v1
log=run_logs/nvidia_confirm_v1/pipeline.log
while true; do
  count=$(wc -l < data/nvidia_current_v1/results.jsonl)
  printf '%s development_calls=%s/3600\n' "$(date -u +%FT%TZ)" "$count" >> "$log"
  if [ "$count" -ge 3600 ]; then break; fi
  sleep 60
done
python scripts/aggregate_nvidia_current_pool.py >> "$log" 2>&1
llmrouter train --router mlprouter --config configs/model_config_train/mlprouter_nvidia_current_v1.yaml --device cuda >> "$log" 2>&1
python scripts/audit_nvidia_readiness.py --phase pre_confirmation >> "$log" 2>&1
python - <<'PY' >> "$log" 2>&1
import hashlib,json
from pathlib import Path
root=Path('.')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
checkpoint=root/'llmrouter/saved_models/mlprouter/mlprouter_nvidia_current_v1_seed42.pkl'
if not checkpoint.exists(): raise FileNotFoundError(checkpoint)
freeze={
 'experiment_id':'nvidia_current_v1_development_freeze',
 'frozen_before_confirmatory_calls':True,
 'router':'mlprouter',
 'checkpoint':str(checkpoint),
 'checkpoint_sha256':sha(checkpoint),
 'config_sha256':sha('configs/model_config_train/mlprouter_nvidia_current_v1.yaml'),
 'development_results_sha256':sha('data/nvidia_current_v1/results.jsonl'),
 'development_split_sha256':sha('data/nvidia_current_v1/grouped/split_summary.json'),
 'confirmation_preregistration_sha256':sha('data/nvidia_confirm_v1/PREREGISTRATION.json'),
 'cost_lambda':0.0,
 'selection_note':'best epoch selected only by development validation metric; no confirmation outcomes read'
}
out=root/'run_logs/nvidia_confirm_v1/FROZEN_ROUTER.json';out.write_text(json.dumps(freeze,indent=2))
seal_path=root/'data/nvidia_confirm_v1/SEAL.json';seal=json.loads(seal_path.read_text());seal['api_calls_started']=True;seal['router_freeze_sha256']=sha(out);seal_path.write_text(json.dumps(seal,indent=2))
print(json.dumps(freeze,indent=2))
PY
python scripts/predict_nvidia_confirm_router.py >> "$log" 2>&1
set -a
source .env
set +a
python scripts/collect_mlprouter_reevaluations.py --manifest data/nvidia_confirm_v1/manifest.jsonl --data data/nvidia_confirm_v1/queries_sealed.jsonl --output data/nvidia_confirm_v1/results.jsonl --workers 4 >> "$log" 2>&1
python - <<'PY' >> "$log" 2>&1
import hashlib,json
from pathlib import Path
p=Path('data/nvidia_confirm_v1/results.jsonl')
seal_path=Path('data/nvidia_confirm_v1/SEAL.json');seal=json.loads(seal_path.read_text());seal['collection_complete']=True;seal['results_rows']=sum(1 for _ in p.open());seal['results_sha256']=hashlib.sha256(p.read_bytes()).hexdigest();seal_path.write_text(json.dumps(seal,indent=2));print(json.dumps(seal,indent=2))
PY
python scripts/evaluate_nvidia_confirm_once.py >> "$log" 2>&1
