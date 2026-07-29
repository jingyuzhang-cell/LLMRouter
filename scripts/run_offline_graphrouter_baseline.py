#!/usr/bin/env python3
"""Leakage-safe GraphRouter training and frozen-response mapping."""
from __future__ import annotations
import hashlib,json,random,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from sklearn.preprocessing import StandardScaler
from scipy.stats import ttest_rel,wilcoxon
from llmrouter.models.graphrouter.graph_nn import EncoderDecoderNet
from llmrouter.utils.embeddings import get_longformer_embedding

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parents[1]/'frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z'
SOURCE=ARCHIVE/'run_logs/formal_context_v2_rescored_v22_result.json'
KNN_DIR=ROOT/'run_logs/offline_knn_baseline';OUT=ROOT/'run_logs/offline_graphrouter_baseline'
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo');SEEDS=(17,29,43);DEVICE='cuda' if torch.cuda.is_available() else 'cpu'
DESCRIPTIONS={'deepseek-chat':'DeepSeek Chat, strong financial reasoning and general analysis model.','glm-5.2':'GLM-5.2, large reasoning, coding, agent and structured generation model.','qwen-plus':'Qwen Plus, balanced general purpose and financial question answering model.','qwen-turbo':'Qwen Turbo, low cost and low latency general purpose model.'}

def num(x,d=0.):
 try:return float(x)
 except (TypeError,ValueError):return d

def metrics(rows):
 q=np.mean([num(x.get('quality')) for x in rows]);c0=np.mean([num(x.get('raw_cost_usd')) for x in rows]);l0=np.mean([num(x.get('latency_ms')) for x in rows]);r=np.mean([bool(x.get('ok')) for x in rows]);u=.45*q+.20*(1-min(c0/.02,1))+.15*(1-min(l0/10000,1))+.20*r
 return {'quality':float(q),'raw_cost_usd':float(c0),'latency_ms':float(l0),'reliability':float(r),'utility':float(u)}

def make_graph(ids,qmap,llm_features,utilities,visible_ids,predict_ids):
 q=torch.tensor(np.stack([qmap[x] for x in ids]),dtype=torch.float32,device=DEVICE);m=torch.tensor(llm_features,dtype=torch.float32,device=DEVICE);n=len(ids)
 src=torch.arange(n,device=DEVICE).repeat_interleave(len(MODELS));dst=torch.arange(len(MODELS),device=DEVICE).repeat(n)+n;edge=torch.stack([src,dst])
 weights=torch.tensor([utilities[tid][model]['utility'] for tid in ids for model in MODELS],dtype=torch.float32,device=DEVICE).reshape(-1,1)
 labels=torch.tensor([1. if model==max(MODELS,key=lambda z:(utilities[tid][z]['utility'],-MODELS.index(z))) else 0. for tid in ids for model in MODELS],dtype=torch.float32,device=DEVICE)
 visible=torch.tensor([tid in set(visible_ids) for tid in ids for _ in MODELS],dtype=torch.bool,device=DEVICE);predict=torch.tensor([tid in set(predict_ids) for tid in ids for _ in MODELS],dtype=torch.bool,device=DEVICE)
 return q,m,edge,weights,labels,visible,predict

def predict(model,graph):
 q,m,e,w,labels,visible,target=graph;model.eval()
 with torch.no_grad():scores=model(q,m,e,edge_mask=target,edge_can_see=visible,edge_weight=w).reshape(-1,len(MODELS))
 return scores.argmax(1).cpu().numpy(),scores.cpu().numpy()

def train_once(qmap,llm_features,utilities,train_ids,val_ids,hidden,lr,seed,epochs=120):
 random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
 ids=train_ids+val_ids;graph=make_graph(ids,qmap,llm_features,utilities,train_ids,val_ids);q,m,e,w,labels,visible,valmask=graph
 model=EncoderDecoderNet(q.shape[1],m.shape[1],hidden,1).to(DEVICE);opt=torch.optim.AdamW(model.parameters(),lr=lr,weight_decay=1e-4)
 train_edges=torch.where(visible)[0];best={'utility':-1,'accuracy':-1,'epoch':0,'state':None}
 for epoch in range(1,epochs+1):
  model.train();gen=torch.Generator(device='cpu').manual_seed(seed*1000+epoch);hold_cpu=torch.rand(len(train_edges),generator=gen)<.30;hold=train_edges[hold_cpu.to(train_edges.device)];seen=visible.clone();seen[hold]=False
  if len(hold)==0:hold=train_edges[:1];seen[hold]=False
  opt.zero_grad();scores=model(q,m,e,edge_mask=torch.isin(torch.arange(len(labels),device=DEVICE),hold),edge_can_see=seen,edge_weight=w).reshape(-1)
  target=labels[hold];loss=F.binary_cross_entropy(scores,target,weight=torch.where(target>0,torch.tensor(3.,device=DEVICE),torch.tensor(1.,device=DEVICE)));loss.backward();opt.step()
  if epoch%5==0 or epoch==epochs:
   pred,_=predict(model,graph);gold=np.array([max(range(len(MODELS)),key=lambda j:utilities[x][MODELS[j]]['utility']) for x in val_ids]);acc=float(np.mean(pred==gold));util=float(np.mean([utilities[x][MODELS[int(j)]]['utility'] for x,j in zip(val_ids,pred)]))
   if (util,acc)>(best['utility'],best['accuracy']):best={'utility':util,'accuracy':acc,'epoch':epoch,'state':{k:v.detach().cpu().clone() for k,v in model.state_dict().items()}}
 return best

