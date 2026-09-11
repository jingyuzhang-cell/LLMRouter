"""Bounded infrastructure repair, separate journal; no quality-based resampling."""
import json,time,fcntl,subprocess,sys,shutil
from pathlib import Path
from . import run_repeat_stability as e
from .data import sha
ROOT=Path(__file__).resolve().parents[1];P=ROOT/'router_v2/mmlu_utility_panel_400';D=ROOT/'data/mmlu_utility_repeats_400';O=ROOT/'data/mmlu_utility_repair_20260911'
def save(name,value):
 p=O/name;t=p.with_suffix('.tmp');t.write_text(json.dumps(value,indent=2)+'\n');t.replace(p)
def status(phase,**kw):save('STATUS.json',dict(phase=phase,ts=time.time(),**kw))
def append(path,value):
 with path.open('a') as f:f.write(json.dumps(value)+'\n');f.flush()
def main():
 plan=json.loads((O/'REPAIR_PLAN.json').read_text());diag=json.loads((O/'DIAGNOSTIC_PLAN.json').read_text())
 deadline=time.monotonic()+24*3600
 while not (O/'DIAGNOSTIC_RESULT.json').exists():
  status('WAITING_FOR_DIAGNOSTIC')
  if time.monotonic()>deadline:raise RuntimeError('Diagnostic deadline')
  time.sleep(15)
 result=json.loads((O/'DIAGNOSTIC_RESULT.json').read_text())
 if result['status']!='response_received':
  status('BLOCKED_DIAGNOSTIC_FAILURE',result_file='DIAGNOSTIC_RESULT.json');return
 panel={r['query_id']:r for r in e.bind_panel(e.read_jsonl(P/'PANEL.jsonl'),ROOT/'data/cohort_full_v2')}
 protocol=json.loads((D/'COLLECTION_PROTOCOL.json').read_text())
 if sha(P/'PANEL.jsonl')!=plan['panel_sha256'] or sha(e.__file__)!=protocol['engine_sha256']:raise RuntimeError('Frozen input changed')
 def record(raw,q,k):
  return dict(**raw,**e.score_answer(panel[q],raw.get('answer'),raw['status']),query_id=q,repeat_index=k,slot='reasoning',dataset='mmlupro',task_type=panel[q]['task_type'],model=e.SLOTS['reasoning']['model'],panel_index=panel[q]['panel_index'],panel_sha256=protocol['panel_sha256'],cohort_sha256=protocol['cohort_sha256'],temperature=.7,top_p=1.,ts=time.time(),transport_budget_spent=1,repair_plan_sha256=sha(O/'REPAIR_PLAN.json'))
 journal=O/'reasoning.jsonl';existing=e.read_jsonl(journal) if journal.exists() else []
 known={(r['query_id'],r['repeat_index']) for r in existing};key=(diag['query_id'],diag['repeat_index'])
 if key not in known:
  response=result['response'];choice=response['choices'][0];message=choice.get('message',{});answer=(message.get('content') or '').strip() or None;finish=choice.get('finish_reason');usage=response.get('usage') or {}
  raw=dict(answer=answer,thinking=message.get('reasoning_content'),finish_reason=finish,status='ok' if finish=='stop' and answer else ('truncated' if finish=='length' else 'failed'),cost=dict(tokens_input=usage.get('prompt_tokens'),tokens_output=usage.get('completion_tokens'),tokens_estimated=False),latency=dict(total_ms=result['latency_seconds']*1000))
  append(journal,record(raw,*key));known.add(key)
  if raw['status']=='failed':status('BLOCKED_EMPTY_DIAGNOSTIC_RESPONSE');return
 with (ROOT/'collect/logs/reasoning.lock').open('a+') as lock:
  while True:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    status('WAITING_FOR_EXISTING_COLLECTOR')
    if time.monotonic()>deadline:raise RuntimeError('Collector deadline')
    time.sleep(30)
  current=e.read_jsonl(D/'reasoning.jsonl');valid={(r['query_id'],r['repeat_index']) for r in current if r['status']!='failed' and not r.get('error') and r.get('quality') in (0,1)}
  attempts=O/'ATTEMPTS.jsonl';reserved={(r['query_id'],r['repeat_index']) for r in e.read_jsonl(attempts)} if attempts.exists() else set()
  client=e.api_client()
  for item in plan['failed_keys']:
   q,k=item['query_id'],item['repeat_index']
   if (q,k) in known or (q,k) in valid or (q,k)==key:continue
   if (q,k) in reserved:status('BLOCKED_UNRESOLVED_RESERVED_ATTEMPT',query_id=q,repeat_index=k);return
   append(attempts,dict(query_id=q,repeat_index=k,ts=time.time(),max_requests=1));status('REPAIRING',query_id=q,repeat_index=k)
   raw=e.generate(client,e.SLOTS['reasoning']['served'],panel[q],.7,1.,1);append(journal,record(raw,q,k))
   if raw['status']=='failed' or raw.get('error'):status('BLOCKED_REPAIR_SERVICE_FAILURE',query_id=q,repeat_index=k);return
  merged={ (r['query_id'],r['repeat_index']):r for r in current}
  for r in e.read_jsonl(journal):
   if r['status']!='failed' and not r.get('error') and r.get('quality') in (0,1):
    key=(r['query_id'],r['repeat_index'])
    if key not in valid:merged[key]=r
  good=sum(r['status']!='failed' and not r.get('error') and r.get('quality') in (0,1) for r in merged.values())
  if good!=2000:status('BLOCKED_REMAINING_MISSING_DATA',valid_reasoning=good);return
  clean=ROOT/'data/mmlu_utility_repeats_400_repaired';clean.mkdir(exist_ok=False)
  shutil.copy2(D/'large.jsonl',clean/'large.jsonl');shutil.copy2(D/'COLLECTION_PROTOCOL.json',clean/'COLLECTION_PROTOCOL.json')
  (clean/'reasoning.jsonl').write_text(''.join(json.dumps(r)+'\n' for _,r in sorted(merged.items())))
  (clean/'REPAIR_PROVENANCE.json').write_text(json.dumps({str(path):sha(path) for path in [D/'large.jsonl',D/'reasoning.jsonl',journal,O/'REPAIR_PLAN.json']},indent=2)+'\n')
 status('BUILDING_DISTRIBUTIONS')
 subprocess.run([sys.executable,'-m','router_v2.utility_distributions','--panel-dir',str(P),'--data-dir',str(clean)],cwd=ROOT,check=True)
 output=ROOT/'router_v2/mmlu_learnability_400_repaired'
 subprocess.run([sys.executable,'-m','router_v2.mmlu_learnability','--panel-dir',str(P),'--data-dir',str(clean),'--output',str(output)],cwd=ROOT,check=True)
 status('P1_COMPLETE',report=str(output/'REPORT.md'),ma_training='NOT_STARTED')
if __name__=='__main__':
 try:main()
 except Exception as exc:status('BLOCKED_ERROR',error=str(exc));raise
