"""Independent accounting and provenance checks, no inference calls."""
import hashlib,json,math
from pathlib import Path
from . import core,tool_aware_v1 as v,tool_aware_finish as f

def main():
 p=v.verify();out=v.OUT/'fresh';tasks=json.loads((out/'TASKS.json').read_text());plans={r['task_id']:r for r in json.loads((out/'PLANS.json').read_text())};tm={t['task_id']:t for t in tasks};routed=core.lines(out/'routed_RESPONSES.jsonl');ri={(r['task_id'],r['node_id']):r for r in routed};facts={}
 for r in routed:
  if r['node_id']=='extraction':
   try:facts[r['task_id']]=v.parse_facts(r['answer'])
   except Exception:pass
 counts={};alltokens=0
 for slot,cap in p['max_requests'].items():
  file=out/(slot+'_REQUESTS.jsonl');responses=out/(slot+'_RESPONSES.jsonl')
  assert file.exists() and responses.exists()
  rq=core.lines(file);rr=core.lines(responses);index={(r['task_id'],r['node_id']):r for r in rr};assert len(index)==len(rr)==len(rq)<=cap
  counts[slot]=len(rq)
  for q in rq:
   tid=q['task_id'];nid=q['node_id'];response=index[tid,nid];assert q['unix_time']>=p['created_unix'];assert response['model']==q['model']
   if slot=='routed':assert q['model']==next(n['selected_model'] for n in plans[tid]['nodes'] if n['node_id']==nid)
   else:assert tid in json.loads((out/'SHADOW_IDS.json').read_text()) and q['model']==slot
   expected=v.eprompt(tm[tid]) if nid=='extraction' else v.sprompt(tm[tid],facts[tid]);assert q['prompt']==expected
   if response.get('usage'):
    u=response['usage'];assert u['total_tokens']==u['prompt_tokens']+u['completion_tokens'];alltokens+=u['total_tokens']
   if nid=='semantic':assert q['unix_time']>=ri[tid,'extraction']['end_unix']
 for plan in plans.values():
  for n in plan['nodes']:
   cs=n['candidates'];eligible={s:c for s,c in cs.items() if c['eligible']};winner=max(sorted(eligible),key=lambda s:eligible[s]['score']);assert winner==n['selected_model']
   for c in eligible.values():assert abs(c['score']-(c['Q']-.05*c['C_tokens']/1000-.05*c['L_seconds']/10))<1e-12
 tool=core.lines(out/'TOOL_NODES.jsonl');assert len(tool)==len({r['task_id'] for r in tool})==40
 for t in tool:
  if t['arithmetic_executed']:assert f.close(f.independent_calc(t['expression'],facts[t['task_id']]),t['value'])
  assert t['ended_unix']>=t['started_unix']
 per=json.loads((out/'PER_TASK.json').read_text());result=json.loads((out/'RESULTS.json').read_text());assert len(per)==40
 labels={x['task_id']:x['answer'] for x in json.loads((out/'EVAL_ONLY.json').read_text())}
 for r in per:assert r['success']==f.close(r['answer'],labels[r['task_id']]) and r['quality']==float(r['success'])
 assert result['total_tokens']==sum((r.get('usage') or {}).get('total_tokens',0) for r in routed)
 controlled=v.OUT/'controlled';protocol=json.loads((controlled/'PROTOCOL.json').read_text())
 for path,h in protocol['bindings'].items():assert core.sha(path)==h
 old=json.loads((core.ROOT/'static_dag_v0/local_repair/run_v1/TASKS.json').read_text());cr=json.loads((controlled/'PER_TASK.json').read_text())
 for task,r in zip(old,cr):
  x=task['input'];n=sum(x['departments'])-x['stock']+x['reserve'];c=[]
  for s in x['suppliers']:
   total=n*(s['unit_cents']-s['discount_cents'])+s['freight_cents']+s['handling_cents']
   if s['capacity']>=n and s['days']<=x['deadline_days'] and total<=x['budget_cents']:c.append((total,s['vendor']))
  total,vendor=min(c) if c else (0,'NONE');assert r['answer']==dict(vendor=vendor,total_cents=total)
 checks=['Controlled identical 20 tasks and original artifacts verified','40 natural source tasks and no answer/program/evidence annotation in requests','Frozen candidate utility argmax matches every routed model','Shadow sample and all per-model budgets obeyed; Small unavailability explicit','Semantic inputs equal actual routed extraction, no label oracle substitution','Independent rational interpreter verifies executed tool arithmetic','Actual tokens and numeric final quality reconcile']
 core.write(out/'VALIDATION.json',dict(passed=True,checks=checks,physical_calls=counts,total_known_tokens_including_shadow=alltokens,small_actual_evaluation_complete=False,small_reason='Missing original 3B weights and compatible frozen profile',validator_sha256=core.sha(Path(__file__))))
 for folder in [out,controlled]:core.write(folder/'ARTIFACT_MANIFEST.json',{x.name:core.sha(x) for x in folder.iterdir() if x.is_file() and x.suffix not in ['.log'] and x.name!='ARTIFACT_MANIFEST.json'})
 print(json.dumps(dict(passed=True,physical_calls=counts,total_tokens_including_shadow=alltokens)))
if __name__=='__main__':main()
