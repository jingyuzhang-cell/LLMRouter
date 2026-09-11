"""Download frozen official GLM checkpoint then collect120 local train-only answers."""
import json,shutil,subprocess,fcntl,sys,time
from pathlib import Path
from huggingface_hub import snapshot_download
from . import run_repeat_stability as e
from .data import sha
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'router_v2/pool4_pilot_120';OUT=ROOT/'data/pool4_glm_pilot_120';MODEL=Path('/root/autodl-tmp/models/glm-4-9b-chat-hf')
def main():
 protocol=json.loads((P/'PROTOCOL.json').read_text());assert sha(P/'PANEL.jsonl')==protocol['panel_sha256'];panel=e.bind_panel(e.read_jsonl(P/'PANEL.jsonl'),ROOT/'data/cohort_full_v2');OUT.mkdir(exist_ok=True)
 def state(phase,**kwargs):(OUT/'STATUS.json').write_text(json.dumps(dict(phase=phase,ts=time.time(),**kwargs),indent=2)+'\n')
 if not (MODEL/'DOWNLOAD_COMPLETE.json').exists():
  free=shutil.disk_usage(MODEL.parent).free
  if free<21*1024**3:state('BLOCKED_DISK_CAPACITY',free_bytes=free,required_free_bytes=21*1024**3);return
  state('DOWNLOADING');snapshot_download(protocol['glm_checkpoint'],revision=protocol['glm_revision'],local_dir=str(MODEL),allow_patterns=['*.json','*.safetensors','*.model','*.txt','*.jinja'])
  (MODEL/'DOWNLOAD_COMPLETE.json').write_text(json.dumps(dict(repo=protocol['glm_checkpoint'],revision=protocol['glm_revision'])))
 with (ROOT/'collect/logs/local_gpu.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);log=(OUT/'VLLM.log').open('a');proc=subprocess.Popen(['/root/autodl-tmp/r3_venv/bin/vllm','serve',str(MODEL),'--served-model-name',protocol['glm_checkpoint'],'--port','8127','--max-model-len','8192','--max-num-seqs','2','--gpu-memory-utilization','.92','--generation-config','vllm'],stdout=log,stderr=subprocess.STDOUT)
  try:
   state('LOADING');e.wait_healthy(proc);client=dict(base_url='http://127.0.0.1:8127/v1',api_key='local',local=True,timeout=600);journal=OUT/'glm.jsonl';attempts=OUT/'ATTEMPTS.jsonl';spent={r['query_id'] for r in e.read_jsonl(attempts)} if attempts.exists() else set();errors=0
   for row in panel:
    q=row['query_id']
    if q in spent:continue
    with attempts.open('a') as f:f.write(json.dumps(dict(query_id=q,max_requests=2,ts=time.time()))+'\n')
    raw=e.generate(client,protocol['glm_checkpoint'],row,0.,1.,2);score=e.score_answer(row,raw.get('answer'),raw['status'])
    with journal.open('a') as f:f.write(json.dumps(dict(**raw,**score,query_id=q,slot='glm',model=protocol['glm_checkpoint'],revision=protocol['glm_revision'],temperature=0.,top_p=1.,panel_sha256=protocol['panel_sha256'],ts=time.time()))+'\n')
    spent.add(q);errors=errors+1 if raw['status']=='failed' else 0;state('COLLECTING',records=len(spent),target=120,consecutive_errors=errors)
    if errors>=3:state('BLOCKED_FAILURE',records=len(spent));return
   state('COLLECTION_FINISHED',records=len(spent))
  finally:proc.terminate();proc.wait(timeout=60);log.close()
if __name__=='__main__':main()
