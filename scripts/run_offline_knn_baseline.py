#!/usr/bin/env python3
"""Train a leakage-checked Longformer KNN baseline on frozen responses only."""
from __future__ import annotations
import hashlib,json,pickle,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import torch
from sklearn.metrics import accuracy_score,balanced_accuracy_score,confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from llmrouter.utils.embeddings import get_longformer_embedding

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parents[1]/'frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z'
SOURCE=ARCHIVE/'run_logs/formal_context_v2_rescored_v22_result.json'
OUT=ROOT/'run_logs/offline_knn_baseline'
SEED=20260729
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo')

def num(x,d=0.):
 try:return float(x)
 except (TypeError,ValueError):return d

def task_metrics(rows):
 q=np.mean([num(x.get('quality')) for x in rows]); cost=np.mean([num(x.get('raw_cost_usd')) for x in rows]); lat=np.mean([num(x.get('latency_ms')) for x in rows]); rel=np.mean([bool(x.get('ok')) for x in rows])
 c=min(cost/.02,1); l=min(lat/10000,1); u=.45*q+.20*(1-c)+.15*(1-l)+.20*rel
 return {'quality':round(float(q),6),'raw_cost_usd':round(float(cost),8),'latency_ms':round(float(lat),6),'reliability':round(float(rel),6),'utility':round(float(u),6)}

def stratified_split(tasks,labels):
 # Classes with fewer than three tasks cannot honestly appear in all splits.
 counts=Counter(labels.values());rare=sorted(x for x in labels if counts[labels[x]]<3)
 common=sorted(x for x in labels if x not in set(rare))
 trainval,test=train_test_split(common,test_size=20,random_state=SEED,stratify=[labels[x] for x in common])
 train,val=train_test_split(trainval,test_size=20,random_state=SEED,stratify=[labels[x] for x in trainval])
 train+=rare
 assert not(set(train)&set(val) or set(train)&set(test) or set(val)&set(test))
 assert set(train)|set(val)|set(test)==set(labels)
 return {'train':sorted(train),'validation':sorted(val),'test':sorted(test)}

