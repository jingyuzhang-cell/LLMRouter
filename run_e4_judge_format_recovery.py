"""Frozen syntax-repair recovery on existing failed GLM calibration groups only."""
import asyncio,json,hashlib,time
from pathlib import Path
from phase_e4_1.judge_format_normalization import parse_scores
ROOT=Path('/root'); OUT=ROOT/'phase_e4_1'
source=(ROOT/'run_c9_multi_judge_feasibility.py').read_text();ns={'__name__':'recovery_definitions'}
exec(compile(source.replace('asyncio.run(main())',''),'<frozen definitions>','exec'),ns)
async def main():
 latest={(r['group_id'],r['judge_model']):r for r in ns['read_jsonl'](ROOT/'phase_c9_0/C9_2_MULTI_JUDGE_CALIBRATION_BASE_EVENTS.jsonl')}
 failed=[r for r in latest.values() if r['judge_model']=='glm-4-flash' and not r['success']]
 path=OUT/'JUDGE_FORMAT_RECOVERY_EVENTS.jsonl'
 old=ns['read_jsonl'](path) if path.exists() else []
 done={r['group_id'] for r in old}
 diag=json.loads((OUT/'JUDGE_DIAGNOSTIC_glm-4-flash.json').read_text())
 backend=ns['LLMBackend'](ns['OpenClawConfig'].from_yaml(str(ns['PROJECT']/'configs/openclaw_multi_provider.yaml')))
 for r in failed:
  gid=r['group_id']
  if gid in done:continue
  tid,rep=gid.rsplit(':',1);mapping,prompt=ns['prompt_for']((tid,int(rep)))
  row={'group_id':gid,'judge_model':'glm-4-flash','formal_label':False,'success':False,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
  try:
   if gid==diag['group_id']:
    assert row['prompt_sha256']==diag['prompt_sha256'];response=diag['raw_response'];row['new_api_call']=False
   else:
    row['new_api_call']=True
    response=await asyncio.wait_for(backend.call('glm-4-flash',[{'role':'user','content':prompt}],max_tokens=1500,temperature=0,stream=False),90)
   row['raw_response']=response
   scores=parse_scores(ns['extract_message_text'](response),sorted(mapping))
   row.update(success=True,scores_by_model={mapping[k]:v for k,v in scores.items()})
  except Exception as exc:row.update(error_type=type(exc).__name__)
  with path.open('a') as h:h.write(json.dumps(row,ensure_ascii=False)+'\n')
  print(json.dumps({k:v for k,v in row.items() if k not in ('raw_response','scores_by_model')},ensure_ascii=False),flush=True)
asyncio.run(main())
