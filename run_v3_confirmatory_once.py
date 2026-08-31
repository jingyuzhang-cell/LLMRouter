#!/usr/bin/env python3
"""One-shot evaluation of the frozen C3 selective advantage router on v3."""
import contextlib,hashlib,importlib.util,io,json,math
from collections import Counter
from pathlib import Path
import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from transformers import AutoModel,AutoTokenizer
ROOT=Path('/root');V3=ROOT/'v3_confirmatory';SEED=20260827;MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash');ENC=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/pretrained/e5-small-v2'
spec=importlib.util.spec_from_file_location('c3frozen',ROOT/'run_phase_c3.py');c3=importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):spec.loader.exec_module(c3)
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
tasks=read(V3/'V3_CONFIRMATORY_TASKS.jsonl');tids=sorted(x['id'] for x in tasks);task={x['id']:x for x in tasks};matrix=read(V3/'V3_TASK_MODEL_MATRIX_FROZEN.jsonl');out={(x['task_id'],x['model']):x for x in matrix};assert len(matrix)==600
means={m:float(np.mean([c3.outcomes[(t,m)]['utility'] for t in c3.ids])) for m in MODELS};baseline=max(means,key=means.get);assert baseline=='qwen-plus'
def encode(texts):
 tok=AutoTokenizer.from_pretrained(str(ENC),local_files_only=True);model=AutoModel.from_pretrained(str(ENC),local_files_only=True).eval();device='cuda' if torch.cuda.is_available() else 'cpu';model.to(device);arr=[]
 with torch.no_grad():
  for s in range(0,len(texts),24):
   b=tok(texts[s:s+24],padding=True,truncation=True,max_length=512,return_tensors='pt');b={k:v.to(device) for k,v in b.items()};h=model(**b).last_hidden_state;mask=b['attention_mask'].unsqueeze(-1);v=(h*mask).sum(1)/mask.sum(1).clamp(min=1);arr.append(torch.nn.functional.normalize(v,p=2,dim=1).cpu().numpy())
 return np.vstack(arr)
emb_v3=encode([c3.embed_text(task[t]) for t in tids]);base_v3=np.vstack([np.r_[c3.structural(task[t]),c3.manual(task[t])] for t in tids]);ensemble={m:[] for m in MODELS if m!=baseline};folds=KFold(5,shuffle=True,random_state=SEED+999)
for tr,_ in folds.split(c3.ids):
 pca=PCA(n_components=32,random_state=SEED).fit(c3.emb[tr]);ztr=np.hstack([c3.base[tr],pca.transform(c3.emb[tr])]);zv=np.hstack([base_v3,pca.transform(emb_v3)]);xs=[];ys=[];ws=[];mods=[]
 for local,i in enumerate(tr):
  tid=c3.ids[i]
  for m in MODELS:
   if m==baseline:continue
   adv=c3.outcomes[(tid,m)]['utility']-c3.outcomes[(tid,baseline)]['utility'];var=np.var(c3.repeat_lookup[(tid,m)],ddof=1)+np.var(c3.repeat_lookup[(tid,baseline)],ddof=1);snr=abs(adv)/math.sqrt(var+1e-6);xs.append(ztr[local]);ys.append(adv);ws.append(float(np.clip(snr,.25,4)));mods.append(m)
 pipe=make_pipeline(StandardScaler(),Ridge(alpha=10.0));pipe.fit(c3.design(np.asarray(xs),mods),np.asarray(ys),ridge__sample_weight=np.asarray(ws))
 for m in ensemble:ensemble[m].append(pipe.predict(c3.design(zv,[m]*len(tids))))
pred_mean={t:{} for t in tids};pred_std={t:{} for t in tids};choices={};decision_rows=[]
for i,t in enumerate(tids):
 for m,v in ensemble.items():pred_mean[t][m]=float(np.mean(v,axis=0)[i]);pred_std[t][m]=float(np.std(v,axis=0,ddof=1)[i])
 lcb={m:pred_mean[t][m]-1.645*pred_std[t][m] for m in ensemble};candidate=max(lcb,key=lcb.get);choices[t]=candidate if lcb[candidate]>0 else baseline;decision_rows.append({'task_id':t,'baseline_model':baseline,'predicted_advantage':pred_mean[t],'prediction_std':pred_std[t],'lcb90':lcb,'selected_model':choices[t]})
