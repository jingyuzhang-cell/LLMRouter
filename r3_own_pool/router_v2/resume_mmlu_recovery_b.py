"""One bounded recovery pass after the existing repair releases its API lock."""
import json,time,fcntl,sys,subprocess,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from . import run_repeat_stability as e
from .data import sha
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'router_v2/mmlu_utility_panel_400';D=ROOT/'data/mmlu_utility_repeats_400';R=ROOT/'data/mmlu_utility_repair_20260911';O=ROOT/'data/mmlu_utility_resume_20260911b'
def rows(p):return e.read_jsonl(p) if p.exists() else []
def good(r):return r['status']!='failed' and not r.get('error') and r.get('quality') in (0,1)
def key(r):return r['query_id'],int(r['repeat_index'])
def save(name,r):
 p=O/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(r,indent=2)+'\n');t.replace(p)
def state(phase,**kw):save('STATUS.json',dict(phase=phase,ts=time.time(),**kw))
def append(p,r):
 with p.open('a') as f:f.write(json.dumps(r)+'\n');f.flush()
def main():
 O.mkdir(exist_ok=True);deadline=time.monotonic()+24*3600
 with (ROOT/'collect/logs/reasoning.lock').open('a+') as lock:
  while True:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    state('WAITING_FOR_REPAIR')
    if time.monotonic()>deadline:raise RuntimeError('Repair wait deadline')
    time.sleep(30)
  repair_state=json.loads((R/'STATUS.json').read_text())
  panel={r['query_id']:r for r in e.bind_panel(rows(P/'PANEL.jsonl'),ROOT/'data/cohort_full_v2')};protocol=json.loads((D/'COLLECTION_PROTOCOL.json').read_text())
  if sha(e.__file__)!=protocol['engine_sha256'] or sha(P/'PANEL.jsonl')!=protocol['panel_sha256']:raise RuntimeError('Frozen source changed')
  original=rows(D/'reasoning.jsonl');repair=rows(R/'reasoning.jsonl');existing=rows(O/'reasoning.jsonl');used={key(r) for r in original};valid={key(r) for r in original+repair if good(r)};old_repair={key(r) for r in json.loads((R/'REPAIR_PLAN.json').read_text())['failed_keys']}
  targets=[dict(query_id=q,repeat_index=k,max_requests=1) for q in sorted(panel) for k in range(5) if (q,k) not in valid]
  plan_path=O/'PLAN.json'
  if plan_path.exists():
   plan=json.loads(plan_path.read_text());targets=plan['targets']
  else:save('PLAN.json',dict(workers=2,targets=targets,max_transport_requests=sum(r['max_requests'] for r in targets),policy='New user-requested recovery pass, one additional request per missing key; prior attempts preserved. Read timeout1200s, workers2. Stop refill after3 consecutive failures.',sources={str(p):sha(p) for p in [D/'reasoning.jsonl',R/'reasoning.jsonl',R/'REPAIR_PLAN.json']},panel_sha256=sha(P/'PANEL.jsonl')))
  completed={key(r) for r in existing};spent=completed  # attempts without results (killed in-flight) are retried once
  todo=iter(r for r in targets if key(r) not in spent);client=e.api_client();client['timeout']=1200;errors=0;done=len(existing);stop=False
  state('COLLECTING',completed=done,targets=len(targets),consecutive_errors=0)
  with ThreadPoolExecutor(max_workers=10) as pool:
   pending={}
   def submit():
    item=next(todo,None)
    if item is None:return
    append(O/'ATTEMPTS.jsonl',dict(**item,ts=time.time()))
    pending[pool.submit(e.generate,client,e.SLOTS['reasoning']['served'],panel[item['query_id']],.7,1.,item['max_requests'])]=item
   for _ in range(10):submit()
   while pending:
    ready,_=wait(pending,return_when=FIRST_COMPLETED)
    for future in ready:
     item=pending.pop(future);q,k=key(item);raw=future.result()
     r=dict(**raw,**e.score_answer(panel[q],raw.get('answer'),raw['status']),query_id=q,repeat_index=k,slot='reasoning',dataset='mmlupro',task_type=panel[q]['task_type'],model=e.SLOTS['reasoning']['model'],panel_index=panel[q]['panel_index'],panel_sha256=protocol['panel_sha256'],cohort_sha256=protocol['cohort_sha256'],temperature=.7,top_p=1.,ts=time.time(),transport_budget_spent=item['max_requests'],resume_plan_sha256=sha(plan_path))
     append(O/'reasoning.jsonl',r);done+=1;errors=0 if good(r) else errors+1
     if errors>=3:stop=True
     state('COLLECTING',completed=done,targets=len(targets),consecutive_errors=errors)
     if not stop:submit()
  merged={}
  for r in original+repair+rows(O/'reasoning.jsonl'):
   if good(r) and key(r) not in merged:merged[key(r)]=r
  if len(merged)!=2000:state('BLOCKED_INCOMPLETE',valid_reasoning=len(merged));return
  clean=ROOT/'data/mmlu_utility_repeats_400_recovered_b';clean.mkdir(exist_ok=False)
  shutil.copy2(D/'large.jsonl',clean/'large.jsonl');shutil.copy2(D/'COLLECTION_PROTOCOL.json',clean/'COLLECTION_PROTOCOL.json')
  (clean/'reasoning.jsonl').write_text(''.join(json.dumps(r)+'\n' for _,r in sorted(merged.items())))
  (clean/'MERGE_PROVENANCE.json').write_text(json.dumps({str(p):sha(p) for p in [D/'large.jsonl',D/'reasoning.jsonl',R/'reasoning.jsonl',O/'reasoning.jsonl',plan_path]},indent=2)+'\n')
 state('RUNNING_P1')
 subprocess.run([sys.executable,'-m','router_v2.utility_distributions','--panel-dir',str(P),'--data-dir',str(clean)],cwd=ROOT,check=True)
 output=ROOT/'router_v2/mmlu_learnability_400_recovered_b'
 subprocess.run([sys.executable,'-m','router_v2.mmlu_learnability','--panel-dir',str(P),'--data-dir',str(clean),'--output',str(output)],cwd=ROOT,check=True)
 state('P1_COMPLETE',report=str(output/'REPORT.md'),ma_training='NOT_STARTED')
if __name__=='__main__':
 try:main()
 except Exception as exc:O.mkdir(exist_ok=True);state('BLOCKED_ERROR',error=str(exc));raise
