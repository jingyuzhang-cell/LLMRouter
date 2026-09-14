"""Frozen old-label controls, then one repaired-label evaluation on common outcomes."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
from sklearn.linear_model import Ridge

from .label_repair_plan import OUT,ROOT,E9,SOURCE,SLOTS,MA_SEEDS,verify,write,status,audit_counts
from .data import sha,load_cohort
from .train_repeat_pairwise_compatibility_115 import fit,inner_split,PairwiseMA,subject
from .rescore_glm_pilot import extract_option


def load():
 protocol=verify();z=np.load(OUT/'INPUTS.npz',allow_pickle=False);ids=z['ids'].tolist();ix={q:i for i,q in enumerate(ids)}
 folds=json.loads((OUT/'FOLD_REPAIR_SELECTION.json').read_text());cohort,_=load_cohort(ROOT/'data/cohort_full_v2')
 subjects=np.array([subject(cohort[q]['query']) for q in ids])
 return protocol,z,ids,ix,folds,subjects


def train_condition(x,old_y,ids,ix,folds,subjects,new_y=None):
 torch.set_num_threads(4)
 ridge=np.empty((400,4));ma=np.empty((3,400,4));best=np.empty(400,int);details=[];fold_labels=[]
 for f in folds:
  dev=np.array([ix[q] for q in f['development_ids']]);test=np.array([ix[q] for q in f['test_ids']])
  repair=np.array([ix[q] for q in f['repair_training_ids']])
  if not set(repair)<=set(dev) or set(dev)&set(test):raise ValueError('Fold-local repair leakage')
  y=old_y.copy()
  if new_y is not None:y[repair]=new_y[repair]
  # No other repaired label is used, even if available from another fold's selection.
  untouched=np.ones(400,bool);untouched[repair]=False
  if not np.array_equal(y[untouched],old_y[untouched]):raise ValueError('Noneligible label changed')
  train,validation=inner_split(dev,subjects,f['fold'])
  rp=Ridge(alpha=1.).fit(x[dev],y[dev]).predict(x[test]);ridge[test]=rp
  best[test]=int(y[dev].mean(0).argmax());trace=[]
  for j,seed in enumerate(MA_SEEDS):
   pred,state,detail=fit(x,y,train,validation,dev,test,seed);ma[j,test]=pred
   trace.append(dict(seed=seed,**detail))
  details.append(dict(fold=f['fold'],development_ids=f['development_ids'],test_ids=f['test_ids'],
                      repaired_training_ids=f['repair_training_ids'] if new_y is not None else [],ma_fit=trace))
  fold_labels.append(dict(fold=f['fold'],used_quality=y[dev].tolist()))
  print(json.dumps(dict(condition='repaired' if new_y is not None else 'old5',fold_complete=f['fold'])),flush=True)
 return dict(ridge_scores=ridge,ma_scores=ma,bestsingle_choice=best),details,fold_labels


def baseline():
 protocol,z,ids,ix,folds,subjects=load()
 if (OUT/'BASELINE_FROZEN.json').exists():raise FileExistsError('Original-label control already frozen')
 if any((OUT/'raw').glob('*ATTEMPTS.jsonl')):raise RuntimeError('Baseline must precede all new collection')
 start=time.time()
 predictions,details,labels=train_condition(z['x'],z['old_quality'],ids,ix,folds,subjects)
 previous=np.load(SOURCE/'PREDICTIONS.npz',allow_pickle=False)
 if previous['ids'].tolist()!=ids:raise ValueError('Baseline order changed')
 if not np.array_equal(predictions['ridge_scores'].argmax(1),previous['choice_QueryOnlyRidge']):raise ValueError('Old Ridge not reproduced')
 for j,seed in enumerate(MA_SEEDS):
  if not np.array_equal(predictions['ma_scores'][j].argmax(1),previous[f'choice_RepeatPairwiseMA_seed{seed}']):raise ValueError('Old MA not reproduced')
 np.savez_compressed(OUT/'BASELINE_PREDICTIONS.npz',ids=np.array(ids),**predictions)
 write(OUT/'BASELINE_FOLDS.json',details)
 write(OUT/'BASELINE_FROZEN.json',dict(predictions_sha256=sha(OUT/'BASELINE_PREDICTIONS.npz'),
       folds_sha256=sha(OUT/'BASELINE_FOLDS.json'),protocol_sha256=sha(OUT/'PROTOCOL.json'),
       started_at=start,frozen_at=time.time(),all_baseline_choices_reproduced=True))
 status('BASELINE_FROZEN',queries=400,models_unchanged=True)


def aggregate(z,ids,ix):
 selected=z['selected_indices'];selected_ids={ids[i] for i in selected}
 new=np.full((400,4,10),np.nan);hashes={};cohort,_=load_cohort(ROOT/'data/cohort_full_v2')
 for m,slot in enumerate(SLOTS):
  path=OUT/'raw'/f'{slot}.jsonl'
  if not path.exists():raise ValueError('Collection incomplete: '+slot)
  rows=[json.loads(s) for s in path.open()]
  keys={(r['query_id'],r['repeat_index']) for r in rows}
  expected={(q,k) for q in selected_ids for k in range(5,15)}
  if len(rows)!=len(keys) or keys!=expected:raise ValueError('Incomplete/duplicate collection: '+slot)
  for r in rows:
   if r['quality'] not in (0,1) or r['status'] not in ('ok','truncated') or not r.get('answer'):raise ValueError('Missing generation cannot become0')
   if r['protocol_sha256']!=sha(OUT/'PROTOCOL.json') or r['temperature']!=.7 or r['top_p']!=1. or r['max_tokens']!=2048:raise ValueError('Generation distribution binding changed')
   option=extract_option(r['answer']);gt=str(cohort[r['query_id']]['ground_truth']).strip().upper()[-1]
   quality=float(option==gt) if option else 0.
   if quality!=r['quality']:raise ValueError('Corrected score reproduction failed')
   new[ix[r['query_id']],m,r['repeat_index']-5]=quality
  hashes[slot]=sha(path)
 if not np.isfinite(new[selected]).all():raise ValueError('Selected new10 labels incomplete')
 repaired=z['old_quality'].copy()
 repaired[selected]=np.concatenate([z['old_repeats'][selected],new[selected]],axis=2).mean(2)
 np.savez_compressed(OUT/'REPAIRED_LABELS.npz',ids=np.array(ids),selected_indices=selected,new_repeats_selected=new[selected],
                      old_quality=z['old_quality'],repaired_quality=repaired)
 write(OUT/'LABELS_FROZEN.json',dict(raw_sha256=hashes,labels_sha256=sha(OUT/'REPAIRED_LABELS.npz'),
                                    selected_queries=len(selected),new_records=len(selected)*40))
 return new,repaired


def run():
 protocol,z,ids,ix,folds,subjects=load()
 if (OUT/'RESULTS.json').exists() or (OUT/'EVALUATION_STARTED.json').exists():raise FileExistsError('Final evaluation already started/completed')
 frozen=json.loads((OUT/'BASELINE_FROZEN.json').read_text())
 if sha(OUT/'BASELINE_PREDICTIONS.npz')!=frozen['predictions_sha256']:raise ValueError('Original predictions changed')
 # Refuse an incomplete panel before opening evaluation or training repaired models.
 new,repaired_y=aggregate(z,ids,ix)
 write(OUT/'EVALUATION_STARTED.json',dict(unix_time=time.time(),labels_sha256=sha(OUT/'REPAIRED_LABELS.npz')))
 old_audit={r['query_id']:r for r in map(json.loads,(E9/'PER_QUERY.jsonl').open())}
 selected=z['selected_indices'];all_after=dict(old_audit);audit_rows=[]
 for i in selected:
  values=np.concatenate([z['old_repeats'][i],new[i]],axis=1)
  after=audit_counts(tuple(values.sum(1).astype(int)),15)
  before=audit_counts(tuple(z['old_repeats'][i].sum(1).astype(int)),5)
  if before['label']!=old_audit[ids[i]]['label']:raise ValueError('E9 audit not reproduced')
  all_after[ids[i]]=after
  audit_rows.append(dict(query_id=ids[i],before=before,after=after))
 (OUT/'BAYESIAN_AUDIT_PER_QUERY.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in audit_rows))
 conversion={c:sum(r['after']['label']==c for r in audit_rows) for c in ['switch','stay','tie','uncertain']}
 fold_positive=[]
 for f in folds:
  dev=f['development_ids'];repaired_set=set(f['repair_training_ids'])
  labels={q:all_after[q] if q in repaired_set else old_audit[q] for q in dev}
  fold_positive.append(dict(fold=f['fold'],repaired_queries=len(repaired_set),
       before_switch=sum(old_audit[q]['label']=='switch' for q in dev),after_switch=sum(labels[q]['label']=='switch' for q in dev),
       after_uncertain=sum(labels[q]['label']=='uncertain' for q in dev),
       after_strict_switch=sum(any(p>.9 for p in labels[q]['p_gain_delta']) for q in dev)))
 audit=dict(selected_queries=len(selected),uncertain_to=conversion,
       resolved_fraction=(len(selected)-conversion['uncertain'])/len(selected),
       strict_switch_selected=sum(r['after']['strict_switch'] for r in audit_rows),
       full400_after_counts={c:sum(row['label']==c for row in all_after.values()) for c in ['switch','stay','tie','uncertain']},
       per_fold_effective_positives=fold_positive,
       mean_pair_entropy_before=float(np.mean([r['before']['pair_sign_entropy_bits'] for r in audit_rows])),
       mean_pair_entropy_after=float(np.mean([r['after']['pair_sign_entropy_bits'] for r in audit_rows])),
       warning='Unresolved at15 is not proof of near-tie; confident-tie requires the frozen posterior band criterion.')
 write(OUT/'BAYESIAN_AUDIT.json',audit)
 status('AUDIT_COMPLETE',conversion=conversion)
 predictions,details,used_labels=train_condition(z['x'],z['old_quality'],ids,ix,folds,subjects,new_y=repaired_y)
 np.savez_compressed(OUT/'REPAIRED_PREDICTIONS.npz',ids=np.array(ids),**predictions)
 write(OUT/'REPAIRED_FOLDS.json',details);write(OUT/'FOLD_TRAIN_LABELS.json',used_labels)
 write(OUT/'REPAIRED_PREDICTIONS_FROZEN.json',dict(predictions_sha256=sha(OUT/'REPAIRED_PREDICTIONS.npz'),
                                                labels_sha256=sha(OUT/'REPAIRED_LABELS.npz'),frozen_at=time.time()))
 old=np.load(OUT/'BASELINE_PREDICTIONS.npz',allow_pickle=False)
 choices={}
 for condition,pred in [('original',old),('repaired',predictions)]:
  choices[condition+'_Ridge']=pred['ridge_scores'].argmax(1)[None,:]
  choices[condition+'_MA']=pred['ma_scores'].argmax(2)
  choices[condition+'_BestSingle']=pred['bestsingle_choice'][None,:]
 def evaluate(y,indices):
  idx=np.asarray(indices);boot=np.random.default_rng(20260914).integers(0,len(idx),(10000,len(idx)))
  actual={name:y[idx[None,:],ch[:,idx]].mean(0) for name,ch in choices.items()}
  def comparison(a,b):
   diff=actual[a]-actual[b];means=diff[boot].mean(1)
   return dict(mean=float(diff.mean()),ci95=np.quantile(means,[.025,.975]).tolist(),
               ci975_two_primary=np.quantile(means,[.0125,.9875]).tolist(),success=bool(diff.mean()>0 and np.quantile(means,.025)>0))
  comparisons={name:comparison(a,b) for name,a,b in [
    ('MA_repaired_minus_original','repaired_MA','original_MA'),('Ridge_repaired_minus_original','repaired_Ridge','original_Ridge'),
    ('repaired_MA_minus_repaired_Ridge','repaired_MA','repaired_Ridge'),('repaired_MA_minus_original_Ridge','repaired_MA','original_Ridge'),
    ('repaired_Ridge_minus_original_BestSingle','repaired_Ridge','original_BestSingle')]}
  oracle=y[idx].max(1);baseline=actual['original_BestSingle'];gap=float((oracle-baseline).mean())
  methods={name:dict(eq=float(a.mean()),gap_recovery=float((a-baseline).mean()/gap) if gap>0 else None,
          selection_fraction={s:float((choices[name][:,idx]==m).mean()) for m,s in enumerate(SLOTS)}) for name,a in actual.items()}
  return dict(n=len(idx),methods=methods,comparisons=comparisons,empirical_oracle_eq=float(oracle.mean()),
              original_bestsingle_eq=float(baseline.mean())),actual
 new_y=np.zeros((400,4));new_y[selected]=new[selected].mean(2)
 primary,actual_primary=evaluate(new_y,selected)
 secondary,actual_secondary=evaluate(repaired_y,np.arange(400))
 historical,actual_historical=evaluate(z['old_quality'],np.arange(400))
 metrics=dict(primary_new10_selected=primary,secondary_common_repaired400=secondary,secondary_original5_400=historical)
 boot=np.random.default_rng(20260914).integers(0,len(selected),(10000,len(selected)))
 batch={}
 for m,s in enumerate(SLOTS):
  diff=new[selected,m].mean(1)-z['old_repeats'][selected,m].mean(1)
  batch[s]=dict(old5_eq=float(z['old_repeats'][selected,m].mean()),new10_eq=float(new[selected,m].mean()),
                 difference=float(diff.mean()),ci95=np.quantile(diff[boot].mean(1),[.025,.975]).tolist(),
                 note='Selected on old labels; regression-to-mean confounds this with provider/time drift. Not an iid test.')
 ma_success=primary['comparisons']['MA_repaired_minus_original']['success'];ridge_success=primary['comparisons']['Ridge_repaired_minus_original']['success']
 if ma_success or ridge_success:
  interpretation='supervision_resolution_intervention_supported_for_'+('_and_'.join(n for n,s in [('MA',ma_success),('Ridge',ridge_success)] if s))
 else:interpretation='no_confirmed_router_improvement_after_bounded_label_repair'
 result=dict(experiment='Label Repair Experiment',audit=audit,metrics=metrics,batch_diagnostics=batch,
      decision=dict(interpretation=interpretation,MA_improved=ma_success,Ridge_improved=ridge_success,
                    no_unique_causal_attribution=True,unresolved_is_not_near_tie=True,final_gate_complete=True,next_experiment_started=False),
      protocol_sha256=sha(OUT/'PROTOCOL.json'),baseline_predictions_sha256=sha(OUT/'BASELINE_PREDICTIONS.npz'),
      repaired_predictions_sha256=sha(OUT/'REPAIRED_PREDICTIONS.npz'),labels_sha256=sha(OUT/'REPAIRED_LABELS.npz'))
 np.savez_compressed(OUT/'EVALUATION_VALUES.npz',selected_ids=np.array(ids)[selected],
      **{'primary_'+k:v for k,v in actual_primary.items()},**{'secondary_'+k:v for k,v in actual_secondary.items()},
      **{'original5_'+k:v for k,v in actual_historical.items()})
 write(OUT/'RESULTS.json',result);report(result);status('COMPLETE',interpretation=interpretation,next_experiment_started=False)


def effect(r):return f'{100*r["mean"]:+.2f} [{100*r["ci95"][0]:.2f}, {100*r["ci95"][1]:.2f}]'


def report(r):
 audit=r['audit'];primary=r['metrics']['primary_new10_selected']
 lines=['# Label Repair Experiment：最终受控验证','',
        f'选中{audit["selected_queries"]}个原uncertain query，四模型各新增10次，5→15 repeats。选题为每个冻结development折内信息增益前40题的并集；各折只使用自己的40题修复标签。','',
        '同一原始GTE、QueryOnly Ridge与现有最简单冻结MA训练流程；不改变模型/表示/loss/阈值。旧标签对照在补采前重训并封存，且复现历史Ridge与全部3个MA初始化决策。','',
        '## 标签转化','', '| uncertain → | 数量 |','|---|---:|']
 for c,n in audit['uncertain_to'].items():lines.append(f'| {c} | {n} |')
 lines += ['',f'已判定比例：{audit["resolved_fraction"]:.2%}；修复子集严格margin switch：{audit["strict_switch_selected"]}。','',
           '| fold | 修复题数 | switch前 | switch后 | strict switch后 | uncertain后 |','|---|---:|---:|---:|---:|---:|']
 for f in audit['per_fold_effective_positives']:lines.append(f'| {f["fold"]} | {f["repaired_queries"]} | {f["before_switch"]} | {f["after_switch"]} | {f["after_strict_switch"]} | {f["after_uncertain"]} |')
 lines+=['','## 主检验：选中题目的新增10次回答','',
         '新旧Router均在同一批新回答上评价；每题使用原outer fold的预测，该题的新标签不进入自己的训练折。目标是主动选择的uncertain开发子集，不是新query或总体外部确认。','',
         '| Router | EQ | Gap Recovery |','|---|---:|---:|']
 for name,m in primary['methods'].items():lines.append(f'| {name} | {m["eq"]:.2%} | '+(f'{m["gap_recovery"]:.2%}' if m['gap_recovery'] is not None else '未定义')+' |')
 lines+=['','| 比较 | EQ变化 pp [95% paired query CI] |','|---|---|']
 for name,v in primary['comparisons'].items():lines.append(f'| {name} | {effect(v)} |')
 lines+=['','## 辅助：共同修复标签的全400题评估','', '| 比较 | EQ变化 pp [95% CI] |','|---|---|']
 for name,v in r['metrics']['secondary_common_repaired400']['comparisons'].items():lines.append(f'| {name} | {effect(v)} |')
 lines+=['','## 最终闸门','',r['decision']['interpretation'], '',
         '正向配对提升支持本固定训练流程受益于监督分辨率，但不能证明它是唯一瓶颈。若标签更明确却没有确认收益，只能说明这次有限补采没有证明Router改善；不能以区间跨0证明完全不可学习。未判定仍不等于near-tie，只有满足后验band规则才报告confident tie。','',
         '## 限制与停止条件','',
         '- fresh-100替代模型仅在旧Router切换的10题采集，其缺少统计支持的切换不能代表总体机会迁移。此次不改动该确认集。',
         '- confidence-only oracle与修复面板Oracle均为开发诊断上限，不是已证明可学习GAP。',
         '- 信息增益使用独立Jeffreys后验的三个边际sign事件之和，非联合信息量；生成漂移与有限采样仍可能影响结果。',
         '- 全部配对区间以query为单位，3个MA初始化先取实际质量均值。两项主比较另报97.5%区间；不按seed/参数挑选结果。',
         '- 旧5/新10的均值差混合了选择导致的回归均值与时间/服务漂移，单凭它不能归因于后端模型变化。',
         '- 本轮为唯一受控补采，不自动增到25次，不加query、不改encoder/loss/Router、不推GitHub，完成后停止。']
 (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['baseline','run']);args=ap.parse_args();globals()[args.stage]()
