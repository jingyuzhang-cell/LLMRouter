"""Aggregate explicitly adjudicated Silver review; does not pretend to infer semantics.
No model or network invocation. Frozen original scorer remains untouched.
"""
import hashlib,json,sys
from pathlib import Path
P=Path(__file__).resolve().parent

def aggregate(node,review,response_bytes):
 rubric=json.loads((P/'SILVER_RUBRIC.json').read_text());scope=rubric['per_node_scope'][node]
 if review.get('response_sha256')!=hashlib.sha256(response_bytes).hexdigest():raise ValueError('RESPONSE_HASH_MISMATCH')
 if not review.get('reviewer') or review.get('independent') is not False:raise ValueError('NON_INDEPENDENT_REVIEW_ID_REQUIRED')
 items=review.get('items',[])
 if len({i['id'] for i in items})!=len(items):raise ValueError('DUPLICATE_ITEM')
 if any(i['id'] not in scope for i in items):raise ValueError('OUT_OF_SCOPE')
 indexed={i['id']:i for i in items};rows=[]
 for tid in scope:
  i=indexed.get(tid,{'id':tid,'factual':'UNKNOWN','evidence':'UNKNOWN','rationale':'Not adjudicated'})
  if i['factual'] not in ['CORRECT','WRONG','UNKNOWN'] or i['evidence'] not in ['SUPPORTED','UNSUPPORTED','UNKNOWN']:raise ValueError('BAD_VERDICT')
  if not i.get('rationale'):raise ValueError('RATIONALE_REQUIRED')
  if i['evidence']=='SUPPORTED' and not i.get('evidence_ids'):raise ValueError('SUPPORT_IDS_REQUIRED')
  rows.append(i)
 n=len(rows);c=sum(i['factual']=='CORRECT' for i in rows);w=sum(i['factual']=='WRONG' for i in rows);u=n-c-w
 good=sum(i['factual']=='CORRECT' and i['evidence']=='SUPPORTED' for i in rows)
 bad=sum(i['factual']=='WRONG' or i['evidence']=='UNSUPPORTED' for i in rows)
 pending=n-good-bad
 return {'node':node,'reference_level':'NON_INDEPENDENT_SILVER','full_frozen_Q':None,'denominator':n,'fact_correct':c,'fact_wrong':w,'fact_unknown':u,'fact_coverage':(c+w)/n,'fact_accuracy_on_reviewed':c/(c+w) if c+w else None,'fact_bounds':[c/n,(c+u)/n],'supported_correct':good,'supported_incorrect_or_unsupported':bad,'support_unknown':pending,'supported_bounds':[good/n,(good+pending)/n],'rows':rows,'K_not_inferred':True,'source_support_is_reviewed_not_computed_from_ID_presence':True}
if __name__=='__main__':
 if len(sys.argv)!=4:raise SystemExit('Usage: score_review.py NODE REVIEW.json RAW_RESPONSE_FILE')
 print(json.dumps(aggregate(sys.argv[1],json.loads(Path(sys.argv[2]).read_text()),Path(sys.argv[3]).read_bytes()),ensure_ascii=False,indent=2))
