"""Wait for repeat collection, then run frozen rescore and router diagnostics."""
import json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
status_path=ROOT/'data/repeat_compatibility_400/STATUS.json'
while True:
    if status_path.exists():
        status=json.loads(status_path.read_text())
        if status.get('phase')=='REPEAT_LABELS_COMPLETE': break
        if status.get('phase')=='BLOCKED_ERROR': raise RuntimeError(status.get('error'))
    time.sleep(30)
for module in ['router_v2.rescore_repeat_compatibility_400','router_v2.train_repeat_compatibility_400_fold_local']:
    print('START',module,flush=True)
    subprocess.run([sys.executable,'-u','-m',module],cwd=ROOT,check=True)
    print('FINISHED',module,flush=True)
print('ALL_400_EXPERIMENTS_COMPLETE',flush=True)