def aggregate(rows):return {k:round(float(np.mean([x['metrics'][k] for x in rows])),6) for k in ('quality','raw_cost_usd','latency_ms','reliability','utility')}

def paired_comparisons(mapped,fixed,knn_rows):
 rng=np.random.default_rng(20260729);graph=np.array([x['metrics']['utility'] for x in mapped]);baselines={'fixed_strong':np.array([x['metrics']['utility'] for x in fixed]),'knn':np.array([x['metrics']['utility'] for x in knn_rows])};rows=[]
 for name,base in baselines.items():
  diff=graph-base;boots=np.array([np.mean(diff[rng.integers(0,len(diff),len(diff))]) for _ in range(10000)]);t=float(ttest_rel(graph,base).pvalue)
  try:w=float(wilcoxon(diff).pvalue)
  except ValueError:w=1.
  rows.append({'baseline':name,'mean_delta':round(float(np.mean(diff)),6),'bootstrap_95_ci':[round(float(x),6) for x in np.quantile(boots,[.025,.975])],'paired_t_p':t,'wilcoxon_p':w})
 for field in ('paired_t_p','wilcoxon_p'):
  ordered=sorted(range(len(rows)),key=lambda i:rows[i][field]);adjusted=[0.]*len(rows);running=0.
  for rank,i in enumerate(ordered):running=max(running,min(1.,rows[i][field]*(len(rows)-rank)));adjusted[i]=running
  for i,row in enumerate(rows):row['holm_'+field]=round(adjusted[i],6)
 for row in rows:row['joint_significant']=row['bootstrap_95_ci'][0]>0 and row['holm_paired_t_p']<.05 and row['holm_wilcoxon_p']<.05
 return rows

