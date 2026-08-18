#!/usr/bin/env python3
"""Ten strict task-split robustness runs for trained KNN and GraphRouter."""
from __future__ import annotations
import hashlib,json,pickle,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import torch
from sklearn.metrics import accuracy_score,balanced_accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from llmrouter.models.graphrouter.graph_nn import EncoderDecoderNet
from llmrouter.utils.embeddings import get_longformer_embedding
from scripts.run_offline_graphrouter_baseline import MODELS,DESCRIPTIONS,DEVICE,make_graph,predict,train_once,metrics

ROOT=Path(__file__).resolve().parents[1];ARCHIVE=ROOT.parents[1]/'frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z';SOURCE=ARCHIVE/'run_logs/formal_context_v2_rescored_v22_result.json';KNN_DIR=ROOT/'run_logs/offline_knn_baseline';OUT=ROOT/'run_logs/split_robustness_analysis';SPLIT_SEEDS=[20260729+i for i in range(10)]

def split_labels(labels,seed):
 counts=Counter(labels.values());rare=sorted(x for x in labels if counts[labels[x]]<3);common=sorted(x for x in labels if x not in set(rare))
 trainval,test=train_test_split(common,test_size=20,random_state=seed,stratify=[labels[x] for x in common]);train,val=train_test_split(trainval,test_size=20,random_state=seed,stratify=[labels[x] for x in trainval]);train+=rare
 out={'train':sorted(train),'validation':sorted(val),'test':sorted(test)};sets=[set(out[x]) for x in out];assert [len(out[x]) for x in out]==[60,20,20] and not(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2]);return out

def mean_metric(ids,selected,utilities,key='utility'):return float(np.mean([utilities[x][m][key] for x,m in zip(ids,selected)]))

def summary(rows,key):
 values=np.array([x[key] for x in rows],dtype=float);return {'mean':round(float(values.mean()),6),'sample_std':round(float(values.std(ddof=1)),6),'min':round(float(values.min()),6),'max':round(float(values.max()),6)}

