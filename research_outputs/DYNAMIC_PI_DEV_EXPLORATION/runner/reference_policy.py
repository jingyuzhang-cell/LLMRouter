"""Transparent exploration references; UNKNOWN is never imputed as failure."""
import hashlib,json
from pathlib import Path
TIERS=('INDEPENDENT_ADJUDICATED','PROJECT_REVIEWED_NONINDEPENDENT','PENDING')
IDS={f'T{i}' for i in range(1,7)}
def validate(root,ref):
 root=Path(root)
 if ref.get('mode')!='DEVELOPMENT_EXPLORATION' or ref.get('partial_scoring_policy_accepted') is not True:
  raise ValueError('REFERENCE_POLICY_NOT_ACCEPTED')
 for role in ('calibration','evaluation'):
  if ref.get('reference_hashes',{}).get(role)!=hashlib.sha256((root/role/'REFERENCE_PENDING.json').read_bytes()).hexdigest():raise ValueError('REFERENCE_HASH_MISMATCH')
  targets=ref.get('targets',{}).get(role,{})
  if set(targets)!=IDS:raise ValueError('REFERENCE_SCOPE_CHANGED')
  for f in targets.values():
   if f.get('tier') not in TIERS:raise ValueError('INVALID_REFERENCE_TIER')
   if f['tier']!='PENDING':
    if not all(f.get(k) for k in ('reviewer','date','rationale','evidence_locator')):raise ValueError('REVIEW_PROVENANCE_MISSING')
    if f['tier']=='INDEPENDENT_ADJUDICATED' and f.get('independent_of_reference_author') is not True:raise ValueError('INDEPENDENCE_NOT_DECLARED')
 return ref

def metrics(reference,facts):
 if set(facts)!=IDS:raise ValueError('FACT_SCOPE_CHANGED')
 output={}
 for tier in TIERS[:2]:
  eligible=[i for i in sorted(IDS) if reference[i]['tier']==tier]
  known=[];effective=[];unknown=[]
  for i in eligible:
   f=facts[i]
   if f.get('content') not in ('CORRECT','WRONG','MISSING','UNKNOWN','PENDING') or f.get('support') not in ('SUPPORTED','UNSUPPORTED','UNKNOWN','PENDING'):raise ValueError('INVALID_OUTPUT_JUDGMENT')
   if f['content'] in ('UNKNOWN','PENDING'):unknown.append(i);continue
   if not f.get('reason'):raise ValueError('OUTPUT_JUDGMENT_REASON_REQUIRED')
   known.append(i)
   if f['content']!='CORRECT' or f['support'] in ('SUPPORTED','UNSUPPORTED'):effective.append(i)
  correct=sum(facts[i]['content']=='CORRECT' for i in known)
  supported=sum(facts[i]['content']=='CORRECT' and facts[i]['support']=='SUPPORTED' for i in effective)
  output[tier]={'reference_ids':eligible,'reference_coverage':len(eligible)/6,'resolved_ids':known,'resolved_coverage':len(known)/6,
                'content_unknown_ids':unknown,'correct_count':correct,'partial_fact_score':correct/len(known) if known else None,
                'partial_effective_score':supported/len(effective) if effective else None,'effective_resolved_ids':effective,
                'eligible_fact_bounds':[correct/len(eligible),(correct+len(unknown))/len(eligible)] if eligible else None}
 output['pending_reference_ids']=[i for i in sorted(IDS) if reference[i]['tier']=='PENDING']
 output['full_terminal_Q']=None # issued only with full, independent output adjudication
 return output
