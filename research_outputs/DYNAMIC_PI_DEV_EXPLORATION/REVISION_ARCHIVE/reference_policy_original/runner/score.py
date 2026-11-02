"""Offline, explicit independent adjudication. Never an LLM judge.
Export blinded full outputs; import signed per-fact decisions. Raw scores unchanged.
"""
import argparse, hashlib, json, random
from pathlib import Path
from paid_transport import write

def export(run):
 run=Path(run);result=json.loads((run/'RESULT.json').read_text());out=run/'blind_review';out.mkdir(exist_ok=False)
 items=[]
 for pair in result['pairs']:
  for arm in pair['arms']:
   if arm.get('full_output_file'):
    f=run/arm['full_output_file'];raw=json.loads(f.read_text())
    items.append((pair['pair_id'],arm['arm'],raw['outputs'],hashlib.sha256(f.read_bytes()).hexdigest()))
 random.Random(20261030).shuffle(items)
 mapping={}
 for i,(pair,arm,output,sha) in enumerate(items,1):
  bid=f'OUTPUT_{i:02d}';write(out/(bid+'.json'),{'id':bid,'full_output':output})
  mapping[bid]={'pair':pair,'arm':arm,'raw_sha256':sha,'blind_sha256':hashlib.sha256((out/(bid+'.json')).read_bytes()).hexdigest()}
 write(run/'PRIVATE_REVIEW_MAPPING.json',mapping)
 write(out/'DECISIONS_TEMPLATE.json',{'reviewer':None,'independent':False,'date':None,'coverage_complete':False,'outputs':{k:{'blind_sha256':v['blind_sha256'],'facts':{f'T{j}':{'content':'PENDING','support':'PENDING','reason':None} for j in range(1,7)},'additional_false_assertions':None,'additional_unsupported_assertions':None,'extra_assertions_review_complete':False} for k,v in mapping.items()}})
 return len(items)

def score(run,decisions):
 run=Path(run);d=json.loads(Path(decisions).read_text());mapping=json.loads((run/'PRIVATE_REVIEW_MAPPING.json').read_text())
 if not d.get('reviewer') or not d.get('date') or d.get('independent') is not True or not d.get('coverage_complete'):raise ValueError('REVIEW_PENDING')
 if set(d['outputs'])!=set(mapping):raise ValueError('MISSING_OR_EXTRA_OUTPUTS')
 rows=[]
 for k,m in mapping.items():
  r=d['outputs'][k]
  if hashlib.sha256((run/(m['pair']+'_'+m['arm']+'.RAW.json')).read_bytes()).hexdigest()!=m['raw_sha256']:raise ValueError('RAW_OUTPUT_CHANGED')
  if r.get('blind_sha256')!=m['blind_sha256'] or hashlib.sha256((run/'blind_review'/(k+'.json')).read_bytes()).hexdigest()!=m['blind_sha256']:raise ValueError('OUTPUT_HASH_MISMATCH')
  if set(r['facts'])!={f'T{j}' for j in range(1,7)}:raise ValueError('FACT_DENOMINATOR_CHANGED')
  for f in r['facts'].values():
   if f['content'] not in ('CORRECT','WRONG','MISSING','UNKNOWN') or f['support'] not in ('SUPPORTED','UNSUPPORTED','UNKNOWN') or not f.get('reason'):raise ValueError('UNADJUDICATED_FACT')
  for field in ('additional_false_assertions','additional_unsupported_assertions'):
   if type(r.get(field)) is not int or r[field]<0:raise ValueError('EXTRA_ASSERTIONS_PENDING')
  if not r.get('extra_assertions_review_complete'):raise ValueError('EXTRA_ASSERTIONS_PENDING')
  fs=list(r['facts'].values());correct=sum(f['content']=='CORRECT' for f in fs)
  unk=sum(f['content']=='UNKNOWN' for f in fs)
  supported=sum(f['content']=='CORRECT' and f['support']=='SUPPORTED' for f in fs)
  unknown_effective=sum(f['content']=='UNKNOWN' or (f['content']=='CORRECT' and f['support']=='UNKNOWN') for f in fs)
  rows.append({'pair':m['pair'],'arm':m['arm'],'Q_fact':None if unk else correct/6,'Q_fact_bounds':[correct/6,(correct+unk)/6],
               'Q_effective':None if unknown_effective else supported/6,'Q_effective_bounds':[supported/6,(supported+unknown_effective)/6],
               'additional_false_assertions':r['additional_false_assertions'],'additional_unsupported_assertions':r['additional_unsupported_assertions'],
               'terminal_reference_success':supported==6 and not r['additional_false_assertions'] and not r['additional_unsupported_assertions'],
               'raw_sha256':m['raw_sha256']})
 result=json.loads((run/'RESULT.json').read_text())
 for p in result['pairs']:
  for a in p['arms']:
   match=next((r for r in rows if r['pair']==p['pair_id'] and r['arm']==a['arm']),None)
   if match:a['independent_score']=match;a['terminal_success']=bool(a.get('task_complete')) and match['terminal_reference_success']
   else:a['independent_score']=None;a['terminal_success']=False
 result['adjudication_file_sha256']=hashlib.sha256(Path(decisions).read_bytes()).hexdigest()
 result['terminal_quality_status']='INDEPENDENT_MANUAL_ADJUDICATION_IMPORTED'
 result['algorithm_benefit']='REQUIRES_PAIRED_Q_COST_LATENCY_INTERPRETATION; NO_AUTOMATIC_POSITIVE_CLAIM'
 write(run/'SCORED_RESULT.json',result)
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--decisions');a=p.parse_args()
 print(score(a.run,a.decisions)['terminal_quality_status'] if a.decisions else export(a.run))
