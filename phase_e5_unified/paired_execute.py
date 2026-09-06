"""Execute frozen policies on real upstream histories; no trajectory splicing."""
import asyncio,fcntl,hashlib,json,sys,time
from pathlib import Path
ROOT=Path('/root');sys.path.insert(0,str(ROOT));OUT=ROOT/'phase_e5_unified'
from phase_e5_unified.execute import Engine,rows,append,atomic,judge_prompt
from phase_e5_unified.common import MODELS,NODES,LADDERS,FINAL,whole_prompt,delivery
from run_e4_0_b_exploration import prompt as dag_prompt
from phase_e4_0.execution_controls import generation_ceiling_binding
from phase_e4_1.deterministic_extractor import score_deterministic
from phase_e4_1.judge_format_normalization import parse_scores
from scripts.run_finance_model_evaluation import answer_from_result

async def run_one(engine,entry,task,contracts):
 key=entry['execution_key'];finalpath=OUT/'PAIRED_RESULTS.jsonl'
 if key in {r['execution_key'] for r in rows(finalpath)}:return
 nodepath=OUT/'PAIRED_NODE_RECORDS.jsonl'
 previous=[];assignment=entry['assignment'];sequence=NODES if entry['regime']=='DAG' else ('N4',)
 for node in sequence:
  saved=[r for r in rows(nodepath) if r['execution_key']==key and r['node_id']==node]
  if saved:previous.append(saved[-1]);continue
  model=assignment[node];prompt=dag_prompt(task,node,previous) if entry['regime']=='DAG' else whole_prompt(task)
  if entry['regime']=='DAG' and node=='N4':prompt+='\n'+FINAL
  ladder=LADDERS[node];ceiling_idx=0;errors=0;raw='';binding=False;success=False;attempts=[]
  while ceiling_idx<len(ladder) and errors<3:
   delay=0
   if attempts and not binding:
    delay=(30,120)[min(errors-1,1)];await asyncio.sleep(delay)
   r=await engine.call(f'paired|{key}|{node}|{len(attempts)+1}',model,prompt,ladder[ceiling_idx],240 if node=='N1' else 120,retry_backoff_ms=delay*1000)
   attempts.append(r);result=r['raw_response'];raw=answer_from_result(result) if result else ''
   reason=(result.get('choices') or [{}])[0].get('finish_reason')
   binding=generation_ceiling_binding(reason,r['usage'],ladder[ceiling_idx],empty_output=not raw.strip())
   success=r['error_type'] is None and bool(raw.strip())
   if binding:ceiling_idx+=1
   elif success:break
   else:errors+=1
  if binding:raise RuntimeError('Terminal generation ceiling binding; no scientific score permitted')
  rec={'execution_key':key,'task_id':task['task_id'],'node_id':node,'selected_model':model,'raw_output':raw,'provider_success':success,'generation_ceiling_binding':binding,'cost_usd':sum(r['accounted_upper_bound_usd'] for r in attempts),'cost_is_upper_bound':any(not r['billing_known'] for r in attempts),'latency_ms':sum(r['latency_ms']+r.get('retry_backoff_ms',0) for r in attempts)}
  append(nodepath,rec);previous.append(rec)
 final=previous[-1];valid,obj=delivery(final['raw_output'],final['provider_success'],final['generation_ceiling_binding'])
 q=None;layer='delivery_failure'
 if not valid:q=0.
 elif task['task_id'] in contracts:
  q=score_deterministic(obj['answer'],contracts[task['task_id']])['score'];layer='deterministic'
 else:
  layer='machine_qwen_only';prompt=judge_prompt(task,obj['answer'])
  for attempt in range(3):
   r=await engine.call(f'pairedjudge|{key}|{attempt}','qwen-max',prompt,1500,90)
   try:q=parse_scores(answer_from_result(r['raw_response']),['A'])['A']/4.;break
   except (ValueError,TypeError,KeyError):pass
 if q is None:raise RuntimeError('Missing paired evaluator label; cannot impute')
 rec={'execution_key':key,'task_id':task['task_id'],'assignment':assignment,'Q':q,'R':float(valid),'C':sum(r['cost_usd'] for r in previous),'T_ms':sum(r['latency_ms'] for r in previous),'cost_is_upper_bound':any(r['cost_is_upper_bound'] for r in previous),'scoring_layer':layer,'real_upstream_execution':True}
 append(finalpath,rec);print(json.dumps({'paired_complete':key,'budget_accounted':engine.charged()}),flush=True)

async def main():
 freeze=json.loads((OUT/'PAIRED_EXECUTION_FREEZE.json').read_text())
 for rel,digest in freeze['artifact_sha256'].items():assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest,rel
 tasks={r['task_id']:r for r in rows(OUT/'DEVELOPMENT_TASKS.jsonl')};entries=rows(OUT/'PAIRED_EXECUTION_MANIFEST.jsonl');unique={r['execution_key']:r for r in entries}
 contracts={r['task_id']:r for r in json.loads((ROOT/'phase_e4_1/E4_1_NUMERIC_UNIT_CONTRACT_FROZEN.json').read_text())['tasks']}
 engine=Engine()
 # Whole-query arms also executed afresh: removes historical/new timing and prompt mismatches.
 jobs=sorted(unique.values(),key=lambda r:hashlib.sha256(('E5PAIR20260905'+r['execution_key']).encode()).hexdigest())
 for i in range(0,len(jobs),4):
  answers=await asyncio.gather(*(run_one(engine,r,tasks[r['task_id']],contracts) for r in jobs[i:i+4]),return_exceptions=True)
  errors=[str(x) for x in answers if isinstance(x,Exception)]
  if errors:raise RuntimeError('; '.join(errors))
 atomic(OUT/'PAIRED_STATUS.json',{'status':'COMPLETE','unique_executions':len(unique),'accounted_usd':engine.charged(),'evidence_role':'OOF development validation, not fresh holdout'})
if __name__=='__main__':
 with (OUT/'RUN.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:asyncio.run(main())
  except Exception as exc:atomic(OUT/'PAIRED_STATUS.json',{'status':'STOPPED','reason':str(exc)});raise
