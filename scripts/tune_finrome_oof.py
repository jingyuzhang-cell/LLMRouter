#!/usr/bin/env python3
"""OOF-only GraphRouter and Meta policy search; test is read after freezing."""
from __future__ import annotations
import json,math,time
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np,torch
import torch.nn.functional as F
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from llmrouter.models.graphrouter.graph_nn import EncoderDecoderNet
import scripts.run_finrome_formal_oof as b

OUT=b.ROOT/'run_logs/finrome_oof_tuning';OUT.mkdir(parents=True,exist_ok=True)
def train_graph(x,u,cfg,seed):
 b.seed(seed);sc=StandardScaler().fit(x);q,mf,e,w,lab=b.gt(sc.transform(x),u);target=torch.tensor(((u-u.min(1,keepdims=True))/(np.ptp(u,axis=1,keepdims=True)+1e-6)).reshape(-1),dtype=torch.float32,device=b.DEVICE);m=EncoderDecoderNet(x.shape[1],4,cfg['hidden'],1).to(b.DEVICE);opt=torch.optim.AdamW(m.parameters(),lr=cfg['lr'],weight_decay=1e-4);all=torch.ones(len(lab),dtype=torch.bool,device=b.DEVICE);best=None;bl=1e9
 for ep in range(90):
  m.train();g=torch.Generator().manual_seed(seed*1000+ep);hold=(torch.rand(len(lab),generator=g)<cfg['mask']).to(b.DEVICE)
  if not hold.any():hold[0]=True
  opt.zero_grad();p=m(q,mf,e,edge_mask=hold,edge_can_see=all&~hold,edge_weight=w);t=target[hold];loss=F.smooth_l1_loss(p,t);loss.backward();opt.step();v=float(loss.detach())
  if v<bl:bl=v;best={k:z.detach().cpu().clone() for k,z in m.state_dict().items()}
 m.load_state_dict(best);m.eval();return m,sc,x.copy(),u.copy()
def load():
 src=json.loads(b.SOURCE.read_text());sp=json.loads(b.SPLIT.read_text());tasks={x['id']:x for x in src['sampled_task_set']};risks={t:b.risk(x) for t,x in tasks.items()};by=defaultdict(list)
 for r in src['raw_model_runs']:by[(r['task_id'],r['model'])].append(r)
 out={t:np.stack([b.metrics(by[(t,m)]) for m in b.MODELS]) for t in tasks};util={t:out[t][:,4] for t in tasks};labels={t:int(np.argmax(util[t])) for t in tasks};p=torch.load(b.EMB,map_location='cpu',weights_only=False);emb={t:p['embeddings'][i].numpy() for i,t in enumerate(p['task_ids'])};xm={t:np.r_[emb[t],b.tf(tasks[t])] for t in tasks};bm={t:b.tf(tasks[t]) for t in tasks};return sp,tasks,risks,out,util,labels,xm,bm
