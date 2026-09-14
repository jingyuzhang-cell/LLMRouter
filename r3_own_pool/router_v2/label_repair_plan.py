"""Final controlled label-resolution intervention; selection uses no router scores."""
import argparse
from functools import lru_cache
import importlib.metadata
import json
from pathlib import Path
import time
import numpy as np
from scipy.stats import betabinom

from .data import sha, load_cohort
from .run_e9_routing_label_audit import p_greater, p_gain, p_tie, classify

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'router_v2/label_repair_experiment'
E9=ROOT/'router_v2/e9_routing_label_audit'
E5=ROOT/'router_v2/e5_independent_query_learning_curve'
SOURCE=ROOT/'router_v2/experiment_repeat_compatibility_400_fold_local'
LABELS=ROOT/'data/repeat_compatibility_400_rescore_v1/EXPECTED_UTILITY_LABELS.jsonl'
COHORT=ROOT/'data/cohort_full_v2'
SLOTS=['medium','large','coder','reasoning']
QUOTA=40
EXTRA=10
MA_SEEDS=[42,43,44]
MODELS={
 'medium':dict(served='Qwen/Qwen2.5-7B-Instruct',model='Qwen/Qwen2.5-7B-Instruct',path='/root/autodl-tmp/models/Qwen2.5-7B-Instruct',revision='a09a35458c702b33eeacc393d103063234e8bc28'),
 'large':dict(served='Qwen/Qwen2.5-14B-Instruct',model='Qwen/Qwen2.5-14B-Instruct',path='/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8',revision='local GPTQ Int8 checkpoint, hashes frozen'),
 'coder':dict(served='Qwen/Qwen2.5-Coder-7B-Instruct',model='Qwen/Qwen2.5-Coder-7B-Instruct',path='/root/autodl-tmp/models/Qwen2.5-Coder-7B-Instruct',revision='c03e6d358207e414f1eca0bb1891e29f1db0e242'),
 'reasoning':dict(served='deepseek-r1-distill-qwen-14b',model='deepseek-ai/DeepSeek-R1-Distill-Qwen-14B',endpoint='https://dashscope.aliyuncs.com/compatible-mode/v1',revision='provider alias; exact backend weights not independently verifiable')}


def write(path,value):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(path)


def status(phase,**extra):
 row=dict(phase=phase,unix_time=time.time(),**extra);write(OUT/'STATUS.json',row);print(json.dumps(row),flush=True)


@lru_cache(None)
def win(k1,n1,k2,n2):
 if n1==n2 and k1==k2:return .5
 if n1==n2 and k1<k2:return 1-win(k2,n2,k1,n1)
 return float(p_greater(k1+.5,n1-k1+.5,k2+.5,n2-k2+.5))


def entropy(p):
 p=np.clip(np.asarray(p,dtype=float),1e-15,1-1e-15)
 return -p*np.log2(p)-(1-p)*np.log2(1-p)


@lru_cache(None)
def pair_eig(k_alt,k_ref):
 future=np.array([[win(k_alt+i,15,k_ref+j,15) for j in range(11)] for i in range(11)])
 pa=betabinom.pmf(np.arange(11),10,k_alt+.5,5-k_alt+.5)
 pr=betabinom.pmf(np.arange(11),10,k_ref+.5,5-k_ref+.5)
 return float(entropy(win(k_alt,5,k_ref,5))-(pa[:,None]*pr[None,:]*entropy(future)).sum())


def rank_uncertain(ids,repeats,rows):
 rank=[]
 for i,q in enumerate(ids):
  if rows[q]['label']!='uncertain':continue
  counts=repeats[i].sum(1).astype(int)
  eig=sum(pair_eig(int(counts[m]),int(counts[3])) for m in range(3))
  p=np.array(rows[q]['p_win'])
  proximity=float(np.minimum(np.abs(p-.9),np.abs(p-.1)).min())
  rank.append(dict(query_id=q,expected_information_gain_bits=eig,boundary_distance=proximity,
                   original_successes=counts.tolist(),original_label='uncertain'))
 return sorted(rank,key=lambda r:(-r['expected_information_gain_bits'],r['boundary_distance'],r['query_id']))


