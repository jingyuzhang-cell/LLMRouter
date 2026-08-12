#!/usr/bin/env python3
"""Formal KNN/MLP/neural-GraphRouter 5-fold OOF and Meta study."""
from __future__ import annotations
import hashlib,json,math,random,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import numpy as np,torch
import torch.nn.functional as F
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,mean_absolute_error,roc_auc_score
from sklearn.model_selection import KFold
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from llmrouter.models.mlprouter.router import MLPClassifierNN
from llmrouter.models.graphrouter.graph_nn import EncoderDecoderNet

ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parents[1]/'frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z/run_logs/formal_context_v2_rescored_v22_result.json';SPLIT=ROOT/'run_logs/offline_knn_baseline/split.json';EMB=ROOT/'run_logs/offline_knn_baseline/longformer_embeddings.pt';OUT=ROOT/'run_logs/finrome_formal_oof'
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo');ROUTERS=('knnrouter','mlprouter','graphrouter');SEED=20260808;DEVICE='cuda' if torch.cuda.is_available() else 'cpu';MF=np.eye(4,dtype=np.float32)
def seed(s):random.seed(s);np.random.seed(s);torch.manual_seed(s);torch.cuda.manual_seed_all(s) if torch.cuda.is_available() else None
def num(x,d=0.):
 try:return float(x)
 except:return d
def risk(t):
 x=str(t.get('risk',t.get('risk_level','.62'))).lower()
 if x in {'low','medium','high'}:return x
 return 'high' if num(x)>=.8 else 'medium' if num(x)>=.4 else 'low'
def tf(t):
 kinds=('financial_numerical_reasoning','financial_table_text_reasoning','financial_audit_compliance_qa','financial_kg_grounded_qa','financial_kg_multihop_qa');r=risk(t)
 return np.array([num(t.get('complexity'),.5),{'low':.2,'medium':.62,'high':.86}[r],float(bool(t.get('requires_calculation'))),float(bool(t.get('requires_table_reasoning'))),float(bool(t.get('requires_kg_reasoning'))),min(len(str(t.get('query',''))),5000)/5000,*[float(t.get('task_type')==k) for k in kinds]],dtype=np.float32)
def metrics(rows):
 q=np.mean([num(x.get('quality')) for x in rows]);c=np.mean([num(x.get('raw_cost_usd')) for x in rows]);l=np.mean([num(x.get('latency_ms')) for x in rows]);rel=np.mean([bool(x.get('ok')) for x in rows]);u=.45*q+.2*(1-min(c/.02,1))+.15*(1-min(l/10000,1))+.2*rel
 return np.array([q,c,l,rel,u,float(rel<1 or q<.6)])
def rank(s):return np.argsort(np.argsort(s,axis=1),axis=1)/max(1,s.shape[1]-1)
def soft(s):z=s-s.max(1,keepdims=True);e=np.exp(z);return e/e.sum(1,keepdims=True)
def meta_x(b,s):p=soft(s);o=np.sort(s,axis=1);return np.c_[b,s,o[:,-1]-o[:,-2],-(p*np.log(np.maximum(p,1e-12))).sum(1)]
class ConstC:
 def __init__(self,v):self.v=float(v)
 def predict_proba(self,x):p=np.full(len(x),self.v);return np.c_[1-p,p]
class ConstR:
 def __init__(self,v):self.v=float(v)
 def predict(self,x):return np.full(len(x),self.v)
def fc(x,y):return ConstC(y.mean()) if len(np.unique(y))<2 else LogisticRegression(max_iter=1500,class_weight='balanced',C=.5,random_state=SEED).fit(x,y)
def fr(x,y):return ConstR(y.mean()) if np.std(y)<1e-10 else GradientBoostingRegressor(n_estimators=80,max_depth=2,learning_rate=.035,loss='huber',random_state=SEED).fit(x,y)
def ece(y,p):
 z=0.
 for a,b in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
  m=(p>=a)&(p<(b) if b<1 else p<=b)
  if m.any():z+=m.mean()*abs(p[m].mean()-y[m].mean())
 return float(z)
def auc(y,p):return float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None
def train_knn(x,y,u,s):return KNeighborsClassifier(n_neighbors=min(7,len(x)),weights='distance',metric='cosine',algorithm='brute').fit(x,y)
def score_knn(m,x):
 out=np.zeros((len(x),4));p=m.predict_proba(x)
 for j,c in enumerate(m.classes_):out[:,int(c)]=p[:,j]
 return out