def main():
 started=time.perf_counter();sp,tasks,risks,out,u,labels,xm,bm=load();train,cal,test=sp['train'],sp['validation'],sp['test'];cnt=Counter(labels[t] for t in train);rare=[t for t in train if cnt[labels[t]]<5];common=[t for t in train if t not in rare];folds=list(KFold(5,shuffle=True,random_state=b.SEED).split(common));base={r:np.zeros((len(common),4)) for r in ('knnrouter','mlprouter')}
 for f,(ii,hh) in enumerate(folds):
  fi=[common[i] for i in ii]+rare;hi=[common[i] for i in hh];x=np.stack([xm[t] for t in fi]);y=np.array([labels[t] for t in fi]);uu=np.stack([u[t] for t in fi]);xh=np.stack([xm[t] for t in hi])
  for r in base:base[r][hh]=b.SCORE[r](b.TRAIN[r](x,y,uu,b.SEED+f),xh)
 configs=[{'hidden':h,'mask':m,'positive_weight':w,'lr':lr,'seed':s} for h in (16,32) for m in (.2,.4) for w in (2.,4.) for lr in (.001,.003) for s in (17,29,43)];trials=[];best_graph=None
 for n,cfg in enumerate(configs,1):
  scores=np.zeros((len(common),4))
  for f,(ii,hh) in enumerate(folds):
   fi=[common[i] for i in ii]+rare;hi=[common[i] for i in hh];x=np.stack([xm[t] for t in fi]);uu=np.stack([u[t] for t in fi]);scores[hh]=b.score_graph(train_graph(x,uu,cfg,cfg['seed']+f),np.stack([xm[t] for t in hi]))
  sm=b.summary(common,scores.argmax(1),labels,out,risks);row={**cfg,'utility':sm['utility'],'regret':sm['mean_regret'],'failure':sm['failure_rate'],'high_failure':sm['high_risk_failure_rate'],'accuracy':sm['accuracy']};trials.append(row)
  if best_graph is None or (row['utility'],-row['regret'],-row['high_failure'])>(best_graph[0]['utility'],-best_graph[0]['regret'],-best_graph[0]['high_failure']):best_graph=(row,scores.copy())
  if n%8==0:print(json.dumps({'progress':f'{n}/{len(configs)}','best':best_graph[0]},ensure_ascii=False),flush=True)
 graph=best_graph[1];oof={**base,'graphrouter':graph};bc=np.stack([bm[t] for t in common]);uc=np.stack([u[t] for t in common]);meta_cv={r:{k:np.zeros(len(common)) for k in ('accept','fail','regret')} for r in b.ROUTERS};truth={}
 for r in b.ROUTERS:
  sel=oof[r].argmax(1);reg=uc.max(1)-uc[np.arange(len(common)),sel];fail=np.array([out[t][m,5] for t,m in zip(common,sel)]);acc=(reg<=.03).astype(int);truth[r]=(acc,fail,reg);z=b.meta_x(bc,oof[r])
  for ii,hh in folds:meta_cv[r]['accept'][hh]=b.fc(z[ii],acc[ii]).predict_proba(z[hh])[:,1];meta_cv[r]['fail'][hh]=b.fc(z[ii],fail[ii]).predict_proba(z[hh])[:,1];meta_cv[r]['regret'][hh]=b.fr(z[ii],reg[ii]).predict(z[hh])
 router_perf={r:b.summary(common,oof[r].argmax(1),labels,out,risks) for r in b.ROUTERS};best_router=max(b.ROUTERS,key=lambda r:router_perf[r]['utility']);bp=router_perf[best_router]
 admitted=[r for r in b.ROUTERS if router_perf[r]['utility']>=bp['utility']-.015 and router_perf[r]['failure_rate']<=bp['failure_rate']+.03 and router_perf[r]['high_risk_failure_rate']<=bp['high_risk_failure_rate']+.04]
 if best_router not in admitted:admitted.append(best_router)
 grids=[]
 for a in range(11):
  for c in range(11-a):
   d=10-a-c;w=np.array([a,c,d],dtype=float)/10
   if all((r in admitted) or w[i]==0 for i,r in enumerate(b.ROUTERS)):grids.append(w)
 if not grids:
  w=np.zeros(3);w[b.ROUTERS.index(best_router)]=1;grids=[w]
 target=np.array([1/len(admitted) if r in admitted else 0 for r in b.ROUTERS]);weight_trials=[]
 for w in grids:
  score=sum(w[i]*b.rank(oof[r]) for i,r in enumerate(b.ROUTERS));sm=b.summary(common,score.argmax(1),labels,out,risks);obj=sm['utility']-.002*float(np.square(w-target).sum());weight_trials.append({'weights':w.tolist(),'objective':obj,'utility':sm['utility'],'regret':sm['mean_regret'],'failure':sm['failure_rate'],'high_failure':sm['high_risk_failure_rate']})
 best_weight=max(weight_trials,key=lambda z:(z['objective'],-z['regret'],-z['high_failure']));global_w=np.array(best_weight['weights']);base_oof=sum(global_w[i]*b.rank(oof[r]) for i,r in enumerate(b.ROUTERS));base_sel=base_oof.argmax(1);m1_oof=b.summary(common,base_sel,labels,out,risks);policies=[]
 for ca in (0.,.5,1.,2.):
  for cf in (0.,.5,1.,2.,4.):
   for cr in (0.,2.,5.,10.):
    if ca+cf+cr==0:continue
    for eta in (.1,.25,.5):
     fused=np.zeros_like(base_oof)
     for i in range(len(common)):
      merit=np.array([ca*meta_cv[r]['accept'][i]-cf*meta_cv[r]['fail'][i]-cr*meta_cv[r]['regret'][i] for r in b.ROUTERS]);cw=global_w*np.exp(eta*(merit-merit.mean()));cw/=cw.sum();fused[i]=sum(cw[j]*b.rank(oof[r][i:i+1])[0] for j,r in enumerate(b.ROUTERS))
     chosen=fused.argmax(1);sm=b.summary(common,chosen,labels,out,risks);intervention=float(np.mean(chosen!=base_sel));policies.append({'mode':'residual_convex','ca':ca,'cf':cf,'cr':cr,'eta':eta,'global_weights':global_w.tolist(),'admitted_routers':admitted,'utility':sm['utility'],'regret':sm['mean_regret'],'failure':sm['failure_rate'],'high_failure':sm['high_risk_failure_rate'],'intervention_rate':intervention,'meta_active':True})
 feasible=[z for z in policies if z['intervention_rate']>=.03 and z['failure']<=m1_oof['failure_rate']+.005 and z['high_failure']<=m1_oof['high_risk_failure_rate']+.01]
 if not feasible:feasible=[z for z in policies if z['intervention_rate']>=.03 and z['failure']<=m1_oof['failure_rate']+.01]
 best_policy=max(feasible,key=lambda z:(z['utility'],-z['regret'],-z['high_failure'],-z['failure'],-z['eta'])) if feasible else {'mode':'residual_convex','ca':0.,'cf':0.,'cr':0.,'eta':0.,'global_weights':global_w.tolist(),'admitted_routers':admitted,'utility':m1_oof['utility'],'regret':m1_oof['mean_regret'],'failure':m1_oof['failure_rate'],'high_failure':m1_oof['high_risk_failure_rate'],'intervention_rate':0.,'meta_active':False}
 gate=bool(best_policy['meta_active'] and best_policy['utility']>m1_oof['utility'] and best_policy['regret']<=m1_oof['mean_regret'])
 # Freeze inner-OOF choices, then train once and read outer test.
 xtr=np.stack([xm[t] for t in train]);ytr=np.array([labels[t] for t in train]);utr=np.stack([u[t] for t in train]);xt=np.stack([xm[t] for t in test]);final={'knnrouter':b.train_knn(xtr,ytr,utr,b.SEED),'mlprouter':b.train_mlp(xtr,ytr,utr,b.SEED+100),'graphrouter':train_graph(xtr,utr,best_graph[0],best_graph[0]['seed']+100)};ts={r:b.SCORE[r](final[r],xt) for r in b.ROUTERS};bt=np.stack([bm[t] for t in test]);mt={}
 for r in b.ROUTERS:
  z=b.meta_x(bc,oof[r]);acc,fail,reg=truth[r];zt=b.meta_x(bt,ts[r]);mt[r]={'accept':b.fc(z,acc).predict_proba(zt)[:,1],'fail':b.fc(z,fail).predict_proba(zt)[:,1],'regret':np.maximum(0,b.fr(z,reg).predict(zt))}
 m1score=sum(global_w[i]*b.rank(ts[r]) for i,r in enumerate(b.ROUTERS));m2score=m1score.copy()
 if gate:
  for i in range(len(test)):
   merit=np.array([best_policy['ca']*mt[r]['accept'][i]-best_policy['cf']*mt[r]['fail'][i]-best_policy['cr']*mt[r]['regret'][i] for r in b.ROUTERS]);cw=global_w*np.exp(best_policy['eta']*(merit-merit.mean()));cw/=cw.sum();m2score[i]=sum(cw[j]*b.rank(ts[r][i:i+1])[0] for j,r in enumerate(b.ROUTERS))
 m1=b.summary(test,m1score.argmax(1),labels,out,risks);m2=b.summary(test,m2score.argmax(1),labels,out,risks);report={'report_type':'oof_gated_convex_residual_meta_v2','seconds':time.perf_counter()-started,'device':b.DEVICE,'graph_objective':'normalized utility regression','graph_trials':trials,'selected_graph':best_graph[0],'router_performance':{r:{k:v for k,v in x.items() if k!='rows'} for r,x in router_perf.items()},'admitted_routers':admitted,'weight_trials':weight_trials,'selected_global_weights':global_w.tolist(),'meta_policies':policies,'selected_meta_policy':best_policy,'oof_M1':{k:v for k,v in m1_oof.items() if k!='rows'},'oof_gate_passed':gate,'test':{'M1':m1,'M2':m2},'test_gate':{'utility':m2['utility']>m1['utility'],'regret':m2['mean_regret']<m1['mean_regret'],'high_failure':m2['high_risk_failure_rate']<m1['high_risk_failure_rate']},'selection_contract':'expert admission, convex weights and residual policy selected on inner OOF only; outer test read once'};(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(OUT/'report.md').write_text(f"# OOF gated convex residual Meta v2\n\n- admitted={admitted}\n- weights={global_w.tolist()}\n- Meta={best_policy}\n- gate={gate}\n- M1={m1['utility']:.6f}\n- M2={m2['utility']:.6f}\n");print(json.dumps({'out':str(OUT),'admitted':admitted,'weights':global_w.tolist(),'meta':best_policy,'oof_gate':gate,'M1':{k:v for k,v in m1.items() if k!='rows'},'M2':{k:v for k,v in m2.items() if k!='rows'}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
