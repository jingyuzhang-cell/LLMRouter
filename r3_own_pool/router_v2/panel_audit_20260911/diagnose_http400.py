import json,time
from pathlib import Path
from urllib import request,error
from router_v2 import run_repeat_stability as e
root=Path('/root/r3_own_pool');out=root/'data/mmlu_utility_repair_20260911';records=e.read_jsonl(root/'data/mmlu_utility_repeats_400/reasoning.jsonl');failed=[r for r in records if r['status']=='failed' and 'HTTP Error 400' in str(r.get('error'))];r=failed[-1];panel={r['query_id']:r for r in e.bind_panel(e.read_jsonl(root/'router_v2/mmlu_utility_panel_400/PANEL.jsonl'),root/'data/cohort_full_v2')};row=panel[r['query_id']]
plan=dict(query_id=r['query_id'],repeat_index=r['repeat_index'],reason='diagnose HTTP400 infrastructure failure',max_new_requests=1,temperature=.7,top_p=1.,model=e.SLOTS['reasoning']['served'],original_record=r)
path=out/'DIAGNOSTIC_PLAN.json'
if path.exists():raise RuntimeError('Diagnostic budget already reserved; no automatic retry')
path.write_text(json.dumps(plan,indent=2)+'\n');client=e.api_client();payload=dict(model=e.SLOTS['reasoning']['served'],messages=[dict(role='user',content=row['query'])],temperature=.7,top_p=1.,max_tokens=e.MAX_TOKENS[row['task_type']],stream=False)
req=request.Request(client['base_url']+'/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+client['api_key']},method='POST');t=time.perf_counter()
try:
 with request.urlopen(req,timeout=client['timeout']) as response:result=dict(status='response_received',response=json.loads(response.read()),latency_seconds=time.perf_counter()-t)
except error.HTTPError as exc:
 body=exc.read().decode(errors='replace');result=dict(status='http_error',http_status=exc.code,body=body,latency_seconds=time.perf_counter()-t)
except Exception as exc:result=dict(status='transport_error',error_type=type(exc).__name__,message=str(exc))
(out/'DIAGNOSTIC_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='response'},ensure_ascii=False))