def train_mlp(x,y,u,s):
 seed(s);sc=StandardScaler().fit(x);z=torch.tensor(sc.transform(x),dtype=torch.float32,device=DEVICE);v=torch.tensor(u,dtype=torch.float32,device=DEVICE);tie=torch.isclose(v,v.max(1,keepdim=True).values,atol=1e-8).float();target=.8*tie/tie.sum(1,keepdim=True)+.2*torch.softmax(v/.1,1);reg=v.max(1,keepdim=True).values-v;m=MLPClassifierNN(x.shape[1],[64,32],4,'relu').to(DEVICE);opt=torch.optim.AdamW(m.parameters(),lr=8e-4,weight_decay=2e-3);best=None;bl=1e9
 for _ in range(180):
  m.train();opt.zero_grad();log=m(z);loss=(-(target*torch.log_softmax(log,1)).sum(1)+(torch.softmax(log,1)*reg).sum(1)).mean();loss.backward();opt.step()
  if float(loss)<bl:bl=float(loss);best={k:w.detach().cpu().clone() for k,w in m.state_dict().items()}
 m.load_state_dict(best);m.eval();return m,sc
def score_mlp(bundle,x):
 m,sc=bundle
 with torch.no_grad():return torch.softmax(m(torch.tensor(sc.transform(x),dtype=torch.float32,device=DEVICE)),1).cpu().numpy()
def gt(x,u):
 n=len(x);q=torch.tensor(x,dtype=torch.float32,device=DEVICE);mf=torch.tensor(MF,dtype=torch.float32,device=DEVICE);src=torch.arange(n,device=DEVICE).repeat_interleave(4);dst=torch.arange(4,device=DEVICE).repeat(n)+n;e=torch.stack([src,dst]);w=torch.tensor(u.reshape(-1,1),dtype=torch.float32,device=DEVICE);lab=torch.tensor((u==u.max(1,keepdims=True)).astype(float).reshape(-1),dtype=torch.float32,device=DEVICE);return q,mf,e,w,lab
def train_graph(x,y,u,s):
 seed(s);sc=StandardScaler().fit(x);q,mf,e,w,lab=gt(sc.transform(x),u);target=torch.tensor(((u-u.min(1,keepdims=True))/(np.ptp(u,axis=1,keepdims=True)+1e-6)).reshape(-1),dtype=torch.float32,device=DEVICE);m=EncoderDecoderNet(x.shape[1],4,32,1).to(DEVICE);opt=torch.optim.AdamW(m.parameters(),lr=.002,weight_decay=1e-4);all=torch.ones(len(lab),dtype=torch.bool,device=DEVICE);best=None;bl=1e9
 for ep in range(140):
  m.train();g=torch.Generator().manual_seed(s*1000+ep);hold=(torch.rand(len(lab),generator=g)<.3).to(DEVICE);hold[0]=True if not hold.any() else hold[0];opt.zero_grad();p=m(q,mf,e,edge_mask=hold,edge_can_see=all&~hold,edge_weight=w);t=target[hold];loss=F.smooth_l1_loss(p,t);loss.backward();opt.step()
  if float(loss)<bl:bl=float(loss);best={k:v.detach().cpu().clone() for k,v in m.state_dict().items()}
 m.load_state_dict(best);m.eval();return m,sc,x.copy(),u.copy()
def score_graph(bundle,x):
 m,sc,tr,u=bundle;n=len(tr);q,mf,e,w,_=gt(sc.transform(np.vstack([tr,x])),np.vstack([u,np.zeros((len(x),4))]));vis=torch.zeros(len(w),dtype=torch.bool,device=DEVICE);vis[:n*4]=True
 with torch.no_grad():return m(q,mf,e,edge_mask=~vis,edge_can_see=vis,edge_weight=w).reshape(len(x),4).cpu().numpy()
TRAIN={'knnrouter':train_knn,'mlprouter':train_mlp,'graphrouter':train_graph};SCORE={'knnrouter':score_knn,'mlprouter':score_mlp,'graphrouter':score_graph}
def summary(ids,sel,labels,outcomes,risks):
 rows=[]
 for t,m in zip(ids,sel):o=labels[t];v=outcomes[t][m];rows.append({'task_id':t,'selected':int(m),'oracle':o,'utility':float(v[4]),'failure':float(v[5]),'regret':float(outcomes[t][o,4]-v[4]),'risk':risks[t]})
 h=[x for x in rows if x['risk']=='high'];return {'count':len(rows),'accuracy':float(np.mean([x['selected']==x['oracle'] for x in rows])),'utility':float(np.mean([x['utility'] for x in rows])),'failure_rate':float(np.mean([x['failure'] for x in rows])),'high_risk_failure_rate':float(np.mean([x['failure'] for x in h])) if h else None,'mean_regret':float(np.mean([x['regret'] for x in rows])),'selection_counts':dict(Counter(MODELS[x['selected']] for x in rows)),'rows':rows}
