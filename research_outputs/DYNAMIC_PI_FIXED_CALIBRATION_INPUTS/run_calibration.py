"""One-shot independent-node calibration. Default is local preflight, no network."""
import argparse,ast,hashlib,json,os,time
from pathlib import Path
from types import SimpleNamespace
from bounded_transport import Guard,Transport,units,write
ROOT=Path(__file__).resolve().parent
VALIDATOR=Path('/root/.worktrees/planner/r3_own_pool/planner_execution_workpackage_20261028_v1/window2_core.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load():
 c=json.loads((ROOT/'CALIBRATION_CONFIG.json').read_text())
 idx=json.loads((ROOT/'REQUEST_DRAFTS/INDEX.json').read_text())
 cells=[]
 for rec in idx['requests']:
  fixture=json.loads((ROOT/(rec['node_id']+'.json')).read_text())
  body=json.loads((ROOT/'REQUEST_DRAFTS'/rec['file']).read_text())
  cells.append((rec,fixture,body))
 return c,cells

def validator(cells):
 # Use the existing structural validator unchanged; never reads reference answers.
 contracts={f['contract']:(None,None,list(f['output_schema'])) for _,f,_ in cells}
 node=next(n for n in ast.parse(VALIDATOR.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='make_validator')
 ns={'bridge':SimpleNamespace(CONTRACTS=contracts)}
 exec(compile(ast.Module(body=[node],type_ignores=[]),str(VALIDATOR),'exec'),ns)
 return ns['make_validator']({})

def preflight(auth=None):
 issues=[];lock=ROOT/'BATCH_LOCK.json'
 if not lock.exists():return ['MISSING_BATCH_LOCK']
 for p,digest in json.loads(lock.read_text())['files'].items():
  if not Path(p).is_file() or sha(Path(p))!=digest:issues.append('CHANGED:'+p)
 if (ROOT/'RUN_ONCE.lock').exists():issues.append('BATCH_ALREADY_STARTED_NO_RETRY')
 if auth is not None:
  a=json.loads(auth.read_text());c,_=load()
  for key,val in {'approved':True,'lock_sha256':sha(lock),'max_requests':8,'estimate_stop_CNY':c['estimate_stop_CNY'],'estimate_stop_USD':c['estimate_stop_USD'],'accept_non_hard_cash_cap':True,'accept_token_uncertainty':True,'accept_mutable_model_version':True,'account_and_quote_confirmed':True}.items():
   if a.get(key)!=val:issues.append('AUTH_MISMATCH:'+key)
  if not a.get('authorization_source') or not a.get('approved_by'):issues.append('AUTH_PROVENANCE_MISSING')
  for name in ('DYNAMIC_PI_QWEN_KEY','DYNAMIC_PI_DEEPSEEK_KEY'):
   if not os.environ.get(name):issues.append('MISSING_ENV:'+name)
 return issues

def cap(n,c):
 return dict(requests=n,input_tokens=n*16384,output_tokens=n*3072,total_tokens=n*19456,
             micro_cny=round(c['estimate_stop_CNY']*1e6),micro_usd=round(c['estimate_stop_USD']*1e6))

def execute(out,*,send=None):
 c,cells=load();check=validator(cells);out.mkdir(parents=True,exist_ok=False)
 origin='OFFLINE_CONTROL_TEST' if send else 'LIVE_CONDITIONAL_CALIBRATION'
 write(out/'CONTEXT.json',{'origin':origin,'config':c,'actual_cash_settlement':None})
 guard=Guard(out/'ledger.sqlite',{'batch_id':c['batch_id'],'global':cap(8,c),
       'models':{m['request_model']:cap(4,c) for m in c['models']},
       'cells':{str(i):cap(1,c) for i in range(8)}})
 transport=Transport(c,guard,out/'requests',enabled=send is None,send=send)
 rows=[];stop=None
 try:
  for i,(rec,f,body) in enumerate(cells):
   try:
    result=transport.call(str(i),f['node_id'],rec['model'],body,c['request_timeout_s'])
   except Exception as exc:
    rows.append(dict(cell=i,node=f['node_id'],model=rec['model'],status='SYSTEM_STOP',error=type(exc).__name__))
    stop='SYSTEM_STOP';break
   output=result['output']
   try:
    v=check(SimpleNamespace(output_contract=f['contract']),f['input'],output)
    if isinstance(output,dict):
     for port in ('claims','findings'):
      if port in output and any(not isinstance(x.get('id'),str) or not x['id'].startswith(f['node_id']+':') for x in output[port]):
       v=dict(K=False,E=False,Q=None,safe_to_consume=False)
   except (KeyError,TypeError,ValueError,AttributeError):
    v=dict(K=False,E=False,Q=None,safe_to_consume=False)
   # Independent fixed inputs: a normal model failure cannot poison another cell.
   rows.append(dict(cell=i,node=f['node_id'],model=rec['model'],
        status='CONTRACT_COMMITTED' if v['safe_to_consume'] else 'MODEL_FAILURE',
        output=output,verdict=v,usage=result['usage'],actual_cash_settlement=None,
        semantic_quality=None,reliability_guarantee=None))
   write(out/(f'CELL_{i}.json'),rows[-1])
 finally:
  result=dict(origin=origin,rows=rows,stop=stop,ledger=guard.snapshot(),
    terminal_quality=None,dynamic_pi_benefit='NOT_EVALUATED',
    note='Calibration only. Fixed historical upstreams. No downstream chaining or evaluation arms.')
  write(out/'RESULT.json',result)
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--authorization',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
 if a.execute and (not a.authorization or not a.output):p.error('execution needs authorization and output')
 issues=preflight(a.authorization if a.execute else None)
 if issues:print(json.dumps({'status':'HOLD','issues':issues}));return 2
 if not a.execute:print(json.dumps({'local_preflight':'PASS','live_authorized':False}));return 0
 if a.output.exists():raise FileExistsError('OUTPUT_EXISTS')
 # Exclusive durable claim; no restart or alternative output bypass.
 write(ROOT/'RUN_ONCE.lock',{'authorization_sha256':sha(a.authorization),'batch_lock_sha256':sha(ROOT/'BATCH_LOCK.json'),'started_at_unix':time.time()})
 execute(a.output);return 0
if __name__=='__main__':raise SystemExit(main())