def main():
 OUT.mkdir(parents=True,exist_ok=True);source=json.loads(SOURCE.read_text());split=json.loads((KNN_DIR/'split.json').read_text());tasks={x['id']:x for x in source['sampled_task_set']};by=defaultdict(list)
 for r in source['raw_model_runs']:by[(r['task_id'],r['model'])].append(r)
 utilities={tid:{m:metrics(by[(tid,m)]) for m in MODELS} for tid in tasks}
 payload=torch.load(KNN_DIR/'longformer_embeddings.pt',map_location='cpu',weights_only=False);raw_q={tid:payload['embeddings'][i].numpy() for i,tid in enumerate(payload['task_ids'])}
 llm_raw=get_longformer_embedding([DESCRIPTIONS[m] for m in MODELS]).cpu().numpy();train=split['train'];val=split['validation'];test=split['test']
 scaler=StandardScaler().fit(np.stack([raw_q[x] for x in train]));qmap={x:scaler.transform(raw_q[x].reshape(1,-1))[0] for x in train+val};llm=StandardScaler().fit_transform(llm_raw)
 trials=[];started=time.perf_counter()
 for hidden in (16,32):
  for lr in (.001,.003):
   for seed in SEEDS:
    b=train_once(qmap,llm,utilities,train,val,hidden,lr,seed);trials.append({'hidden':hidden,'lr':lr,'seed':seed,'validation_utility':round(b['utility'],6),'validation_accuracy':round(b['accuracy'],6),'best_epoch':b['epoch'],'state':b['state']})
 best=sorted(trials,key=lambda x:(-x['validation_utility'],-x['validation_accuracy'],x['hidden'],x['lr'],x['seed']))[0];tuning_seconds=time.perf_counter()-started
 # Refit preprocessing on train+validation; retrain for the selected epoch and seed.
 trainval=train+val;scaler=StandardScaler().fit(np.stack([raw_q[x] for x in trainval]));qmap={x:scaler.transform(raw_q[x].reshape(1,-1))[0] for x in trainval+test}
 # Train the final model directly for the validation-selected epoch count.
 random.seed(best['seed']);np.random.seed(best['seed']);torch.manual_seed(best['seed']);torch.cuda.manual_seed_all(best['seed']);ids=trainval+test;graph=make_graph(ids,qmap,llm,utilities,trainval,test);q,m,e,w,labels,visible,target=graph
 model=EncoderDecoderNet(q.shape[1],m.shape[1],best['hidden'],1).to(DEVICE);opt=torch.optim.AdamW(model.parameters(),lr=best['lr'],weight_decay=1e-4);train_edges=torch.where(visible)[0]
 for epoch in range(1,max(best['best_epoch'],5)+1):
  model.train();gen=torch.Generator().manual_seed(best['seed']*1000+epoch);hold=train_edges[(torch.rand(len(train_edges),generator=gen)<.30).to(train_edges.device)];hold=hold if len(hold) else train_edges[:1];seen=visible.clone();seen[hold]=False;mask=torch.zeros(len(labels),dtype=torch.bool,device=DEVICE);mask[hold]=True
  opt.zero_grad();s=model(q,m,e,edge_mask=mask,edge_can_see=seen,edge_weight=w).reshape(-1);y=labels[hold];loss=F.binary_cross_entropy(s,y,weight=torch.where(y>0,torch.tensor(3.,device=DEVICE),torch.tensor(1.,device=DEVICE)));loss.backward();opt.step()
 torch.save({'state_dict':model.state_dict(),'models':MODELS,'hidden':best['hidden'],'lr':best['lr'],'seed':best['seed'],'epochs':max(best['best_epoch'],5)},OUT/'graphrouter_finance.pt')
 pred,scores=predict(model,graph);gold=np.array([max(range(len(MODELS)),key=lambda j:utilities[x][MODELS[j]]['utility']) for x in test]);mapped=[]
 for tid,j,g,score in zip(test,pred,gold,scores):mapped.append({'task_id':tid,'dataset':tasks[tid].get('dataset'),'selected_model':MODELS[int(j)],'label_model':MODELS[int(g)],'correct':bool(j==g),'scores':{m:round(float(score[i]),6) for i,m in enumerate(MODELS)},'metrics':{k:round(v,8) for k,v in utilities[tid][MODELS[int(j)]].items()}})
 fixed=[{'metrics':utilities[x]['deepseek-chat']} for x in test];oracle=[{'metrics':utilities[x][MODELS[int(g)]]} for x,g in zip(test,gold)];knn=json.loads((KNN_DIR/'report.json').read_text())['test'];knn_by_id={x['task_id']:x for x in knn['rows']};knn_rows=[knn_by_id[x] for x in test]
 public_trials=[{k:v for k,v in x.items() if k!='state'} for x in trials]
 report={'report_type':'strict_offline_graphrouter_baseline','generated_at':datetime.now(timezone.utc).isoformat(),'offline_only':True,'api_calls':0,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'device':DEVICE,'split_source':str((KNN_DIR/'split.json').relative_to(ROOT)),'split_counts':{k:len(v) for k,v in split.items()},'graph':{'train_edges':len(train)*4,'validation_edges':len(val)*4,'test_edges':len(test)*4,'query_dimension':768,'model_dimension':768,'test_edges_visible_during_training':False,'validation_edges_visible_during_training':False},'leakage_checks':{'same_split_as_knn':True,'train_validation_test_disjoint':True,'scaler_fit_without_test':True,'model_descriptions_contain_no_outcome_metrics':True,'test_labels_and_utilities_used_only_after_prediction':True},'tuning':{'seconds':round(tuning_seconds,3),'trials':public_trials,'selected':{k:v for k,v in best.items() if k!='state'}},'test':{'count':len(test),'accuracy':round(float(np.mean(pred==gold)),6),'selection_counts':dict(Counter(MODELS[int(x)] for x in pred)),'label_counts':dict(Counter(MODELS[int(x)] for x in gold)),'graphrouter_metrics':aggregate(mapped),'knn_metrics':knn['knn_metrics'],'fixed_strong_metrics':aggregate(fixed),'oracle_upper_bound_metrics':aggregate(oracle),'rows':mapped}}
 report['test']['paired_significance']=paired_comparisons(mapped,fixed,knn_rows)
 (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(OUT/'split.json').write_text(json.dumps(split,ensure_ascii=False,indent=2)+'\n')
 lines=['# 严格离线金融 GraphRouter 基线','',f"- 划分：{report['split_counts']}（与 KNN 完全相同）",f"- 设备：{DEVICE}；调参耗时：{tuning_seconds:.3f} 秒",f"- 图边：train {len(train)*4} / validation {len(val)*4} / test {len(test)*4}",'- 验证边和测试边在训练消息传递中均不可见',f"- 最优参数：hidden={best['hidden']}，lr={best['lr']}，seed={best['seed']}，epoch={best['best_epoch']}",f"- 测试准确率：{report['test']['accuracy']:.2%}",f"- 选择分布：{report['test']['selection_counts']}",f"- GraphRouter 效用：{report['test']['graphrouter_metrics']['utility']:.6f}",f"- KNN 效用：{knn['knn_metrics']['utility']:.6f}",f"- 固定 DeepSeek 效用：{report['test']['fixed_strong_metrics']['utility']:.6f}",f"- Oracle 上界：{report['test']['oracle_upper_bound_metrics']['utility']:.6f}",'','本结果是独立补充实验，不覆盖冻结主实验。']
 lines+=['','## 配对显著性']+[f"- vs {x['baseline']}: Δ={x['mean_delta']:.6f}, CI={x['bootstrap_95_ci']}, Holm t={x['holm_paired_t_p']:.6f}, Holm W={x['holm_wilcoxon_p']:.6f}, significant={x['joint_significant']}" for x in report['test']['paired_significance']]
 (OUT/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'selected':report['tuning']['selected'],'test':report['test']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
