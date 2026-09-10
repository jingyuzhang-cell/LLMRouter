"""400-query MMLU panel: fold-local opportunity selection plus random coverage."""
import json
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import StratifiedGroupKFold
from .data import load_cohort,sha
from .diagnose_rank_signal import load_inputs

ROOT=Path(__file__).resolve().parents[1]


def main():
 source=ROOT/'router_v2/objective_verified_20260910';f,x,ds=load_inputs(source)
 cohort,_=load_cohort(ROOT/'data/cohort_full_v2');ids=f['ids'];y=f['quality'];folds=f['folds']
 gp=ROOT/'router_v2/contamination_audit_20260910b/PROMPT_GROUPS.json';g=json.loads(gp.read_text());groups=np.array([g['groups'][q] for q in ids])
 selections={};union=set();rng=np.random.default_rng(20260911)
 for fold in sorted(np.unique(folds)):
  tr=np.flatnonzero(folds!=fold);va=np.flatnonzero(folds==fold)
  if set(groups[tr])&set(groups[va]):raise ValueError('Group overlap')
  pred=np.zeros((len(tr),4))
  for a,b in StratifiedGroupKFold(3,shuffle=True,random_state=42).split(x[tr],ds[tr],groups[tr]):pred[b]=Ridge(alpha=20.).fit(x[tr[a]],y[tr[a]]).predict(x[tr[b]])
  candidates=np.flatnonzero(ds[tr]=='mmlupro');ym=y[tr];margin=ym[:,3]-ym[:,2];pm=np.abs(pred[:,3]-pred[:,2]);chosen={}
  def add(indices,tag):
   for j in indices:chosen.setdefault(str(ids[tr[j]]),[]).append(tag)
  for sign,tag in [(1,'reasoning_raw_advantage'),(-1,'large_raw_advantage')]:
   pool=candidates[margin[candidates]*sign>0];add(pool[np.argsort(pm[pool],kind='stable')][:30],tag)
  best=int(ym[candidates].mean(0).argmax());pool=candidates[ym[candidates,2:4].max(1)>ym[candidates,best]]
  add(pool[np.argsort(pm[pool],kind='stable')][:30],'train_opportunity')
  add(candidates[np.argsort(pm[candidates],kind='stable')][:30],'near_predicted_tie')
  # Uniform random supplement is not filtered by raw correctness.
  for j in rng.permutation(candidates):
   if len(chosen)>=160:break
   if str(ids[tr[j]]) not in chosen:add([j],'random_coverage')
  selections[str(fold)]=chosen;union.update(chosen)
 if len(union)>400:raise ValueError('Initial fold panel exceeds frozen 400-query budget')
 # Fill to exactly 400 without consulting additional outcomes. An added query
 # enters only its assigned outer training fold, not every eligible fold.
 remaining=rng.permutation(np.flatnonzero((ds=='mmlupro')&~np.isin(ids,list(union))))
 for j in remaining:
  if len(union)>=400:break
  eligible=[str(int(v)) for v in np.unique(folds) if v!=folds[j]]
  fold=min(eligible,key=lambda z:(len(selections[z]),int(z)))
  selections[fold][str(ids[j])]=['random_budget_fill'];union.add(str(ids[j]))
 if len(union)!=400:raise ValueError('Could not meet panel size')
 out=ROOT/'router_v2/mmlu_utility_panel_400';out.mkdir(exist_ok=False)
 rows=[]
 for i,q in enumerate(sorted(union)):
  c=cohort[q];rows.append(dict(**{k:c[k] for k in ['query_id','query','dataset','task_type']},panel_index=i,
   strata=sorted({t for v in selections.values() for t in v.get(q,[])}),training_folds=[k for k,v in selections.items() if q in v],planned_repeats_per_slot=5))
 (out/'PANEL.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
 (out/'FOLD_SELECTION.json').write_text(json.dumps(selections,indent=2)+'\n')
 manifest=dict(role='fold_local_mmlu_expected_utility',n_panel=400,repeats=5,temperature=.7,top_p=1.,slots=['large','reasoning'],
  source=str(source),groups=str(gp),groups_sha256=sha(gp),source_files={n:sha(source/n) for n in ['PROTOCOL.json','RESULTS.json','OOF.npz']},
  selector_sha256=sha(__file__),fold_sizes={k:len(v) for k,v in selections.items()},
  target='Expected quality difference; raw token and latency differences retained separately; delta U = delta Q - lambda delta C - mu delta L only after units/weights are fixed.',
  uncertainty='Empirical Bernoulli variance and uncertainty of mean are separate; independent slot means imply summed variances for their difference.',
  failure_policy='At most two transport attempts per new generation, no correctness-based retries. Failure remains missing, no automatic unlimited restarts.',
  selection='Per outer training fold: up to30 raw-advantage queries per direction,30 opportunity,30 near-ties; uniform fill to160; union filled to400 with assigned-fold random queries.',
  limits=['Train-only development; no use of outer-held labels for its sample selection or training.',
          'Temperature .7 repeat labels are a different target distribution from historical temperature0 outcomes.',
          'No hard stable label filtering; all complete repeat counts are supervision. Monetary cost not yet verified.'],
  files={n:sha(out/n) for n in ['PANEL.jsonl','FOLD_SELECTION.json']})
 (out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps({'n':400,'fold_sizes':manifest['fold_sizes']},indent=2))

if __name__=='__main__':main()
