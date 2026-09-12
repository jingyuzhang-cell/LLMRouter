"""Monitor frozen confirmation collection, run Large, then analyze."""
import json,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];MODEL=Path('/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8');R1=ROOT/'data/ridge_confirmation_100_reasoning/reasoning.jsonl';MED=ROOT/'data/ridge_confirmation_100_selected/medium_STATUS.json';STATUS=ROOT/'router_v2/ridge_confirmation_100/PIPELINE_STATUS.json'
def atomic(value):
 p=STATUS.with_suffix('.tmp');p.write_text(json.dumps(value,indent=2)+'\n');p.replace(STATUS)
def model_complete():
 try:
  index=json.loads((MODEL/'model.safetensors.index.json').read_text());files=set(index['weight_map'].values());return bool(files) and all((MODEL/f).exists() and (MODEL/f).stat().st_size>100_000_000 for f in files),len(files)
 except Exception:return False,0
def count(path):
 return sum(1 for x in path.open()) if path.exists() else 0
try:
 while True:
  complete,shards=model_complete();r1=count(R1);medium=json.loads(MED.read_text()).get('phase') if MED.exists() else None;atomic({'phase':'WAITING_INPUTS','r1_records':r1,'r1_target':500,'medium':medium,'large_checkpoint_complete':complete,'large_shards':shards,'large_download_bytes':sum(p.stat().st_size for p in MODEL.glob('*.safetensors'))})
  if complete and r1==500 and medium=='FINISHED':break
  if r1>500:raise ValueError(f'Duplicate R1 rows: {r1}')
  time.sleep(30)
 atomic({'phase':'COLLECTING_LARGE','r1_records':500,'medium':'FINISHED','large_checkpoint_complete':True})
 subprocess.run([sys.executable,'-u','-m','router_v2.collect_ridge_confirmation_selected','--slot','large'],cwd=ROOT,check=True)
 atomic({'phase':'ANALYZING'})
 subprocess.run([sys.executable,'-u','-m','router_v2.analyze_ridge_confirmation_100'],cwd=ROOT,check=True)
 atomic({'phase':'COMPLETE','report':str(ROOT/'router_v2/experiment_ridge_confirmation_100/REPORT.md')})
except Exception as exc:
 atomic({'phase':'BLOCKED_ERROR','error':f'{type(exc).__name__}: {exc}','traceback':traceback.format_exc()});raise
