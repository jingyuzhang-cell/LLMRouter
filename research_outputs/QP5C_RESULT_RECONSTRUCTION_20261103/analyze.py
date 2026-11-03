import sys,json,hashlib,collections
from pathlib import Path
from statistics import mean
sys.dont_write_bytecode=True
base=Path('/root/research_outputs/static_pi/stage_d/quality_phase_v1');out=Path(__file__).parent
sys.path.insert(0,str(base))
import qp5c_runner as R
names=['QP5C_LEDGER.jsonl','QP5C_PROGRESS.json','QP5C_RESULTS.json','QP5C_PREREGISTRATION_V2_1.md','QP5C_CAUSAL_DESIGN_REVIEW.md','qp5c_runner.py']
snap={n:(base/n).read_bytes() for n in names}
(out/'SOURCE_SNAPSHOT.json').write_text(json.dumps({n:{'sha256':hashlib.sha256(v).hexdigest(),'text':v.decode()} for n,v in snap.items()},ensure_ascii=False,indent=2))
ledger=[json.loads(s) for s in snap['QP5C_LEDGER.jsonl'].decode().splitlines()]; hist=[json.loads(s) for s in (base/'QP4_LEDGER.jsonl').read_text().splitlines()]
summary=[];scores=[]
for i,x in enumerate(ledger):
 parts=x['purpose'].split('|');summary.append(dict(index=i+1,task=parts[1],arm=parts[2],repeat=int(next(t[1:] for t in parts[3:] if t.startswith('r'))),node=parts[-1],retry='R' in parts,ts=x['ts'],sha=x['prompt_sha256'],cost=x['accounting_yuan'],latency=x['latency_s'],tokens=x['usage'],stop=x['stop_reason'],purpose=x['purpose']))
 if parts[-1]=='p':
  try: sc=R.Q1.score_task(R.F.load_contract(parts[1]),R.extract_any(x['text']));scores.append(dict(index=i+1,task=parts[1],arm=parts[2],rep=summary[-1]['repeat'],score=sc))
  except Exception as e:scores.append(dict(index=i+1,error=str(e)))
# Reconstruct each arm from historical frozen E and recorded calls only; callback cannot dispatch.
replays=[];histmap={x['purpose']:x for x in hist}
for t in R.F.TASKS:
 for rep in [1,2]:
  for arm in ['C1','C2']+(['C0'] if (t,rep) in R.C0_CELLS else []):
   seen=[]
   def call(node,system,user,mt,purpose):
    from stage_d_v2_transport import build_request
    sha=hashlib.sha256(json.dumps(build_request('glm53flash',system,user,mt),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    candidates=[(i,x) for i,x in enumerate(ledger) if x['purpose']==purpose and x['prompt_sha256']==sha]
    if not candidates:raise ValueError('MISSING_EXACT_RECORDED_REQUEST '+purpose)
    i,x=candidates[0];seen.append(i+1);return x['text']
   try:
    result=R.run_arm(arm,t,rep,R.F.load_contract(t),call,histmap)
    result.pop('e0',None);result.pop('e1',None);result.pop('sink',None)
    replays.append(dict(task=t,rep=rep,arm=arm,status='RECORDED_CHAIN_RECONSTRUCTED',indices=seen,result=result))
   except Exception as e: replays.append(dict(task=t,rep=rep,arm=arm,status='INCOMPLETE',indices=seen,error=str(e)))
index={(x['task'],x['rep'],x['arm']):x for x in replays if x['status']=='RECORDED_CHAIN_RECONSTRUCTED'}
pairs=[]
for t in R.F.TASKS:
 for rep in [1,2]:
  a=index.get((t,rep,'C1'));b=index.get((t,rep,'C2'))
  pairs.append(dict(task=t,rep=rep,delta=b['result']['q']-a['result']['q'] if a and b else None,C1=a['result']['q'] if a else None,C2=b['result']['q'] if b else None))
noise=[]
for t,rep in sorted(R.C0_CELLS):
 a=index.get((t,rep,'C1'));b=index.get((t,rep,'C0'))
 noise.append(dict(task=t,rep=rep,delta=b['result']['q']-a['result']['q'] if a and b else None))
data=dict(n_records=len(ledger),first107={'n':min(107,len(ledger)),'cost':sum(x['cost'] for x in summary[:107]),'seconds_sum':sum(x['latency'] for x in summary[:107])},by_arm={a:dict(n=sum(x['arm']==a for x in summary),cost=sum(x['cost'] for x in summary if x['arm']==a),latency_sum=sum(x['latency'] for x in summary if x['arm']==a)) for a in ['C1','C2','C0']},call_order=summary,terminal_scores=scores,recorded_chain_replay=replays,pairs=pairs,noise=noise,total_cost=sum(x['cost'] for x in summary),duplicates={k:v for k,v in collections.Counter(x['purpose'] for x in ledger).items() if v>1})
(out/'RECONSTRUCTION.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps({k:data[k] for k in ['n_records','first107','by_arm','pairs','noise','total_cost','duplicates']},ensure_ascii=False,indent=2));print('replays',collections.Counter(x['status'] for x in replays));print('errors',[(x['task'],x['rep'],x['arm'],x.get('error')) for x in replays if x['status']=='INCOMPLETE'])