def select_fold_local(ranked,folds):
 selections=[];union=set()
 for fold in folds:
  allowed=set(fold['development_ids'])
  chosen=[r['query_id'] for r in ranked if r['query_id'] in allowed][:QUOTA]
  if len(chosen)!=QUOTA:raise ValueError('Too few uncertain development candidates')
  selections.append(dict(fold=fold['fold'],repair_training_ids=chosen,
                         development_ids=fold['development_ids'],test_ids=fold['test_ids']))
  union.update(chosen)
 return selections,sorted(union)


@lru_cache(None)
def audit_counts(counts,n):
 counts=np.array(counts,dtype=int)
 pw=np.array([win(int(counts[m]),n,int(counts[3]),n) for m in range(3)])
 ps=1-pw
 pg=np.array([p_gain(counts[m]+.5,n-counts[m]+.5,counts[3]+.5,n-counts[3]+.5,.1) for m in range(3)])
 best=int(counts[:3].argmax())
 pt=float(p_tie(counts[best]+.5,n-counts[best]+.5,counts[3]+.5,n-counts[3]+.5,.1))
 return dict(label=classify(pw,float(ps.min()),pt),p_win=pw.tolist(),p_gain_delta=pg.tolist(),
             p_stay=ps.tolist(),p_tie_best=pt,strict_switch=bool((pg>.9).any()),
             pair_sign_entropy_bits=float(entropy(pw).sum()),repeats=n,successes=counts.tolist())


