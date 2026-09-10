"""Fixed train-only fine-task baseline and query+subject feature diagnosis."""
import json,re
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from .data import load_cohort,sha
from .diagnose_rank_signal import load_inputs
from .report_gap_recovery import gap_summary


def main():
 source=Path('router_v2/objective_verified_20260910');f,x,ds=load_inputs(source)
 cohort,_=load_cohort('data/cohort_full_v2');ids=f['ids'];y=f['quality'];folds=f['folds'];n=len(y);ix=np.arange(n)
 subjects=[]
 for q in ids:
  m=re.match(r'Answer the following (.+?) question\.',cohort[q]['query'])
  subjects.append(m.group(1).lower() if m else '__no_subject__')
 subjects=np.array(subjects)
 gp=Path('router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json');g=json.loads(gp.read_text());groups=np.array([g['groups'][q] for q in ids])
 choices={k:np.zeros(n,int) for k in ['SubjectMeanShrink20','RidgePlusSubject']}
 for fold in np.unique(folds):
  tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
  if set(groups[tr])&set(groups[va]):raise ValueError('Group leakage')
  choices['SubjectMeanShrink20'][va]=f['DatasetBest'][va]
  for s in set(subjects[tr])-{'__no_subject__'}:
   a=tr[subjects[tr]==s];b=va[subjects[va]==s];population=y[tr][ds[tr]=='mmlupro'].mean(0)
   mean=(y[a].sum(0)+20*population)/(len(a)+20)
   choices['SubjectMeanShrink20'][b]=mean.argmax()
  names=sorted(set(subjects[tr]));st=np.array([[s==k for k in names] for s in subjects[tr]],float);sv=np.array([[s==k for k in names] for s in subjects[va]],float)
  model=Ridge(alpha=20.).fit(np.concatenate([x[tr],st],axis=1),y[tr])
  choices['RidgePlusSubject'][va]=model.predict(np.concatenate([x[va],sv],axis=1)).argmax(1)
 base=y[ix,f['DatasetBest']];opp=y.max(1)-base
 results={k:dict(quality=float(y[ix,c].mean()),**gap_summary(y[ix,c]-base,opp,groups)) for k,c in choices.items()}
 out=Path('router_v2/subject_gap_probe_20260910');out.mkdir(exist_ok=False)
 np.savez_compressed(out/'CHOICES.npz',ids=ids,**choices)
 protocol=dict(role='original_train_grouped_subject_probe',ridge_alpha=20,subject_prior_strength=20,subject_feature_weight=1,
  description='Parse subject from query header; shrink subject means toward outer-train MMLU means. No threshold or hyperparameter selection.',
  caveats=['SubjectMean is a stronger task-level diagnostic baseline, not evidence of query-model compatibility.',
           'Exploratory original-train OOF only; no independent confirmation.'],
  inputs={str(p):sha(p) for p in [source/'RESULTS.json',gp,Path(__file__)]})
 (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2));(out/'RESULTS.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))

if __name__=='__main__':main()
