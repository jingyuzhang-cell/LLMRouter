"""One unchanged-setting diagnostic per failed provider; separate from calibration."""
import asyncio, json, hashlib, time
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path('/root'); OUT=ROOT/'phase_e4_1'; OUT.mkdir(exist_ok=True)
source=(ROOT/'run_c9_multi_judge_feasibility.py').read_text()
assert source.count('asyncio.run(main())')==1
ns={'__name__':'diagnostic_harness'}
exec(compile(source.replace('asyncio.run(main())',''),'<frozen feasibility definitions>','exec'),ns)
async def main():
 rows=ns['read_jsonl'](ROOT/'phase_c9_0/C9_2_MULTI_JUDGE_CALIBRATION_BASE_EVENTS.jsonl')
 latest={(r['group_id'],r['judge_model']):r for r in rows}
 backend=ns['LLMBackend'](ns['OpenClawConfig'].from_yaml(str(ns['PROJECT']/'configs/openclaw_multi_provider.yaml')))
 for judge in ('glm-4-flash','doubao'):
  target=next(r for r in latest.values() if r['judge_model']==judge and not r['success'])
  tid,rep=target['group_id'].rsplit(':',1); mapping,prompt=ns['prompt_for']((tid,int(rep)))
  record={'judge':judge,'group_id':target['group_id'],'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'max_tokens':1500,'temperature':0,'timeout_seconds':90,'diagnostic_only':True,'timestamp':datetime.now(timezone.utc).isoformat()}
  start=time.perf_counter()
  try:
   response=await asyncio.wait_for(backend.call(judge,[{'role':'user','content':prompt}],max_tokens=1500,temperature=0,stream=False),90)
   raw=ns['extract_message_text'](response)
   record.update(raw_response=response,extracted_text=raw,parse_success=ns['parse'](raw,mapping) is not None,expected_labels=sorted(mapping))
  except Exception as exc:
   record.update(error_type=type(exc).__name__,parse_success=False)
  record['latency_ms']=round((time.perf_counter()-start)*1000,2)
  path=OUT/f'JUDGE_DIAGNOSTIC_{judge}.json';path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({k:v for k,v in record.items() if k not in ('raw_response','extracted_text')},ensure_ascii=False),flush=True)
asyncio.run(main())