def aggregate(mapped):
 if not mapped:return {}
 return {k:round(float(np.mean([x['metrics'][k] for x in mapped])),6) for k in ('quality','raw_cost_usd','latency_ms','reliability','utility')}

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 source=json.loads(SOURCE.read_text()); tasks=source['sampled_task_set']; by_tm=defaultdict(list)
 for row in source['raw_model_runs']:by_tm[(row['task_id'],row['model'])].append(row)
 metrics={};labels={};ties={}
 for t in tasks:
  tid=t['id'];metrics[tid]={m:task_metrics(by_tm[(tid,m)]) for m in MODELS}
  best=max(x['utility'] for x in metrics[tid].values()); winners=sorted(m for m,x in metrics[tid].items() if abs(x['utility']-best)<1e-12)
  labels[tid]=winners[0];ties[tid]=winners
 split=stratified_split(tasks,labels)
 rare_labels={name:count for name,count in Counter(labels.values()).items() if count<3}
 task_by_id={t['id']:t for t in tasks}; order=sorted(task_by_id)
 cache=OUT/'longformer_embeddings.pt'; started=time.perf_counter()
 if cache.exists():
  payload=torch.load(cache,map_location='cpu',weights_only=False); assert payload['task_ids']==order; embeddings=payload['embeddings']; cache_hit=True;cold_seconds=payload.get('cold_seconds')
 else:
  chunks=[]
  for i in range(0,len(order),4):chunks.append(get_longformer_embedding([task_by_id[x]['query'] for x in order[i:i+4]]).cpu())
  embeddings=torch.cat(chunks);cache_hit=False;cold_seconds=None
 embed_seconds=time.perf_counter()-started; index={tid:i for i,tid in enumerate(order)}
 if not cache_hit:
  cold_seconds=embed_seconds;torch.save({'task_ids':order,'embeddings':embeddings,'model':'allenai/longformer-base-4096','cold_seconds':cold_seconds},cache)
 X=embeddings.numpy(); y=np.array([labels[x] for x in order]);
 def xy(name):
  ids=split[name];ix=[index[x] for x in ids];return X[ix],np.array([labels[x] for x in ids]),ids
 Xtr,ytr,_=xy('train');Xv,yv,_=xy('validation')
 tuning=[]
 for k in (1,3,5,7,9,11):
  for weights in ('uniform','distance'):
   model=KNeighborsClassifier(n_neighbors=k,weights=weights,metric='cosine',algorithm='brute',n_jobs=-1).fit(Xtr,ytr);pred=model.predict(Xv)
   tuning.append({'k':k,'weights':weights,'accuracy':round(float(accuracy_score(yv,pred)),6),'balanced_accuracy':round(float(balanced_accuracy_score(yv,pred)),6)})
 best=sorted(tuning,key=lambda x:(-x['balanced_accuracy'],-x['accuracy'],x['k'],x['weights']))[0]
 trainval=split['train']+split['validation'];ix=[index[x] for x in trainval]
 model=KNeighborsClassifier(n_neighbors=best['k'],weights=best['weights'],metric='cosine',algorithm='brute',n_jobs=-1).fit(X[ix],y[ix])
 with (OUT/'knnrouter_longformer.pkl').open('wb') as h:pickle.dump(model,h)
 Xt,yt,test_ids=xy('test');pred=model.predict(Xt);proba=model.predict_proba(Xt)
 mapped=[]
 for n,(tid,chosen,gold) in enumerate(zip(test_ids,pred,yt)):
  mapped.append({'task_id':tid,'dataset':task_by_id[tid].get('dataset'),'selected_model':str(chosen),'label_model':str(gold),'correct':bool(chosen==gold),'tie_models':ties[tid],'confidence':round(float(max(proba[n])),6),'metrics':metrics[tid][str(chosen)]})
 fixed=[{'metrics':metrics[tid]['deepseek-chat']} for tid in test_ids];oracle=[{'metrics':metrics[tid][labels[tid]]} for tid in test_ids]
 report={'report_type':'strict_offline_knn_baseline','generated_at':datetime.now(timezone.utc).isoformat(),'offline_only':True,'api_calls':0,'source_archive':str(ARCHIVE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'embedding':{'model':'allenai/longformer-base-4096','dimension':int(embeddings.shape[1]),'cache_hit':cache_hit,'seconds':round(embed_seconds,3)},'split':{k:{'count':len(v),'task_ids':v,'datasets':dict(Counter(task_by_id[x].get('dataset') for x in v)),'labels':dict(Counter(labels[x] for x in v))} for k,v in split.items()},'leakage_checks':{'task_sets_disjoint':True,'labels_derived_per_task_from_three_frozen_repeats':True,'test_labels_not_used_for_tuning':True,'test_responses_not_used_as_features':True},'label_definition':'argmax mean canonical utility over the three frozen responses; lexical tie-break only for exact ties','validation_tuning':tuning,'selected_hyperparameters':best,'test':{'count':len(test_ids),'accuracy':round(float(accuracy_score(yt,pred)),6),'balanced_accuracy':round(float(balanced_accuracy_score(yt,pred)),6),'selection_counts':dict(Counter(map(str,pred))),'label_counts':dict(Counter(map(str,yt))),'labels':list(MODELS),'confusion_matrix':confusion_matrix(yt,pred,labels=list(MODELS)).tolist(),'knn_metrics':aggregate(mapped),'fixed_strong_metrics':aggregate(fixed),'oracle_upper_bound_metrics':aggregate(oracle),'rows':mapped}}
 report['rare_label_policy']={'rare_labels':rare_labels,'policy':'Classes with fewer than three tasks remain in training only and are never duplicated.','test_scope_limitation':'GLM-5.2 recall is not estimable because only one task has GLM-5.2 as the utility-optimal label.'}
 report['embedding']['cold_seconds']=round(float(cold_seconds),3) if cold_seconds is not None else None
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 (OUT/'split.json').write_text(json.dumps(split,ensure_ascii=False,indent=2)+'\n')
 lines=['# 严格离线 Longformer KNN 基线','',f"- 划分：train/validation/test = {len(split['train'])}/{len(split['validation'])}/{len(split['test'])}",'- API 调用：0','- 特征：本地 `allenai/longformer-base-4096`，768 维','- 标签：每题三次冻结回答的平均规范效用最优模型；测试标签不参与训练和调参',f"- 最优参数：k={best['k']}，weights={best['weights']}，metric=cosine",f"- 测试准确率：{report['test']['accuracy']:.2%}",f"- 测试平衡准确率：{report['test']['balanced_accuracy']:.2%}",f"- 测试选择分布：{report['test']['selection_counts']}",f"- KNN 测试效用：{report['test']['knn_metrics']['utility']:.6f}",f"- 固定 DeepSeek 测试效用：{report['test']['fixed_strong_metrics']['utility']:.6f}",f"- Oracle 上界效用：{report['test']['oracle_upper_bound_metrics']['utility']:.6f}",'','该结果是独立补充基线，不回写或替换已冻结主实验。']
 lines.insert(6,f"- 稀有标签：{rare_labels}，仅保留在训练集，不复制样本")
 (OUT/'report.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps({'out':str(OUT),'best':best,'test':report['test']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
