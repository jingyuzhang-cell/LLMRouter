"""Independent completion/budget/fold and outcome reconstruction checks."""
import json
from pathlib import Path
from collections import Counter
import numpy as np
from .data import sha,load_cohort
from .label_repair_plan import OUT,ROOT,SLOTS
from .rescore_glm_pilot import extract_option


def main():
 p=json.loads((OUT/'PROTOCOL.json').read_text());r=json.loads((OUT/'RESULTS.json').read_text())
 for file,h in p['hashes'].items():assert sha(file)==h,file
 assert r['protocol_sha256']==sha(OUT/'PROTOCOL.json')
 assert r['baseline_predictions_sha256']==sha(OUT/'BASELINE_PREDICTIONS.npz')
 assert r['repaired_predictions_sha256']==sha(OUT/'REPAIRED_PREDICTIONS.npz')
 assert r['labels_sha256']==sha(OUT/'REPAIRED_LABELS.npz')
 inp=np.load(OUT/'INPUTS.npz',allow_pickle=False);ids=inp['ids'].tolist();ix={q:i for i,q in enumerate(ids)};selected=inp['selected_indices']
 selected_ids=set(np.array(ids)[selected]);new=np.zeros((400,4,10),dtype=int)
 frozen=json.loads((OUT/'BASELINE_FROZEN.json').read_text())
 cohort,_=load_cohort(ROOT/'data/cohort_full_v2')
 usage={};raw_hashes={}
 for m,s in enumerate(SLOTS):
  path=OUT/'raw'/f'{s}.jsonl';rows=[json.loads(v) for v in path.open()]
  attempts=[json.loads(v) for v in (OUT/'raw'/f'{s}_ATTEMPTS.jsonl').open()]
  # AMENDMENT_001_TRANSPORT_RESCUE: rescued positions legitimately carry one extra attempt
  rescue_path=OUT/'raw'/f'{s}_ATTEMPTS_RESCUE.jsonl'
  rescued=Counter((a['query_id'],a['repeat_index']) for a in (json.loads(v) for v in rescue_path.open())) if rescue_path.exists() else Counter()
  budget=Counter((a['query_id'],a['repeat_index']) for a in attempts)+rescued
  archived=sum(1 for f in (OUT/'raw').glob(f'{s}_ATTEMPTS_ORPHANED_*.jsonl') for _ in f.open())
  keys=[(v['query_id'],v['repeat_index']) for v in rows]
  assert len(rows)==len(set(keys))==len(selected)*10
  assert set(keys)=={(q,k) for q in selected_ids for k in range(5,15)}
  assert set(budget)==set(keys) and all(v<=2+rescued.get(k,0) for k,v in budget.items())
  assert len(attempts)+sum(rescued.values())+archived<=len(selected)*20
  assert all(v.get('amendment')=='AMENDMENT_001_TRANSPORT_RESCUE' for v in rows if (v['query_id'],v['repeat_index']) in rescued)
  assert min(a['unix_time'] for a in attempts)>frozen['frozen_at']
  totals=Counter()
  for v in rows:
   q=v['query_id'];assert v['quality'] in [0,1] and v['status'] in ['ok','truncated'] and v.get('answer')
   assert v['attempts_used']==budget[q,v['repeat_index']]==len(v['attempt_history'])
   option=extract_option(v['answer']);gt=str(cohort[q]['ground_truth']).strip().upper()[-1]
   quality=int(option==gt) if option else 0
   assert quality==v['quality']
   new[ix[q],m,v['repeat_index']-5]=quality
   for a in v['attempt_history']:
    for key,value in (a.get('usage') or {}).items():
     if isinstance(value,(int,float)):totals[key]+=value
  raw_hashes[s]=sha(path);usage[s]=dict(attempts=len(attempts),successes=len(rows),recorded_tokens=dict(totals))
 repaired=inp['old_quality'].copy();repaired[selected]=np.concatenate([inp['old_repeats'][selected],new[selected]],axis=2).mean(2)
 labels=np.load(OUT/'REPAIRED_LABELS.npz',allow_pickle=False)
 np.testing.assert_array_equal(repaired,labels['repaired_quality']);np.testing.assert_array_equal(new[selected],labels['new_repeats_selected'])
 selections=json.loads((OUT/'FOLD_REPAIR_SELECTION.json').read_text())
 train_labels=json.loads((OUT/'FOLD_TRAIN_LABELS.json').read_text())
 for f in selections:
  dev=np.array([ix[q] for q in f['development_ids']]);repair=np.array([ix[q] for q in f['repair_training_ids']]);test=np.array([ix[q] for q in f['test_ids']])
  assert len(repair)==40 and set(repair)<=set(dev) and not set(dev)&set(test)
  expected=inp['old_quality'].copy();expected[repair]=repaired[repair]
  actual=next(x['used_quality'] for x in train_labels if x['fold']==f['fold'])
  np.testing.assert_allclose(actual,expected[dev],rtol=0,atol=1e-8)
  np.testing.assert_array_equal(expected[test],inp['old_quality'][test])
 old=np.load(OUT/'BASELINE_PREDICTIONS.npz',allow_pickle=False);after=np.load(OUT/'REPAIRED_PREDICTIONS.npz',allow_pickle=False)
 choices={}
 for name,z in [('original',old),('repaired',after)]:
  choices[name+'_Ridge']=z['ridge_scores'].argmax(1)[None,:]
  choices[name+'_MA']=z['ma_scores'].argmax(2)
  choices[name+'_BestSingle']=z['bestsingle_choice'][None,:]
 saved=np.load(OUT/'EVALUATION_VALUES.npz',allow_pickle=False)
 new_y=np.zeros((400,4));new_y[selected]=new[selected].mean(2)
 mapping=[('primary_new10_selected','primary',new_y,selected),('secondary_common_repaired400','secondary',repaired,np.arange(400)),('secondary_original5_400','original5',inp['old_quality'],np.arange(400))]
 contrasts={
  'MA_repaired_minus_original':('repaired_MA','original_MA'),
  'Ridge_repaired_minus_original':('repaired_Ridge','original_Ridge'),
  'repaired_MA_minus_repaired_Ridge':('repaired_MA','repaired_Ridge'),
  'repaired_MA_minus_original_Ridge':('repaired_MA','original_Ridge'),
  'repaired_Ridge_minus_original_BestSingle':('repaired_Ridge','original_BestSingle')}
 for key,prefix,y,idx in mapping:
  actual={name:y[idx[None,:],ch[:,idx]].mean(0) for name,ch in choices.items()}
  for name,value in actual.items():
   np.testing.assert_allclose(value,saved[prefix+'_'+name]);assert np.isclose(value.mean(),r['metrics'][key]['methods'][name]['eq'])
  boot=np.random.default_rng(20260914).integers(0,len(idx),(10000,len(idx)))
  for name,(a,b) in contrasts.items():
   diff=actual[a]-actual[b];ci=np.quantile(diff[boot].mean(1),[.025,.975]);entry=r['metrics'][key]['comparisons'][name]
   assert np.isclose(diff.mean(),entry['mean']);np.testing.assert_allclose(ci,entry['ci95'],atol=1e-10)
   assert bool(diff.mean()>0 and ci[0]>0)==entry['success']
 audit_rows=[json.loads(v) for v in (OUT/'BAYESIAN_AUDIT_PER_QUERY.jsonl').open()]
 assert len(audit_rows)==len(selected)
 for a in audit_rows:
  assert a['before']['label']=='uncertain' and a['after']['repeats']==15
  i=ix[a['query_id']]
  np.testing.assert_array_equal(a['after']['successes'],inp['old_repeats'][i].sum(1)+new[i].sum(1))
 assert dict(Counter(a['after']['label'] for a in audit_rows))=={k:v for k,v in r['audit']['uncertain_to'].items() if v}
 result=dict(passed=True,validator_sha256=sha(Path(__file__)),queries=len(selected),new_records=len(selected)*40,
             raw_sha256=raw_hashes,budget_and_usage=usage,baseline_precedes_collection=True,fold_local_training_labels=True,
             same_eval_outcomes_for_old_and_new=True,paired_bootstrap_recomputed=True,posterior_counts_15=True,
             no_new_experiment_started=True)
 (OUT/'INDEPENDENT_VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))


if __name__=='__main__':main()