def main():
 OUT.mkdir(parents=True,exist_ok=True);start=time.perf_counter();src=json.loads(SOURCE.read_text());sp=json.loads(SPLIT.read_text());tasks={x['id']:x for x in src['sampled_task_set']};risks={t:risk(x) for t,x in tasks.items()};by=defaultdict(list)
 for r in src['raw_model_runs']:by[(r['task_id'],r['model'])].append(r)
 outcomes={t:np.stack([metrics(by[(t,m)]) for m in MODELS]) for t in tasks};utilities={t:outcomes[t][:,4] for t in tasks};labels={t:int(np.argmax(utilities[t])) for t in tasks};p=torch.load(EMB,map_location='cpu',weights_only=False);emb={t:p['embeddings'][i].numpy() for i,t in enumerate(p['task_ids'])};xmap={t:np.r_[emb[t],tf(tasks[t])] for t in tasks};bmap={t:tf(tasks[t]) for t in tasks};train,cal,test=sp['train'],sp['validation'],sp['test'];cnt=Counter(labels[t] for t in train);rare_labels={k:v for k,v in cnt.items() if v<5};rare=[t for t in train if labels[t] in rare_labels];common=[t for t in train if t not in rare];folds=list(KFold(5,shuffle=True,random_state=SEED).split(common));oof={r:np.zeros((len(common),4)) for r in ROUTERS}
 for f,(ii,hh) in enumerate(folds):
  fi=[common[i] for i in ii]+rare;hi=[common[i] for i in hh];x=np.stack([xmap[t] for t in fi]);y=np.array([labels[t] for t in fi]);u=np.stack([utilities[t] for t in fi]);xh=np.stack([xmap[t] for t in hi])
  for r in ROUTERS:oof[r][hh]=SCORE[r](TRAIN[r](x,y,u,SEED+f),xh)
 assert all(np.isfinite(oof[r]).all() for r in ROUTERS);yc=np.array([labels[t] for t in common]);uc=np.stack([utilities[t] for t in common]);bc=np.stack([bmap[t] for t in common]);delta=.03;truth={};cv={r:{k:np.zeros(len(common)) for k in ('accept','fail','regret')} for r in ROUTERS};meta={}
 for r in ROUTERS:
  sel=oof[r].argmax(1);reg=uc.max(1)-uc[np.arange(len(common)),sel];fail=np.array([outcomes[t][m,5] for t,m in zip(common,sel)]);acc=(reg<=delta).astype(int);truth[r]=(acc,fail,reg);z=meta_x(bc,oof[r])
  for ii,hh in folds:cv[r]['accept'][hh]=fc(z[ii],acc[ii]).predict_proba(z[hh])[:,1];cv[r]['fail'][hh]=fc(z[ii],fail[ii]).predict_proba(z[hh])[:,1];cv[r]['regret'][hh]=fr(z[ii],reg[ii]).predict(z[hh])
  pa,pf,pr=cv[r]['accept'],cv[r]['fail'],cv[r]['regret'];safe=pa>=.5;meta[r]={'acceptable_brier':float(brier_score_loss(acc,pa)),'acceptable_ece':ece(acc,pa),'acceptable_auroc':auc(acc,pa),'failure_brier':float(brier_score_loss(fail,pf)),'failure_ece':ece(fail,pf),'failure_auroc':auc(fail,pf),'regret_mae':float(mean_absolute_error(reg,pr)),'safe_router_recall':float(safe[acc==1].mean()) if np.any(acc==1) else None,'unsafe_router_rejection_rate':float((~safe[acc==0]).mean()) if np.any(acc==0) else None,'risk_coverage':[{'coverage':q,'risk':float(fail[np.argsort(pf)[:max(1,math.ceil(len(fail)*q))]].mean())} for q in (.2,.4,.6,.8,1.)]}
 xtr=np.stack([xmap[t] for t in train]);ytr=np.array([labels[t] for t in train]);utr=np.stack([utilities[t] for t in train]);xt=np.stack([xmap[t] for t in test]);final={r:TRAIN[r](xtr,ytr,utr,SEED+100) for r in ROUTERS};ts={r:SCORE[r](final[r],xt) for r in ROUTERS};bt=np.stack([bmap[t] for t in test]);mt={}
 for r in ROUTERS:
  z=meta_x(bc,oof[r]);acc,fail,reg=truth[r];zt=meta_x(bt,ts[r]);mt[r]={'accept':fc(z,acc).predict_proba(zt)[:,1],'fail':fc(z,fail).predict_proba(zt)[:,1],'regret':np.maximum(0,fr(z,reg).predict(zt))}
 equal=np.mean([rank(ts[r]) for r in ROUTERS],axis=0);dyn=np.zeros_like(equal)
 for i in range(len(test)):
  w=np.array([math.exp(2*mt[r]['accept'][i]-2*mt[r]['fail'][i]-mt[r]['regret'][i]) for r in ROUTERS]);w/=w.sum();dyn[i]=sum(a*rank(ts[r][i:i+1])[0] for a,r in zip(w,ROUTERS))
 m0o={r:summary(common,oof[r].argmax(1),labels,outcomes,risks) for r in ROUTERS};m0={r:summary(test,ts[r].argmax(1),labels,outcomes,risks) for r in ROUTERS};m1=summary(test,equal.argmax(1),labels,outcomes,risks);m2=summary(test,dyn.argmax(1),labels,outcomes,risks);err={r:oof[r].argmax(1)!=yc for r in ROUTERS};pairs={}
 for i,a in enumerate(ROUTERS):
  for b in ROUTERS[i+1:]:pairs[a+'__'+b]={'error_correlation':float(np.corrcoef(err[a],err[b])[0,1]) if err[a].std() and err[b].std() else None,'double_fault':float(np.mean(err[a]&err[b]))}
 report={'report_type':'formal_three_router_five_fold_oof','generated_at':datetime.now(timezone.utc).isoformat(),'seconds':time.perf_counter()-start,'device':DEVICE,'offline_only':True,'api_calls':0,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'data':{'complete_matrices':len(tasks),'requested_300_minimum_met':len(tasks)>=300,'split':{'train':len(train),'calibration':len(cal),'test':len(test)},'risk_counts':dict(Counter(risks.values()))},'leakage':{'shared_split':True,'five_fold_oof':True,'rare_train_only':True,'rare_ids':rare,'rare_labels':{MODELS[k]:v for k,v in rare_labels.items()},'rare_samples_duplicated':False,'test_used_for_fit':False},'implementations':{'knn':'cosine KNN','mlp':'project MLPClassifierNN soft utility+regret loss','graph':'project neural EncoderDecoderNet; held-out edges invisible'},'oof':{'M0':m0o,'M1':summary(common,np.mean([rank(oof[r]) for r in ROUTERS],axis=0).argmax(1),labels,outcomes,risks),'pairwise':pairs,'expert_coverage':float(np.mean(np.any(np.stack([~err[r] for r in ROUTERS]),axis=0)))},'meta_validation':meta,'test':{'M0':m0,'M1':m1,'M2':m2},'decision':{'M2_beats_M1_utility':m2['utility']>m1['utility'],'M2_beats_M1_regret':m2['mean_regret']<m1['mean_regret'],'M2_beats_M1_high_risk_failure':m2['high_risk_failure_rate']<m1['high_risk_failure_rate']},'limitations':['Only 100 complete matrices exist; expansion to >=300 requires new model evaluations.','Calibration is reserved and untouched in this OOF/M0-M2 study.']};(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');lines=['# 正式三 Router 5-fold OOF','',f"- 数据：100 完整矩阵；60/20/20；设备 {DEVICE}",f"- 稀有标签仅训练：{report['leakage']['rare_labels']}",f"- OOF 专家覆盖率：{report['oof']['expert_coverage']:.2%}",'',f"- M1 utility={m1['utility']:.6f}, regret={m1['mean_regret']:.6f}, high-risk failure={m1['high_risk_failure_rate']:.2%}",f"- M2 utility={m2['utility']:.6f}, regret={m2['mean_regret']:.6f}, high-risk failure={m2['high_risk_failure_rate']:.2%}",f"- M2通过门禁：{report['decision']}",'','当前不足300个完整矩阵，不能执行目标规模的共形覆盖声明。'];(OUT/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'out':str(OUT),'device':DEVICE,'rare':report['leakage']['rare_labels'],'M1':{k:v for k,v in m1.items() if k!='rows'},'M2':{k:v for k,v in m2.items() if k!='rows'},'decision':report['decision']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
