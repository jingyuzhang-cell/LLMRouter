#!/usr/bin/env python3
"""Outcome-blind long-N1 compatibility calibration for DeepSeek and GLM."""
import asyncio,json,sys,time
from datetime import datetime,timezone
from pathlib import Path
from run_e4_0_b_exploration import ROOT,PROJECT,CONFIG,SOURCE,load_env,parse,prompt,rows
from phase_e4_0.execution_controls import generation_ceiling_binding
OUT=ROOT/'phase_e4_0_v2/E4_0_B_V2_DS_GLM_CALIBRATION.json'

def finish_reason(result):
 try:return result['choices'][0].get('finish_reason')
 except Exception:return None

async def main():
 load_env(); sys.path.insert(0,str(PROJECT)); from openclaw_router.config import OpenClawConfig; from openclaw_router.server import LLMBackend; from scripts.run_finance_model_evaluation import answer_from_result,cost_usd,usage_from_result
 cfg=OpenClawConfig.from_yaml(str(CONFIG)); backend=LLMBackend(cfg); tasks=rows(SOURCE); task=max(tasks,key=lambda x:len(x['context'])); request=prompt(task,'N1',[]); results=[]
 for model,ladder in [('deepseek-chat',[2400]),('glm-5.2',[8192,16384,32768])]:
  for ceiling in ladder:
   started=time.perf_counter(); answer=''; usage={}; error=None; result={}
   try:
    result=await backend.call(model,[{'role':'user','content':request}],max_tokens=ceiling,temperature=0,stream=False); answer=answer_from_result(result); usage=usage_from_result(result,request,answer)
    if not answer.strip():raise RuntimeError('empty answer')
   except Exception as exc:error=f'{type(exc).__name__}: {exc!r}'[:1200]
   parsed,valid=parse(answer) if error is None else ({},False); reason=finish_reason(result); binding=generation_ceiling_binding(reason,usage,ceiling)
   llm=cfg.llms[model]; rec={'task_id':task['task_id'],'requested_model_alias':model,'provider_returned_model':result.get('model') if isinstance(result,dict) else None,'resolved_version':'unavailable' if not isinstance(result,dict) or not result.get('model') else result.get('model'),'provider_endpoint':f"{llm.base_url.rstrip('/')}/{llm.chat_path.lstrip('/')}",'execution_timestamp':datetime.now(timezone.utc).isoformat(),'local_context_limit':llm.context_limit,'max_tokens':ceiling,'provider_success':error is None,'provider_error':error,'format_valid':valid and isinstance(parsed,dict) and 'evidence_items' in parsed and 'confidence' in parsed,'finish_reason':reason,'generation_ceiling_binding':binding,'tokens':usage,'content_nonempty':bool(answer.strip()),'latency_ms':round((time.perf_counter()-started)*1000,2),'cost_usd':float(cost_usd(cfg,model,usage)) if usage else 0,'raw_output':answer}
   results.append(rec); print(json.dumps({k:v for k,v in rec.items() if k!='raw_output'},ensure_ascii=False),flush=True)
   if rec['provider_success'] and rec['content_nonempty'] and rec['format_valid'] and not binding:break
 payload={'status':'PASS' if all(any(x['requested_model_alias']==m and x['provider_success'] and x['format_valid'] and not x['generation_ceiling_binding'] for x in results) for m in ('deepseek-chat','glm-5.2')) else 'FAIL','semantic_quality_inspected':False,'results':results}; OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n'); print(json.dumps({'status':payload['status'],'attempts':len(results),'cost_usd':sum(x['cost_usd'] for x in results)},ensure_ascii=False))
 raise SystemExit(0 if payload['status']=='PASS' else 2)

if __name__=='__main__':asyncio.run(main())
