"""Bounded, resumable expected-utility repeat collection; raw successes may be reused."""
import argparse,json,fcntl,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from . import run_repeat_stability as engine
from .data import load_cohort,sha

ROOT=Path(__file__).resolve().parents[1]


def prepare(panel_dir,out):
 panel_dir=Path(panel_dir);out=Path(out);manifest=json.loads((panel_dir/'MANIFEST.json').read_text())
 for n,h in manifest['files'].items():
  if sha(panel_dir/n)!=h:raise ValueError('Panel changed')
 panel=engine.bind_panel(engine.read_jsonl(panel_dir/'PANEL.jsonl'),ROOT/'data/cohort_full_v2')
 protocol=dict(panel_manifest_sha256=sha(panel_dir/'MANIFEST.json'),panel_sha256=sha(panel_dir/'PANEL.jsonl'),
  cohort_sha256=sha(ROOT/'data/cohort_full_v2/queries.jsonl'),engine_sha256=sha(engine.__file__),
  repeats=5,temperature=.7,top_p=1.,workers=8,max_transport_attempts=2,
  quality_target='mean and distribution; no hard stable filter',monetary_cost='not_verified; store raw token counts',
  max_tokens_by_task_type=engine.MAX_TOKENS)
 out.mkdir(parents=True,exist_ok=True);p=out/'COLLECTION_PROTOCOL.json'
 if p.exists() and json.loads(p.read_text())!=protocol:raise ValueError('Collection protocol changed')
 if not p.exists():p.write_text(json.dumps(protocol,indent=2)+'\n')
 return {r['query_id']:r for r in panel},protocol


def reuse(panel_dir,out):
 panel,protocol=prepare(panel_dir,out);out=Path(out);source=ROOT/'data/repeat_fold_stability_20260910'
 old_protocol=json.loads((source/'PROTOCOL.json').read_text());old_panel={r['query_id']:r for r in engine.read_jsonl(old_protocol['panel'])}
 if sha(old_protocol['panel'])!=old_protocol['panel_sha256']:raise ValueError('Archive panel changed')
 audit={}
 for slot in ['large','reasoning']:
  target=out/(slot+'.jsonl')
  if target.exists():raise FileExistsError(target)
  path=source/(slot+'.jsonl');rows=engine.read_jsonl(path);seen=set();records=[]
  for line,r in enumerate(rows,1):
   q=r['query_id'];key=(q,r['repeat_index'])
   if q not in panel or r['status'] not in ('ok','truncated','parse_failed') or r.get('error'):continue
   if key in seen:raise ValueError('Multiple completed samples for same repeat index')
   if any(old_panel[q][k]!=panel[q][k] for k in ['query','dataset','task_type']):raise ValueError('Archive query mismatch')
   if r['cohort_sha256']!=protocol['cohort_sha256'] or r['temperature']!=.7 or r['top_p']!=1.:raise ValueError('Archive distribution mismatch')
   if r['slot']!=slot or r['model']!=engine.SLOTS[slot]['model']:raise ValueError('Model mismatch')
   seen.add(key);score=engine.score_answer(panel[q],r.get('answer'),r['status'])
   records.append({**r,**score,'panel_index':panel[q]['panel_index'],'panel_sha256':protocol['panel_sha256'],
    'archive_provenance':{'path':str(path),'sha256':sha(path),'line':line},'transport_budget_spent':0})
  target.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records));audit[slot]=dict(reused=len(records),source_sha256=sha(path))
 (out/'REUSE_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(audit,indent=2))


def collect(panel_dir,out,slot):
 panel,protocol=prepare(panel_dir,out);out=Path(out);path=out/(slot+'.jsonl')
 existing=engine.read_jsonl(path);spent={(r['query_id'],int(r['repeat_index'])) for r in existing}
 # Failed records consume their full declared budget. A restart cannot reset it.
 targets=[(r,k) for r in panel.values() for k in range(5) if (r['query_id'],k) not in spent]
 lockname='local_gpu' if slot=='large' else 'reasoning'
 with (ROOT/'collect/logs'/f'{lockname}.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  proc=log=None
  try:
   if slot=='large':client,proc,log=engine.local_client(slot,out)
   else:client=engine.api_client()
   status=dict(slot=slot,targets=len(targets),new_completed=0,consecutive_errors=0,phase='RUNNING')
   def save(): (out/(slot+'_STATUS.json')).write_text(json.dumps(status,indent=2)+'\n')
   save();print(json.dumps(status),flush=True);iterator=iter(targets);stop=False
   with path.open('a') as stream,ThreadPoolExecutor(max_workers=8) as pool:
    pending={}
    def submit():
     item=next(iterator,None)
     if item is None:return
     r,k=item
     future=pool.submit(engine.generate,client,engine.SLOTS[slot]['served'],r,.7,1.,2)
     pending[future]=(r,k)
    for _ in range(8):submit()
    while pending:
     ready,_=wait(pending,return_when=FIRST_COMPLETED)
     for future in ready:
      r,k=pending.pop(future);raw=future.result();score=engine.score_answer(r,raw.get('answer'),raw['status'])
      record={**raw,**score,'query_id':r['query_id'],'slot':slot,'repeat_index':k,'dataset':r['dataset'],'task_type':r['task_type'],
       'model':engine.SLOTS[slot]['model'],'panel_index':r['panel_index'],'panel_sha256':protocol['panel_sha256'],
       'cohort_sha256':protocol['cohort_sha256'],'temperature':.7,'top_p':1.,'ts':time.time(),'transport_budget_spent':2}
      fcntl.flock(stream,fcntl.LOCK_EX);stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush();fcntl.flock(stream,fcntl.LOCK_UN)
      status['new_completed']+=1
      status['consecutive_errors']=status['consecutive_errors']+1 if raw['status']=='failed' else 0
      if status['consecutive_errors']>=3:stop=True
      if not stop:submit()
      save()
      if status['new_completed']%25==0:print(slot,status['new_completed'],'/',len(targets),flush=True)
   status['phase']='CIRCUIT_OPEN' if stop else 'FINISHED';save()
  finally:
   if proc is not None:
    proc.terminate()
    try:proc.wait(30)
    except Exception:proc.kill()
   if log is not None:log.close()

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--panel-dir',required=True);ap.add_argument('--output',required=True)
 ap.add_argument('--mode',choices=['reuse','collect'],required=True);ap.add_argument('--slot',choices=['large','reasoning'],default='large')
 a=ap.parse_args()
 if a.mode=='reuse':reuse(a.panel_dir,a.output)
 else:collect(a.panel_dir,a.output,a.slot)