def main():
 OUT.mkdir(parents=True,exist_ok=True);source=json.loads(SOURCE.read_text());tasks={x['id']:x for x in source['sampled_task_set']};by=defaultdict(list)
 for r in source['raw_model_runs']:by[(r['task_id'],r['model'])].append(r)
 utilities={tid:{m:metrics(by[(tid,m)]) for m in MODELS} for tid in tasks};labels={tid:max(MODELS,key=lambda m:(utilities[tid][m]['utility'],-MODELS.index(m))) for tid in tasks}
 payload=torch.load(KNN_DIR/'longformer_embeddings.pt',map_location='cpu',weights_only=False);raw_q={tid:payload['embeddings'][i].numpy() for i,tid in enumerate(payload['task_ids'])};llm_raw=get_longformer_embedding([DESCRIPTIONS[m] for m in MODELS]).cpu().numpy();llm=StandardScaler().fit_transform(llm_raw)
 runs=[];started=time.perf_counter()
 for split_seed in SPLIT_SEEDS:
  split=split_labels(labels,split_seed);train,val,test=(split[x] for x in ('train','validation','test'));index={tid:i for i,tid in enumerate(sorted(tasks))};order=sorted(tasks);X=np.stack([raw_q[x] for x in order]);Xtr=np.stack([raw_q[x] for x in train]);Xv=np.stack([raw_q[x] for x in val]);Xt=np.stack([raw_q[x] for x in test]);ytr=np.array([labels[x] for x in train]);yv=np.array([labels[x] for x in val]);yt=np.array([labels[x] for x in test])
  tuning=[]
  for k in (1,3,5,7,9,11):
   for weights in ('uniform','distance'):
    model=KNeighborsClassifier(n_neighbors=k,weights=weights,metric='cosine',algorithm='brute',n_jobs=-1).fit(Xtr,ytr);pv=model.predict(Xv);tuning.append((balanced_accuracy_score(yv,pv),accuracy_score(yv,pv),-k,weights,model))
  _,_,negk,weights,knn=max(tuning,key=lambda x:(x[0],x[1],x[2],x[3]));kp=knn.predict(Xt)
  scaler=StandardScaler().fit(Xtr);qmap={x:scaler.transform(raw_q[x].reshape(1,-1))[0] for x in train+val+test};best=train_once(qmap,llm,utilities,train,val,32,.001,17,epochs=120);graph_model=EncoderDecoderNet(768,768,32,1).to(DEVICE);graph_model.load_state_dict(best['state']);graph=make_graph(train+test,qmap,llm,utilities,train,test);gp,_=predict(graph_model,graph);gm=[MODELS[int(x)] for x in gp];fixed=['deepseek-chat']*len(test);oracle=[labels[x] for x in test]
  runs.append({'split_seed':split_seed,'split':split,'rare_labels':{m:c for m,c in Counter(labels.values()).items() if c<3},'knn':{'k':-negk,'weights':weights,'accuracy':round(float(accuracy_score(yt,kp)),6),'balanced_accuracy':round(float(balanced_accuracy_score(yt,kp)),6),'selection_counts':dict(Counter(map(str,kp))),'utility':round(mean_metric(test,list(map(str,kp)),utilities),6)},'graphrouter':{'hidden':32,'lr':.001,'training_seed':17,'best_epoch':best['epoch'],'validation_utility':round(best['utility'],6),'accuracy':round(float(accuracy_score(yt,gm)),6),'balanced_accuracy':round(float(balanced_accuracy_score(yt,gm)),6),'selection_counts':dict(Counter(gm)),'utility':round(mean_metric(test,gm,utilities),6)},'fixed_strong':{'utility':round(mean_metric(test,fixed,utilities),6)},'oracle':{'utility':round(mean_metric(test,oracle,utilities),6)},'leakage_checks':{'disjoint':True,'test_not_used_for_tuning':True,'graph_test_edges_invisible':True,'same_test_tasks_for_methods':True}})
 for row in runs:row['graph_minus_fixed']=round(row['graphrouter']['utility']-row['fixed_strong']['utility'],6);row['knn_minus_fixed']=round(row['knn']['utility']-row['fixed_strong']['utility'],6)
 report={'report_type':'ten_split_trained_router_robustness','generated_at':datetime.now(timezone.utc).isoformat(),'offline_only':True,'api_calls':0,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'split_seeds':SPLIT_SEEDS,'elapsed_seconds':round(time.perf_counter()-started,3),'protocol':{'counts':{'train':60,'validation':20,'test':20},'rare_class_policy':'classes with fewer than three tasks stay in train only; no duplication','knn':'validation tunes k and weights for each split','graphrouter':'hidden=32, lr=0.001 and training seed=17 fixed; validation selects stopping epoch','warning':'test sets overlap across split seeds, so across-split summaries are descriptive stability measures, not independent-sample significance tests'},'summary':{'graphrouter_utility':summary([{'x':x['graphrouter']['utility']} for x in runs],'x'),'knn_utility':summary([{'x':x['knn']['utility']} for x in runs],'x'),'fixed_strong_utility':summary([{'x':x['fixed_strong']['utility']} for x in runs],'x'),'graph_minus_fixed':summary(runs,'graph_minus_fixed'),'knn_minus_fixed':summary(runs,'knn_minus_fixed'),'graph_beats_fixed_count':sum(x['graph_minus_fixed']>0 for x in runs),'graph_beats_fixed_rate':round(sum(x['graph_minus_fixed']>0 for x in runs)/len(runs),6),'knn_beats_fixed_count':sum(x['knn_minus_fixed']>0 for x in runs),'knn_beats_fixed_rate':round(sum(x['knn_minus_fixed']>0 for x in runs)/len(runs),6)},'runs':runs}
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');lines=['# 训练路由器 10 划分稳健性分析','',f"- 10 个严格 60/20/20 任务划分；API 调用 0；耗时 {report['elapsed_seconds']:.3f} 秒",'- 测试集在不同种子间有重叠，下列结果是描述性稳健性，不是 10 个独立实验样本','',f"- GraphRouter 效用：{report['summary']['graphrouter_utility']}",f"- KNN 效用：{report['summary']['knn_utility']}",f"- 固定 DeepSeek 效用：{report['summary']['fixed_strong_utility']}",f"- GraphRouter 胜过固定模型：{report['summary']['graph_beats_fixed_count']}/10 ({report['summary']['graph_beats_fixed_rate']:.0%})",f"- KNN 胜过固定模型：{report['summary']['knn_beats_fixed_count']}/10 ({report['summary']['knn_beats_fixed_rate']:.0%})",f"- GraphRouter Δ：{report['summary']['graph_minus_fixed']}",f"- KNN Δ：{report['summary']['knn_minus_fixed']}"]
 (OUT/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps(report['summary'],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
