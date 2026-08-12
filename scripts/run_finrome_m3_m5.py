#!/usr/bin/env python3
"""Run M3--M5 after the OOF M2 gate has passed; no test tuning."""
from __future__ import annotations
import json,math,os,re
from collections import defaultdict
from pathlib import Path
import numpy as np,torch
from sklearn.model_selection import KFold
from openclaw_router.experiment_protocol import objective_score
import scripts.run_finrome_formal_oof as b
import scripts.tune_finrome_oof as t
OUT=b.ROOT/'run_logs/finrome_m3_m5';OUT.mkdir(parents=True,exist_ok=True)
def fq(v,c):
 if not len(v):return 1.
 q=min(1,math.ceil((len(v)+1)*c)/len(v));return float(np.quantile(v,q,method='higher'))
def main():
 tuning=json.loads((t.OUT/'report.json').read_text());meta_enabled=bool(tuning['oof_gate_passed']);cfg=tuning['selected_graph'];pol=tuning['selected_meta_policy'];global_w=np.array(tuning.get('selected_global_weights',pol.get('global_weights',[1/3]*3)),dtype=float);sp,tasks,risks,out,u,labels,xm,bm=t.load();src=json.loads(b.SOURCE.read_text());by=defaultdict(list)
 for r in src['raw_model_runs']:by[(r['task_id'],r['model'])].append(r)
 train,cal,test=sp['train'],sp['validation'],sp['test'];cnt={m:sum(labels[x]==m for x in train) for m in range(4)};rare=[x for x in train if cnt[labels[x]]<5];common=[x for x in train if x not in rare];folds=list(KFold(5,shuffle=True,random_state=b.SEED).split(common));oof={r:np.zeros((len(common),4)) for r in b.ROUTERS}
 for f,(ii,hh) in enumerate(folds):
  fi=[common[i] for i in ii]+rare;hi=[common[i] for i in hh];x=np.stack([xm[z] for z in fi]);y=np.array([labels[z] for z in fi]);uu=np.stack([u[z] for z in fi]);xh=np.stack([xm[z] for z in hi]);oof['knnrouter'][hh]=b.score_knn(b.train_knn(x,y,uu,b.SEED+f),xh);oof['mlprouter'][hh]=b.score_mlp(b.train_mlp(x,y,uu,b.SEED+f),xh);oof['graphrouter'][hh]=b.score_graph(t.train_graph(x,uu,cfg,cfg['seed']+f),xh)
 bc=np.stack([bm[z] for z in common]);uc=np.stack([u[z] for z in common]);meta={};truth={}
 for r in b.ROUTERS:
  sel=oof[r].argmax(1);reg=uc.max(1)-uc[np.arange(len(common)),sel];fail=np.array([out[z][m,5] for z,m in zip(common,sel)]);acc=(reg<=.03).astype(int);z=b.meta_x(bc,oof[r]);meta[r]={'accept':b.fc(z,acc),'fail':b.fc(z,fail),'regret':b.fr(z,reg)};truth[r]=(acc,fail,reg)
 xtr=np.stack([xm[z] for z in train]);ytr=np.array([labels[z] for z in train]);utr=np.stack([u[z] for z in train]);final={'knnrouter':b.train_knn(xtr,ytr,utr,b.SEED),'mlprouter':b.train_mlp(xtr,ytr,utr,b.SEED+100),'graphrouter':t.train_graph(xtr,utr,cfg,cfg['seed']+100)}
 def scores(ids):return {r:b.SCORE[r](final[r],np.stack([xm[z] for z in ids])) for r in b.ROUTERS}
 sc,st=scores(cal),scores(test)
 def mp(ids,s):
  base=np.stack([bm[z] for z in ids]);o={}
  for r in b.ROUTERS:
   z=b.meta_x(base,s[r]);o[r]={'accept':meta[r]['accept'].predict_proba(z)[:,1],'fail':meta[r]['fail'].predict_proba(z)[:,1],'regret':np.maximum(0,meta[r]['regret'].predict(z))}
  return o
 mc,mt=mp(cal,sc),mp(test,st)
 def merits(mm,i):return np.array([pol['ca']*mm[r]['accept'][i]-pol['cf']*mm[r]['fail'][i]-pol['cr']*mm[r]['regret'][i] for r in b.ROUTERS])
 def policy_scores(s,mm,i):
  base=sum(global_w[j]*b.rank(s[r][i:i+1])[0] for j,r in enumerate(b.ROUTERS))
  if not meta_enabled:return base
  merit=merits(mm,i);weight=global_w*np.exp(pol.get('eta',0.)*(merit-merit.mean()));weight/=weight.sum();return sum(weight[j]*b.rank(s[r][i:i+1])[0] for j,r in enumerate(b.ROUTERS))
 m2=np.array([policy_scores(st,mt,i).argmax() for i in range(len(test))]);M2=b.summary(test,m2,labels,out,risks)
 # Split-conformal router regret bound per risk; fallback to M2 expert when none pass.
 quant={r:{} for r in b.ROUTERS};nominal_limits={'low':.30,'medium':.20,'high':.10};limits=dict(nominal_limits);target_coverage={'low':.60,'medium':.60,'high':.50}
 for r in b.ROUTERS:
  chosen=sc[r].argmax(1);actual=np.array([u[z].max()-u[z][m] for z,m in zip(cal,chosen)])
  for rk in ('low','medium','high'):
   ix=np.array([i for i,z in enumerate(cal) if risks[z]==rk],dtype=int);quant[r][rk]=fq(np.maximum(0,actual[ix]-mc[r]['regret'][ix]),.95 if rk=='high' else .9)
 for rk in ('low','medium','high'):
  ix=[i for i,z in enumerate(cal) if risks[z]==rk]
  if ix:
   best_bounds=[min(mc[r]['regret'][i]+quant[r][rk] for r in b.ROUTERS) for i in ix]
   limits[rk]=max(limits[rk],float(np.quantile(best_bounds,target_coverage[rk],method='higher')))
 safeR=[];m3=[]
 for i,z in enumerate(test):
  safe=[r for r in b.ROUTERS if mt[r]['regret'][i]+quant[r][risks[z]]<=limits[risks[z]]];safeR.append(safe);eligible=safe or [b.ROUTERS[int(np.argmax(merits(mt,i)))]];r=max(eligible,key=lambda x:merits(mt,i)[b.ROUTERS.index(x)]);m3.append(int(st[r][i].argmax()))
 m3=np.array(m3);M3=b.summary(test,m3,labels,out,risks)
 # Query-conditional model predictors trained on train, residual bounds calibrated on calibration.
 cols={'quality':0,'failure':5,'cost':1,'latency':2};pred={};quantM={};pred_cal={};xcal=np.stack([xm[z] for z in cal]);xt=np.stack([xm[z] for z in test])
 crossfolds=list(KFold(5,shuffle=True,random_state=b.SEED+701).split(train));shrink_tau=20
 for m in range(4):
  pred[m]={};pred_cal[m]={};quantM[m]={}
  for name,col in cols.items():
   y=np.array([out[z][m,col] for z in train]);log=name in {'cost','latency'};yt=np.log1p(y) if log else y;oofp=np.zeros(len(train))
   for ii,hh in crossfolds:oofp[hh]=b.fr(xtr[ii],yt[ii]).predict(xtr[hh])
   if log:oofp=np.expm1(oofp)
   model=b.fr(xtr,yt);pc=model.predict(xcal);pc=np.expm1(pc) if log else pc;pt=model.predict(xt);pt=np.expm1(pt) if log else pt;pred[m][name]=pt;pred_cal[m][name]=pc;quantM[m][name]={}
   train_actual=np.array([out[z][m,col] for z in train]);train_resid=(oofp-train_actual) if name=='quality' else (train_actual-oofp);cal_actual=np.array([out[z][m,col] for z in cal]);cal_resid=(pc-cal_actual) if name=='quality' else (cal_actual-pc);all_resid=np.maximum(0,np.r_[train_resid,cal_resid]);qglobal=fq(all_resid,.95 if name in {'quality','failure'} else .9)
   for rk in ('low','medium','high'):
    vals=np.r_[np.maximum(0,train_resid[[risks[z]==rk for z in train]]),np.maximum(0,cal_resid[[risks[z]==rk for z in cal]])];qgroup=fq(vals,.95 if rk=='high' else .9);n=len(vals);quantM[m][name][rk]=qglobal if n<8 else float((n*qgroup+shrink_tau*qglobal)/(n+shrink_tau))
 base_thresholds={'low':(.58,.35),'medium':(.58,.35),'high':(.68,.22)};safety_slack={}
 for rk in ('low','medium','high'):
  violations=[]
  for i,z in enumerate(cal):
   if risks[z]!=rk:continue
   qmin,fmax=base_thresholds[rk];per_model=[]
   for m in range(4):
    qlcb=pred_cal[m]['quality'][i]-quantM[m]['quality'][rk];fucb=pred_cal[m]['failure'][i]+quantM[m]['failure'][rk]
    per_model.append(max(0.,qmin-qlcb,fucb-fmax))
   violations.append(min(per_model))
  safety_slack[rk]=float(np.quantile(violations,target_coverage[rk],method='higher')) if violations else 0.
 m2c=np.array([policy_scores(sc,mc,i).argmax() for i in range(len(cal))]);m3c=[]
 for i,z in enumerate(cal):
  safe=[r for r in b.ROUTERS if mc[r]['regret'][i]+quant[r][risks[z]]<=limits[risks[z]]];eligible=safe or [b.ROUTERS[int(np.argmax(merits(mc,i)))]];rr=max(eligible,key=lambda x:merits(mc,i)[b.ROUTERS.index(x)]);m3c.append(int(sc[rr][i].argmax()))
 m3c=np.array(m3c);c2_pre=b.summary(cal,m2c,labels,out,risks);c3_pre=b.summary(cal,m3c,labels,out,risks);m3_gate=bool(c3_pre['utility']>=c2_pre['utility'] and c3_pre['failure_rate']<=c2_pre['failure_rate'] and (c2_pre['high_risk_failure_rate'] is None or c3_pre['high_risk_failure_rate']<=c2_pre['high_risk_failure_rate']))
 if not m3_gate:m3c=m2c.copy();m3=m2.copy();M3=b.summary(test,m3,labels,out,risks)
 m4c=[]
 for i,z in enumerate(cal):
  rk=risks[z];safe=[];est=[];qmin,fmax=base_thresholds[rk];slack=safety_slack[rk]
  for mm in range(4):
   e={'quality_lcb':max(0,float(pred_cal[mm]['quality'][i]-quantM[mm]['quality'][rk])),'failure_ucb':max(0,float(pred_cal[mm]['failure'][i]+quantM[mm]['failure'][rk])),'cost_ucb':max(0,float(pred_cal[mm]['cost'][i]+quantM[mm]['cost'][rk])),'latency_ucb':max(0,float(pred_cal[mm]['latency'][i]+quantM[mm]['latency'][rk]))};est.append(e)
   if e['quality_lcb']>=qmin-slack and e['failure_ucb']<=fmax+slack:safe.append(mm)
  base=int(m3c[i]);cand=safe or [base]
  def ru(mm):
   e=est[mm];return .45*e['quality_lcb']+.2*(1-min(e['cost_ucb']/.02,1))+.15*(1-min(e['latency_ucb']/10000,1))+.2*(1-min(e['failure_ucb'],1))
  best=max(cand,key=lambda mm:(ru(mm),float(policy_scores(sc,mc,i)[mm])));m4c.append(best if base not in safe or ru(best)>ru(base)+.005 else base)
 c3=b.summary(cal,m3c,labels,out,risks);c4=b.summary(cal,np.array(m4c),labels,out,risks);m4_gate=bool(c4['utility']>=c3['utility'] and c4['failure_rate']<=c3['failure_rate'] and (c3['high_risk_failure_rate'] is None or c4['high_risk_failure_rate']<=c3['high_risk_failure_rate']))
 m4=[];safeM=[]
 for i,z in enumerate(test):
  rk=risks[z];safe=[];est=[]
  for m in range(4):
   e={};
   for name in cols:e[name+'_lcb']=max(0,float(pred[m][name][i]-quantM[m][name][rk]));e[name+'_ucb']=max(0,float(pred[m][name][i]+quantM[m][name][rk]))
   est.append(e);qmin,fmax=base_thresholds[rk];slack=safety_slack[rk]
   if e['quality_lcb']>=qmin-slack and e['failure_ucb']<=fmax+slack:safe.append(m)
  safeM.append(safe);base=int(m3[i]);cand=safe or [base]
  def robust_utility(m):
   e=est[m];return .45*e['quality_lcb']+.2*(1-min(e['cost_ucb']/.02,1))+.15*(1-min(e['latency_ucb']/10000,1))+.2*(1-min(e['failure_ucb'],1))
  best=max(cand,key=lambda m:(robust_utility(m),float(policy_scores(st,mt,i)[m])))
  m4.append(best if base not in safe or robust_utility(best)>robust_utility(base)+.005 else base)
 m4=np.array(m4) if m4_gate else m3.copy();M4=b.summary(test,m4,labels,out,risks)
 def ofail(z,m):
  vals=[objective_score(tasks[z],str(x.get('response') or '')) for x in by[(z,b.MODELS[m])]];vals=[x for x in vals if x is not None];return 1-np.mean(vals) if vals else 1.
 global_stats={m:{'failure':float(np.mean([ofail(z,m) for z in cal])),'utility':float(np.mean([out[z][m,4] for z in cal]))} for m in range(4)};global_anchor=min(range(4),key=lambda m:(global_stats[m]['failure'],-global_stats[m]['utility'],m));groups={}
 for z in cal:
  key=(risks[z],tasks[z].get('task_type'));groups.setdefault(key,[]).append(z)
 anchor_map={};anchor_stats={};anchor_policy=os.getenv('FINROME_M5_ANCHOR_POLICY','sparse_v2');anchor_min_group=1 if anchor_policy=='legacy_v1' else 12;anchor_tau=0 if anchor_policy=='legacy_v1' else 20;anchor_min_risk_gain=0. if anchor_policy=='legacy_v1' else .05
 for key,ids in groups.items():
  if len(ids)<anchor_min_group:continue
  raw={m:{'failure':float(np.mean([ofail(z,m) for z in ids])),'utility':float(np.mean([out[z][m,4] for z in ids]))} for m in range(4)};w=1. if anchor_tau==0 else len(ids)/(len(ids)+anchor_tau);stats={m:{k:w*raw[m][k]+(1-w)*global_stats[m][k] for k in ('failure','utility')} for m in range(4)};anchor_stats[str(key)]=stats;anchor_map[key]=min(range(4),key=lambda m:(stats[m]['failure'],-stats[m]['utility'],m))
 anchor_budgets={'high':.02,'other':.04} if anchor_policy=='legacy_v1' else {'high':.015,'other':.03};m5=[];esc=[];manual=[];trace=[]
 for z,m in zip(test,m4):
  key=(risks[z],tasks[z].get('task_type'));stats=anchor_stats.get(str(key),global_stats);anchor=anchor_map.get(key,global_anchor);response=str(by[(z,b.MODELS[int(m)])][0].get('response') or '');obj=objective_score(tasks[z],response);rule=bool(response.strip()) and (bool(re.search(r'最终答案|final answer|答案|结论',response,re.I)) or tasks[z].get('task_type') not in {'financial_numerical_reasoning','financial_table_text_reasoning'});passed=rule and obj is not None and obj>=(.999 if risks[z]=='high' else .8);risk_gain=stats[int(m)]['failure']-stats[anchor]['failure'];utility_loss=stats[int(m)]['utility']-stats[anchor]['utility'];budget=anchor_budgets['high' if risks[z]=='high' else 'other'];up=not passed and int(m)!=anchor and risk_gain>anchor_min_risk_gain and utility_loss<=budget;fm=anchor if up else int(m);obj2=objective_score(tasks[z],str(by[(z,b.MODELS[fm])][0].get('response') or ''));review=obj2 is None or obj2<(.999 if risks[z]=='high' else .8);m5.append(fm);esc.append(up);manual.append(review);trace.append({'task_id':z,'initial':b.MODELS[int(m)],'rule_pass':rule,'objective':obj,'escalated':up,'anchor':'conditional','risk_gain':risk_gain,'utility_loss':utility_loss,'utility_budget':budget,'final':b.MODELS[fm],'second_objective':obj2,'manual_review':review})
 M5=b.summary(test,np.array(m5),labels,out,risks);M5['escalation_rate']=float(np.mean(esc));M5['manual_review_rate']=float(np.mean(manual));report={'report_type':'finrome_M3_M5_after_oof_gate','frozen_graph':cfg,'frozen_meta':pol,'M2_gate_source':str((t.OUT/'report.json').relative_to(b.ROOT)),'M2_meta_enabled':meta_enabled,'M2':M2,'M3':M3,'M4':M4,'M5':M5,'M3_calibration_gate':{'passed':m3_gate,'M2':{k:v for k,v in c2_pre.items() if k!='rows'},'candidate_M3':{k:v for k,v in c3_pre.items() if k!='rows'}},'router_conformal':{'quantiles':quant,'nominal_limits':nominal_limits,'calibrated_limits':limits,'target_coverage':target_coverage,'coverage':float(np.mean([bool(x) for x in safeR])),'mean_safe_count':float(np.mean([len(x) for x in safeR]))},'M4_calibration_gate':{'passed':m4_gate,'M3':{k:v for k,v in c3.items() if k!='rows'},'candidate_M4':{k:v for k,v in c4.items() if k!='rows'}},'conditional_model_safety':{'targets':['Q(x,m)','P_fail(x,m)','C(x,m)','L(x,m)'],'one_sided_bounds':True,'cross_conformal_folds':5,'hierarchical_shrink_tau':shrink_tau,'sparse_group_fallback_n':8,'base_thresholds':base_thresholds,'calibrated_slack':safety_slack,'target_coverage':target_coverage,'safe_coverage':float(np.mean([bool(x) for x in safeM])),'quantiles':quantM},'trusted_anchor':'conditional','anchor_policy':anchor_policy,'conditional_anchor_map':{str(k):b.MODELS[v] for k,v in anchor_map.items()},'anchor_utility_budgets':anchor_budgets,'anchor_min_group':anchor_min_group,'anchor_shrink_tau':anchor_tau,'minimum_predicted_risk_gain':anchor_min_risk_gain,'verifier_trace':trace,'limitations':['20 calibration tasks are exploratory; no formal conditional coverage claim.','Verifier uses real deterministic objective scoring on frozen responses; no new generation because endpoints/credentials are unavailable.']};(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(OUT/'verifier_trace.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in trace));(OUT/'report.md').write_text('\n'.join(['# Fin-RoME M3–M5',f"- M2 utility={M2['utility']:.6f}, failure={M2['failure_rate']:.2%}, regret={M2['mean_regret']:.6f}",f"- M3 utility={M3['utility']:.6f}, failure={M3['failure_rate']:.2%}, regret={M3['mean_regret']:.6f}",f"- M4 utility={M4['utility']:.6f}, failure={M4['failure_rate']:.2%}, regret={M4['mean_regret']:.6f}",f"- M5 utility={M5['utility']:.6f}, failure={M5['failure_rate']:.2%}, regret={M5['mean_regret']:.6f}",f"- Trusted Anchor={b.MODELS[anchor]}; escalation={M5['escalation_rate']:.2%}; manual={M5['manual_review_rate']:.2%}"])+'\n');print(json.dumps({'out':str(OUT),'M2':{k:v for k,v in M2.items() if k!='rows'},'M3':{k:v for k,v in M3.items() if k!='rows'},'M4':{k:v for k,v in M4.items() if k!='rows'},'M5':{k:v for k,v in M5.items() if k!='rows'},'anchor':b.MODELS[anchor]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