dp=V3/'V3_FROZEN_C3_DECISIONS.jsonl';dp.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in decision_rows))
sel=np.asarray([out[(t,choices[t])]['utility'] for t in tids]);best=np.asarray([out[(t,baseline)]['utility'] for t in tids]);oracle=np.asarray([max(out[(t,m)]['utility'] for m in MODELS) for t in tids]);delta=sel-best;gap=float(oracle.mean()-best.mean());rng=np.random.default_rng(SEED);ix=rng.integers(0,len(tids),size=(10000,len(tids)));boot=delta[ix].mean(1);high=[t for t in tids if task[t]['risk_level']=='high'];switch=[t for t in tids if choices[t]!=baseline];gains=np.asarray([out[(t,choices[t])]['utility']-out[(t,baseline)]['utility'] for t in switch]);oracle_models={t:max(MODELS,key=lambda m:out[(t,m)]['utility']) for t in tids}
def avg(field,chosen):return float(np.mean([out[(t,chosen(t))][field] for t in tids]))
metrics={'router_utility':float(sel.mean()),'best_single_utility':float(best.mean()),'oracle_utility':float(oracle.mean()),'oracle_gap':gap,'gap_recovery':float(delta.mean()/gap) if gap>0 else None,'delta_utility':float(delta.mean()),'delta_utility_ci95':[float(np.quantile(boot,.025)),float(np.quantile(boot,.975))],'bootstrap_probability_router_above_best':float(np.mean(boot>0)),'router_quality':avg('quality',lambda t:choices[t]),'best_single_quality':avg('quality',lambda t:baseline),'router_cost_usd':avg('cost_usd',lambda t:choices[t]),'best_single_cost_usd':avg('cost_usd',lambda t:baseline),'router_latency_ms':avg('latency_ms',lambda t:choices[t]),'best_single_latency_ms':avg('latency_ms',lambda t:baseline),'router_failure':float(np.mean([out[(t,choices[t])]['failure'] for t in tids])),'best_single_failure':float(np.mean([out[(t,baseline)]['failure'] for t in tids])),'router_high_risk_failure':float(np.mean([out[(t,choices[t])]['failure'] for t in high])),'best_single_high_risk_failure':float(np.mean([out[(t,baseline)]['failure'] for t in high])),'oracle_match':float(np.mean([choices[t]==oracle_models[t] for t in tids])),'selection_counts':dict(Counter(choices.values())),'switch_count':len(switch),'beneficial_switch_count':int((gains>0).sum()),'harmful_switch_count':int((gains<0).sum()),'beneficial_mean_gain':float(gains[gains>0].mean()) if np.any(gains>0) else None,'harmful_mean_loss':float(gains[gains<0].mean()) if np.any(gains<0) else None,'net_switch_utility':float(gains.sum())}
gates={'gap_recovery_ge_0.20':metrics['gap_recovery']>=.20,'bootstrap_probability_ge_0.95':metrics['bootstrap_probability_router_above_best']>=.95,'failure_router_le_best':metrics['router_failure']<=metrics['best_single_failure'],'high_risk_failure_router_le_best':metrics['router_high_risk_failure']<=metrics['best_single_high_risk_failure']}
conditional={}
for name,group in [('TAT-medium',[t for t in tids if task[t]['dataset']=='TAT-QA' and task[t]['risk_level']=='medium']),('TAT-low',[t for t in tids if task[t]['dataset']=='TAT-QA' and task[t]['risk_level']=='low']),('Obli-high',high)]:
 s=np.mean([out[(t,choices[t])]['utility'] for t in group]);b=np.mean([out[(t,baseline)]['utility'] for t in group]);o=np.mean([max(out[(t,m)]['utility'] for m in MODELS) for t in group]);conditional[name]={'n':len(group),'router_utility':float(s),'best_single_utility':float(b),'oracle_utility':float(o),'gap_recovery':float((s-b)/(o-b)) if o>b else None,'router_failure':float(np.mean([out[(t,choices[t])]['failure'] for t in group])),'best_single_failure':float(np.mean([out[(t,baseline)]['failure'] for t in group]))}
report={'status':'V3_CONFIRMATORY_PASS' if all(gates.values()) else 'V3_CONFIRMATORY_FAIL','protocol_sha256':hashlib.sha256((V3/'V3_CONFIRMATORY_PROTOCOL.json').read_bytes()).hexdigest(),'matrix_sha256':hashlib.sha256((V3/'V3_TASK_MODEL_MATRIX_FROZEN.jsonl').read_bytes()).hexdigest(),'decisions_sha256':hashlib.sha256(dp.read_bytes()).hexdigest(),'training_tasks':419,'v3_tasks':120,'training_baseline_model':baseline,'method':'frozen C3 noise-aware selective advantage, 90% LCB','metrics':metrics,'conditional':conditional,'gates':{**gates,'pass':all(gates.values())},'frar_run':False,'method_or_threshold_changed_after_v3':False};(V3/'V3_CONFIRMATORY_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