def prepare():
 if OUT.exists():raise FileExistsError('Label repair output already exists')
 e9protocol=json.loads((E9/'PROTOCOL.json').read_text())
 for p,h in e9protocol['hashes'].items():
  if sha(p)!=h:raise ValueError('E9 provenance changed: '+p)
 z=np.load(E5/'INPUTS.npz',allow_pickle=False);ids=z['ids'].tolist();repeats=z['repeats']
 if repeats.shape!=(400,4,5) or not np.isin(repeats,[0,1]).all():raise ValueError('Bad original repeats')
 old_protocol=json.loads((E5/'PROTOCOL.json').read_text())
 if sha(E5/'INPUTS.npz')!=old_protocol['hashes'][str(E5/'INPUTS.npz')]:raise ValueError('Original input hash mismatch')
 label_rows={r['query_id']:r for r in map(json.loads,LABELS.open())}
 expected=np.array([[label_rows[q]['models'][m]['values'] for m in SLOTS] for q in ids])
 if not np.array_equal(repeats,expected):raise ValueError('Corrected label source mismatch')
 rows={r['query_id']:r for r in map(json.loads,(E9/'PER_QUERY.jsonl').open())}
 counts={c:sum(r['label']==c for r in rows.values()) for c in ['switch','stay','tie','uncertain']}
 if counts!={'switch':50,'stay':64,'tie':0,'uncertain':286}:raise ValueError('E9 population changed')
 folds=json.loads((SOURCE/'FOLDS.json').read_text())
 ranked=rank_uncertain(ids,repeats,rows)
 selections,selected=select_fold_local(ranked,folds)
 if not 80<=len(selected)<=120:raise ValueError(f'Fixed fold-local quota selected {len(selected)} queries; outside requested80–120 range')
 cohort,split=load_cohort(COHORT);ix={q:i for i,q in enumerate(ids)}
 for f in selections:
  if set(f['repair_training_ids'])&set(f['test_ids']):raise ValueError('Selection used outer test IDs')
 if not set(selected)<=set(split['train']):raise ValueError('Not original development queries')
 OUT.mkdir();(OUT/'raw').mkdir()
 panel=[{k:cohort[q][k] for k in ['query_id','query','dataset','task_type']} for q in selected]
 for row in panel:
  row['panel_index']=ids.index(row['query_id'])
  if row['dataset']!='mmlupro' or row['task_type']!='knowledge':raise ValueError('Unexpected dataset/task')
 (OUT/'PANEL.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in panel))
 (OUT/'SELECTION_SCORES.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in ranked))
 write(OUT/'FOLD_REPAIR_SELECTION.json',selections)
 np.savez_compressed(OUT/'INPUTS.npz',ids=z['ids'],x=z['Original'],old_repeats=repeats,
                     old_quality=repeats.mean(2).astype('float32'),groups=z['groups'],selected_indices=np.array([ix[q] for q in selected]))
 # Local manifest records each unchanged checkpoint before collection. Content hashes checked at launch.
 model_files={}
 for slot,cfg in MODELS.items():
  if slot=='reasoning':continue
  path=Path(cfg['path']);index=json.loads((path/'model.safetensors.index.json').read_text())
  files=sorted(set(index['weight_map'].values()))
  configs=[p for p in path.glob('*.json') if p.is_file()]
  model_files[slot]={'path':str(path),'weight_sizes':{f:(path/f).stat().st_size for f in files},
                     'config_sha256':{p.name:sha(p) for p in configs}}
 write(OUT/'LOCAL_MODEL_MANIFEST.json',model_files)
 paths=[Path(__file__),Path(__file__).with_name('collect_label_repair.py'),Path(__file__).with_name('analyze_label_repair.py'),
        Path(__file__).with_name('train_repeat_pairwise_compatibility_115.py'),Path(__file__).with_name('run_repeat_stability.py'),
        Path(__file__).with_name('rescore_glm_pilot.py'),Path(__file__).with_name('score_available.py'),
        Path(__file__).with_name('run_e9_routing_label_audit.py'),Path(__file__).with_name('data.py'),
        E9/'PROTOCOL.json',E9/'PER_QUERY.jsonl',E9/'RESULTS.json',E5/'INPUTS.npz',SOURCE/'FOLDS.json',SOURCE/'PREDICTIONS.npz',LABELS,
        COHORT/'queries.jsonl',COHORT/'split.json',OUT/'PANEL.jsonl',OUT/'SELECTION_SCORES.jsonl',OUT/'FOLD_REPAIR_SELECTION.json',OUT/'INPUTS.npz',OUT/'LOCAL_MODEL_MANIFEST.json']
 protocol=dict(experiment='Label Repair Experiment: final controlled supervision-resolution gate',
  selection=dict(original_uncertain=286,selected_queries=len(selected),quota_per_development_fold=QUOTA,
                 rule='Descending sum of three marginal sign-preference expected information gains after10 beta-binomial future repeats; boundary proximity to0.9/0.1 then query_id tie-breaks.',
                 eig='Exact discrete expectation over11×11 future counts under Jeffreys Beta posterior, not router predictions. Sum of marginal pair EIG is a ranking heuristic, not joint information gain.',
                 isolation='Each fold ranks only its own uncertain development IDs. Collect union. A fold may use15-repeat training labels only for its own40 selected IDs, even if another fold repaired additional IDs in its development set.'),
  sampling=dict(old_repeats=5,new_repeats=10,total=15,slots=SLOTS,temperature=.7,top_p=1.,max_tokens=2048,
                new_repeat_indices=list(range(5,15)),model_configs=MODELS,local_workers=4,api_workers=4,
                maximum_transport_attempts_per_position=2,nominal_generations=len(selected)*40,
                external_nominal_calls=len(selected)*10,external_maximum_attempts=len(selected)*20,
                failure_rule='Record intent before every request; first successful delivered response retained. No correctness-based retries; at most2 transport attempts per position. Three consecutive failed positions stop a slot. Orphan/terminal positions never automatically restarted.',
                transport_failure='Missing, not quality0. Delivered nonempty truncated/unparseable response is scored as delivered, with original corrected parser.',
                api_model_drift='Alias only; record provider model/fingerprint and metadata. Additional repeats assume unchanged generation distribution; batch shift diagnostics reported, no iid proof.'),
  router=dict(methods=['QueryOnlyRidge','RepeatPairwiseMA'],representation='frozen original-prompt GTE',ridge_alpha=1.,
              MA='Unchanged E5/mainline RepeatPairwiseMA fit(), objective, learned embedding8,hidden64,optimizer,inner epoch rule',
              optimization_seeds=MA_SEEDS,
              baseline='Refit original5-label controls and freeze predictions before collection. Repaired condition changes only fold-eligible query label means5→15. Same seeds/splits/training algorithm.',
              primary_evaluation='Selected union queries: only newly generated10-repeat mean on each original outer test fold. Compare frozen original-label vs repaired-label routers using exactly the same new outcomes.',
              secondary_evaluation='All400 OOF queries using common15-repeat means on repaired union and5-repeat means elsewhere; both old/new evaluated identically. Existing5-only evaluation also shown.',
              no_loss_reweighting=True,no_new_embeddings=True),
  audit=dict(prior='Jeffreys Beta(k+.5,n-k+.5)',confidence=.9,margin=.1,
             hierarchy='same E9 switch→stay→tie→uncertain; now n is5 or15, never hardcoded5',
             outputs=['uncertain→switch/stay/tie/uncertain','strict-margin switch count','per-fold effective switch positives','posterior entropy change','old5/new10 batch mean shifts'],
             caution='Remaining uncertainty is not proof of near-tie; tie claim requires posterior band evidence. Fresh100 incomplete alternative panel and confidence oracle are not population or learnability proof.'),
  inference=dict(bootstrap_queries=10000,seed=20260914,unit='query; MA scores averaged across3 fixed optimization seeds, not3 independent samples',
                 primary_comparisons=['repaired MA−original MA','repaired Ridge−original Ridge'],
                 success='Positive paired mean improvement and pointwise CI95 lower>0; report97.5% intervals for two primary contrasts as sensitivity, no outcome-based changes.',
                 limitations=['Same400 previously selected development queries, not new-query external confirmation. Primary target is the actively selected uncertain subset.',
                              'Same-query new labels excluded from its assigned outer training fold; baseline and repaired models share evaluation outcomes.',
                              'Positive intervention effect supports supervision resolution for this recipe, not unique causal attribution; unchanged near-ties, finite power and API time drift remain possible.']),
  stop='One bounded intervention only. No extra repeats beyond15, no newqueries/encoder/loss/router search, no GitHub push, no automatic subsequent experiment.',
  source_class_counts=counts,packages={p:importlib.metadata.version(p) for p in ['numpy','scipy','scikit-learn','torch']},
  hashes={str(p):sha(p) for p in paths})
 write(OUT/'PROTOCOL.json',protocol)
 write(OUT/'EXTERNAL_SCOPE.json',dict(destination=MODELS['reasoning']['endpoint'],model=MODELS['reasoning']['served'],
      payload='Frozen selected public MMLU-Pro question+options only; no answer keys, local paths or other workspace contents',
      query_ids=selected,nominal_calls=len(selected)*10,max_attempts=len(selected)*20,max_tokens=2048,
      purpose='User-requested single Label Repair Experiment,5→15 repeats',protocol_sha256=sha(OUT/'PROTOCOL.json')))
 status('PREPARED',selected_queries=len(selected),nominal_generations=len(selected)*40,external_nominal_calls=len(selected)*10)


def verify():
 p=json.loads((OUT/'PROTOCOL.json').read_text())
 for path,h in p['hashes'].items():
  if sha(path)!=h:raise ValueError('Frozen file changed: '+path)
 return p


if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('stage',choices=['prepare']);args=a.parse_args();prepare()
