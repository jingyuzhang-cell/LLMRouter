"""Bounded label-repair collection: immutable intents, no quality-based retries."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from urllib import request

from .label_repair_plan import OUT,ROOT,MODELS,SLOTS,verify,write
from .data import load_cohort,sha
from .rescore_glm_pilot import extract_option
from . import run_repeat_stability as engine


def read(path):
 return [json.loads(s) for s in path.open()] if path.exists() else []


def score(row,raw):
 if raw.get('status') not in ('ok','truncated') or not raw.get('answer'):
  return dict(quality=None,evaluation_status='infrastructure_failure_missing',parse_succeeded=False)
 option=extract_option(raw['answer'])
 return dict(quality=float(option==str(row['ground_truth']).strip().upper()[-1]) if option else 0.,
             evaluation_status='scored' if option else 'answer_parse_failed',parse_succeeded=option is not None,extracted_option=option)


def request_once(client,model,row):
 start=time.monotonic()
 payload=dict(model=model,messages=[dict(role='user',content=row['query'])],temperature=.7,top_p=1.,max_tokens=2048,stream=False)
 headers={'Content-Type':'application/json','Authorization':'Bearer '+client['api_key']}
 opener=request.build_opener(request.ProxyHandler({})) if client.get('local') else request.build_opener()
 try:
  req=request.Request(client['base_url']+'/chat/completions',data=json.dumps(payload).encode(),headers=headers,method='POST')
  with opener.open(req,timeout=client.get('timeout',600)) as response:data=json.loads(response.read())
  choice=data['choices'][0];message=choice.get('message',{});answer=(message.get('content') or '').strip() or None
  finish=choice.get('finish_reason');usage=data.get('usage') or {}
  return dict(answer=answer,thinking=message.get('reasoning_content'),finish_reason=finish,
              status='ok' if finish=='stop' and answer else ('truncated' if finish=='length' and answer else 'failed'),
              provider_model=data.get('model'),provider_id=data.get('id'),system_fingerprint=data.get('system_fingerprint'),
              usage=usage,cost=dict(tokens_input=usage.get('prompt_tokens'),tokens_output=usage.get('completion_tokens'),tokens_estimated=False),
              latency=dict(total_ms=1000*(time.monotonic()-start)))
 except Exception as exc:
  return dict(answer=None,thinking=None,status='failed',finish_reason=None,error=f'{type(exc).__name__}: {exc}',
              latency=dict(total_ms=1000*(time.monotonic()-start)))


def model_hashes(slot):
 import hashlib
 cfg=MODELS[slot];manifest=json.loads((OUT/'LOCAL_MODEL_MANIFEST.json').read_text())[slot];path=Path(cfg['path'])
 for name,h in manifest['config_sha256'].items():
  if sha(path/name)!=h:raise ValueError('Local model configuration changed')
 hashes={}
 for name,size in manifest['weight_sizes'].items():
  if (path/name).stat().st_size!=size:raise ValueError('Local checkpoint size changed')
  h=hashlib.sha256()
  with (path/name).open('rb') as stream:
   for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk)
  hashes[name]=h.hexdigest()
 target=OUT/'raw'/f'{slot}_MODEL_PROVENANCE.json'
 provenance=dict(config_sha256=manifest['config_sha256'],weight_sha256=hashes,model=cfg)
 if target.exists() and json.loads(target.read_text())!=provenance:raise ValueError('Weights changed across collection resume')
 if not target.exists():write(target,provenance)


def local_start(slot):
 model_hashes(slot)
 compute=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True)
 if compute.returncode or compute.stdout.strip():raise RuntimeError('GPU occupied; no process interrupted')
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',8127))==0:raise RuntimeError('Port8127 already occupied')
 cfg=MODELS[slot];log=(OUT/'raw'/f'{slot}_VLLM.log').open('a')
 cmd=['/root/autodl-tmp/r3_venv/bin/vllm','serve',cfg['path'],'--served-model-name',cfg['served'],
      '--port','8127','--max-model-len','16384' if slot=='large' else '8192','--max-num-seqs','4',
      '--gpu-memory-utilization','.92','--dtype','auto','--generation-config','vllm']
 proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
 try:engine.wait_healthy(proc)
 except Exception:
  proc.terminate();proc.wait(timeout=30);log.close();raise
 return dict(base_url='http://127.0.0.1:8127/v1',api_key='local',local=True,timeout=600),proc,log


def collect(slot,limit=None):
 protocol=verify()
 frozen=OUT/'BASELINE_FROZEN.json'
 if not frozen.exists():raise RuntimeError('Original-label router controls must be frozen before collection')
 base=json.loads(frozen.read_text())
 if sha(OUT/'BASELINE_PREDICTIONS.npz')!=base['predictions_sha256']:raise ValueError('Baseline changed')
 rawdir=OUT/'raw';file=rawdir/f'{slot}.jsonl';attempt_file=rawdir/f'{slot}_ATTEMPTS.jsonl'
 status_file=rawdir/f'{slot}_STATUS.json'
 cohort,_=load_cohort(ROOT/'data/cohort_full_v2')
 panel=[{**r,'ground_truth':cohort[r['query_id']]['ground_truth']} for r in read(OUT/'PANEL.jsonl')]
 def save(phase,**extra):write(status_file,dict(slot=slot,phase=phase,unix_time=time.time(),**extra))
 lockname='reasoning' if slot=='reasoning' else 'local_gpu'
 with (ROOT/'collect/logs'/f'{lockname}.lock').open('a+') as resource, (rawdir/f'{slot}.lock').open('a+') as job:
  fcntl.flock(job,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(resource,fcntl.LOCK_EX|fcntl.LOCK_NB)
  existing=read(file);attempts=read(attempt_file)
  keys=[(r['query_id'],r['repeat_index']) for r in existing]
  if len(keys)!=len(set(keys)):raise ValueError('Duplicate final generation key')
  if any(r.get('quality') is None for r in existing):raise RuntimeError('Terminal failed position exists; no automatic budget reset')
  spent={(r['query_id'],r['repeat_index']) for r in attempts}
  if spent-set(keys):raise RuntimeError('Orphan intent requires audit; no automatic replay')
  targets=[(r,k) for r in panel for k in range(5,15) if (r['query_id'],k) not in set(keys)]
  if limit is not None:targets=targets[:limit]
  if not targets:save('COMPLETE',completed=len(existing),target=len(panel)*10);return
  save('STARTING',completed=len(existing),target=len(panel)*10,scheduled=len(targets))
  proc=log=None
  try:
   if slot=='reasoning':client=engine.api_client();client['timeout']=600
   else:client,proc,log=local_start(slot)
   attempts_count=len(attempts);guard=threading.Lock()
   with file.open('a') as output,attempt_file.open('a') as ledger:
    def generate(item):
     nonlocal attempts_count
     row,repeat=item;history=[]
     for attempt in range(1,3):
      intent=dict(query_id=row['query_id'],repeat_index=repeat,slot=slot,attempt=attempt,unix_time=time.time(),
                  model=MODELS[slot]['served'],max_tokens=2048,protocol_sha256=sha(OUT/'PROTOCOL.json'))
      with guard:
       if attempts_count>=2*len(panel)*10:raise RuntimeError('Global request budget exhausted')
       ledger.write(json.dumps(intent)+'\n');ledger.flush();os.fsync(ledger.fileno());attempts_count+=1
      raw=request_once(client,MODELS[slot]['served'],row);scored=score(row,raw)
      history.append(dict(attempt=attempt,status=raw['status'],error=raw.get('error'),usage=raw.get('usage'),latency=raw.get('latency'),provider_id=raw.get('provider_id')))
      if scored['quality'] is not None:break
      if attempt==1:time.sleep(2)
     return dict(**raw,**scored,query_id=row['query_id'],repeat_index=repeat,slot=slot,
                 model=MODELS[slot]['model'],revision=MODELS[slot]['revision'],temperature=.7,top_p=1.,max_tokens=2048,
                 attempt_history=history,attempts_used=len(history),unix_time=time.time(),
                 panel_sha256=sha(OUT/'PANEL.jsonl'),protocol_sha256=sha(OUT/'PROTOCOL.json'),
                 cohort_sha256=sha(ROOT/'data/cohort_full_v2/queries.jsonl'),scorer_sha256=sha(Path(__file__).with_name('rescore_glm_pilot.py')))
    errors=0;stop=False;iterator=iter(targets)
    with ThreadPoolExecutor(max_workers=4) as pool:
     pending={}
     def submit():
      item=next(iterator,None)
      if item is not None:pending[pool.submit(generate,item)]=item
     for _ in range(min(4,len(targets))):submit()
     while pending:
      ready,_=wait(pending,return_when=FIRST_COMPLETED)
      for future in ready:
       pending.pop(future);row=future.result();output.write(json.dumps(row,ensure_ascii=False)+'\n');output.flush();os.fsync(output.fileno());existing.append(row)
       errors=errors+1 if row['quality'] is None else 0
       if errors>=3:stop=True
       save('CIRCUIT_OPEN_DRAINING' if stop else 'COLLECTING',completed=len(existing),target=len(panel)*10,
            attempts=attempts_count,consecutive_errors=errors,failures=sum(r.get('quality') is None for r in existing))
       if not stop:submit()
    failed=sum(r.get('quality') is None for r in existing)
    save('FAILED' if failed else ('COMPLETE' if len(existing)==len(panel)*10 else 'CANARY_COMPLETE'),
         completed=len(existing),target=len(panel)*10,attempts=attempts_count,failures=failed)
    if failed:raise RuntimeError('Bounded collection has missing labels; no automatic retry beyond protocol')
  finally:
   if proc is not None:
    proc.terminate()
    try:proc.wait(timeout=30)
    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)
   if log is not None:log.close()


if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('slot',choices=SLOTS+['all-local']);ap.add_argument('--limit',type=int);args=ap.parse_args()
 if args.limit is not None and args.limit<1:raise ValueError('Positive limit required')
 if args.slot=='all-local':
  for s in ['medium','large','coder']:collect(s,args.limit)
 else:collect(args.slot,args.limit)
