"""Offline, explicit independent adjudication. Never an LLM judge.
Export blinded full outputs; import signed per-fact decisions. Raw scores unchanged.
"""
import argparse, hashlib, json, random
from pathlib import Path
from paid_transport import write
from reference_policy import metrics

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
 if not d.get('reviewer') or not d.get('date') or type(d.get('independent')) is not bool:raise ValueError('REVIEW_PENDING')
 context=json.loads((run/'RUN_CONTEXT.json').read_text())
 scopefile=run/'REFERENCE_SCOPE.json'
 if hashlib.sha256(scopefile.read_bytes()).hexdigest()!=context['reference_decisions_sha256']:raise ValueError('PRE_EXECUTION_REFERENCE_SCOPE_CHANGED')
 refs=json.loads(scopefile.read_text())['targets']['evaluation']
 if set(d['outputs'])!=set(mapping):raise ValueError('MISSING_OR_EXTRA_OUTPUTS')
 rows=[]
 for k,m in mapping.items():
  r=d['outputs'][k]
  if hashlib.sha256((run/(m['pair']+'_'+m['arm']+'.RAW.json')).read_bytes()).hexdigest()!=m['raw_sha256']:raise ValueError('RAW_OUTPUT_CHANGED')
  if r.get('blind_sha256')!=m['blind_sha256'] or hashlib.sha256((run/'blind_review'/(k+'.json')).read_bytes()).hexdigest()!=m['blind_sha256']:raise ValueError('OUTPUT_HASH_MISMATCH')
  measures=metrics(refs,r['facts'])
  extras_complete=r.get('extra_assertions_review_complete') is True
  for field in ('additional_false_assertions','additional_unsupported_assertions'):
   if extras_complete and (type(r.get(field)) is not int or r[field]<0):raise ValueError('EXTRA_ASSERTIONS_PENDING')
  independent=measures['INDEPENDENT_ADJUDICATED']
  full=(d['independent'] and len(independent['effective_resolved_ids'])==6 and extras_complete)
  if full:measures['full_terminal_Q']=independent['partial_effective_score']
  # No extrapolation of non-independent or partial quality into task success.
  success=(measures['full_terminal_Q']==1 and not r['additional_false_assertions'] and not r['additional_unsupported_assertions']) if full else None
  rows.append(dict(pair=m['pair'],arm=m['arm'],quality=measures,terminal_reference_success=success,
                   output_review_provenance={'reviewer':d['reviewer'],'date':d['date'],'independent':d['independent']},
                   additional_false_assertions=r.get('additional_false_assertions') if extras_complete else None,
                   additional_unsupported_assertions=r.get('additional_unsupported_assertions') if extras_complete else None,
                   raw_sha256=m['raw_sha256']))
 result=json.loads((run/'RESULT.json').read_text())
 for p in result['pairs']:
  for a in p['arms']:
   match=next((r for r in rows if r['pair']==p['pair_id'] and r['arm']==a['arm']),None)
   a['score_with_provenance']=match
   if not a.get('task_complete'):a['terminal_success']=False
   else:a['terminal_success']=match['terminal_reference_success'] if match else None
  scored=[a['score_with_provenance'] for a in p['arms']]
  p['partial_quality_comparability']={tier:bool(all(scored) and scored[0]['quality'][tier]['resolved_ids']==scored[1]['quality'][tier]['resolved_ids'] and scored[0]['quality'][tier]['resolved_ids']) for tier in ('INDEPENDENT_ADJUDICATED','PROJECT_REVIEWED_NONINDEPENDENT')}
 result['adjudication_file_sha256']=hashlib.sha256(Path(decisions).read_bytes()).hexdigest()
 result['terminal_quality_status']='TIERED_EXPLORATORY_SCORING; FULL_Q_MAY_BE_UNIDENTIFIABLE'
 result['algorithm_benefit']='NO_NET_QUALITY_OR_PARETO_CLAIM_WITHOUT_FULL_COMPARABLE_QUALITY'
 write(run/'SCORED_RESULT.json',result)
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--decisions');a=p.parse_args()
 print(score(a.run,a.decisions)['terminal_quality_status'] if a.decisions else export(a.run))
