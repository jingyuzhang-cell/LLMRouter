"""Outcome-independent infrastructure amendment: restore original Small for shadow audit."""
import json,os,socket,subprocess,time
from pathlib import Path
from urllib import request
from . import core,tool_aware_v1 as v
from . import run as engine
MODEL=Path('/root/autodl-tmp/models/Qwen2.5-3B-Instruct')
OUT=v.OUT/'fresh'

def prepare():
 from router_v2.data import load_cohort
 from router_v2.rescore_glm_pilot import extract_option
 if (OUT/'SMALL_RESTORE_AMENDMENT.json').exists():raise RuntimeError('Amendment already frozen')
 ids={r['query_id'] for r in core.lines(core.ROOT/'router_v2/label_repair_experiment/PANEL.jsonl')};source=core.ROOT/'data/raw/small.jsonl';rows=[r for r in core.lines(source) if r['query_id'] in ids];cohort,_=load_cohort(core.ROOT/'data/cohort_full_v2')
 assert len(rows)==len({r['query_id'] for r in rows})==103 and all(r['model']=='Qwen/Qwen2.5-3B-Instruct' for r in rows)
 profile=dict(quality=sum(extract_option(r['answer'])==str(cohort[r['query_id']]['ground_truth']).strip().upper()[-1] for r in rows)/103,mean_output_tokens=sum(r['cost']['tokens_output'] for r in rows)/103,mean_total_tokens=sum(r['cost']['tokens_input']+r['cost']['tokens_output'] for r in rows)/103,mean_latency_s=sum(r['latency']['total_ms']/1000 for r in rows)/103,n_queries=103,n_repeats=1,source='Historical same103 query Small answers rescored; only1repeat vs other profile10new repeats; shadow-only proxy, not equally precise')
 core.write(OUT/'SMALL_SHADOW_PROFILE.json',profile)
 bindings={str(p):core.sha(p) for p in [Path(__file__),source,core.ROOT/'data/cohort_full_v2/queries.jsonl',core.ROOT/'router_v2/rescore_glm_pilot.py',OUT/'SMALL_SHADOW_PROFILE.json',OUT/'SHADOW_IDS.json']}
 core.write(OUT/'SMALL_RESTORE_AMENDMENT.json',dict(reason='Original Small weights absent at main freeze; restore exact cached historical revision to fulfill requested Small diagnostic.',revision='aa8e72537993ba99e69dfaafa59ed015b17504d1',max_requests=20,router_eligibility=False,main_plan_unchanged=True,profile_only_for_shadow=True,no_retries=True,no_results_used=True,created_unix=time.time(),bindings=bindings))
 print('Small amendment frozen; 103 single-repeat profile; <=20 shadow calls')

def small_start(slot):
 assert slot=='small';amend=json.loads((OUT/'SMALL_RESTORE_AMENDMENT.json').read_text())
 for path,h in amend['bindings'].items():
  if core.sha(path)!=h:raise ValueError('Small amendment input changed')
 index=json.loads((MODEL/'model.safetensors.index.json').read_text());files=sorted(set(index['weight_map'].values()))
 assert all((MODEL/f).exists() for f in files)
 core.write(OUT/'SMALL_MODEL_PROVENANCE.json',dict(revision=amend['revision'],hashes={f:core.sha(MODEL/f) for f in files+['config.json','tokenizer.json']}))
 gpu=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True)
 if gpu.returncode or gpu.stdout.strip():raise RuntimeError('GPU occupied')
 with socket.socket() as s:
  if s.connect_ex(('127.0.0.1',8128))==0:raise RuntimeError('Port occupied')
 log=(OUT/'SMALL_SERVER.log').open('a');t=time.monotonic();proc=subprocess.Popen(['/root/autodl-tmp/r3_venv/bin/vllm','serve',str(MODEL),'--served-model-name','Qwen/Qwen2.5-3B-Instruct','--port','8128','--max-model-len','8192','--max-num-seqs','4','--gpu-memory-utilization','.92','--dtype','auto','--generation-config','vllm'],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
 try:
  while time.monotonic()-t<300:
   if proc.poll() is not None:raise RuntimeError('Small server exited')
   try:
    with request.build_opener(request.ProxyHandler({})).open('http://127.0.0.1:8128/health',timeout=2) as r:
     if r.status==200:return proc,log,time.monotonic()-t
   except Exception:time.sleep(1)
  raise TimeoutError('Small startup')
 except BaseException:engine.stop_model(proc,log);raise

def execute():
 engine.MODELS['small']=dict(path=str(MODEL),served='Qwen/Qwen2.5-3B-Instruct');engine.start_model=small_start;v.collect('small')
 assert len(core.lines(OUT/'small_REQUESTS.jsonl'))<=20
if __name__=='__main__':
 import sys
 globals()[sys.argv[1]]()
