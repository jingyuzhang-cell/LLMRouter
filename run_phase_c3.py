#!/usr/bin/env python3
"""Phase C3: nested-OOF noise-aware semantic advantage routing."""
import hashlib,json,math,re,sys
from collections import Counter,defaultdict
from itertools import combinations
from pathlib import Path
import numpy as np
import torch
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from transformers import AutoModel,AutoTokenizer

ROOT=Path('/root');EXP=ROOT/'target_support_expansion_v1';OUT=ROOT/'phase_c3';PROTOCOL=OUT/'C3_PROTOCOL.json';SCHEMA=OUT/'C3_FEATURE_SCHEMA.json';SEED=20260827
ENCODER=ROOT/'autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/pretrained/e5-small-v2';MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash');PAIRS=tuple(combinations(MODELS,2))
source=(ROOT/'run_phase_c1_structural_interaction.py').read_text().split("protocol=json.loads(PROTOCOL.read_text())",1)[0];ns={'__name__':'c1_features'};exec(compile(source,'c1_features','exec'),ns);structural=ns['structural_features'];bt_choices=ns['bt_choices']
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
tasks={x['id']:x for x in read(EXP/'combined_509_tasks_frozen.jsonl')};outcomes={(x['task_id'],x['model']):x for x in read(EXP/'combined_509_task_model_matrix_frozen.jsonl')}
old=json.loads((ROOT/'target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json').read_text());new=json.loads((EXP/'EXPANSION_DEV_VALIDATION_SPLIT.json').read_text());ids=sorted(set(old['train_task_ids']+old['validation_task_ids']+new['train_task_ids']));excluded=set(new['validation_task_ids']);assert len(ids)==419 and not set(ids)&excluded
repeat_rows=read(ROOT/'five_model_routability_audit/five_model_training_repeats_frozen.jsonl')+read(EXP/'expanded_five_model_repeats_frozen.jsonl');repeat_lookup=defaultdict(list)
def utility(r):return .45*r['quality']+.20*(1-min(float(r.get('cost_usd') or 0)/.02,1))+.15*(1-min(float(r.get('latency_ms') or 0)/10000,1))+.20*float(r.get('reliability',1))
for r in repeat_rows:
 if r['task_id'] in ids:repeat_lookup[(r['task_id'],r['model'])].append(utility(r))
assert all(len(repeat_lookup[(t,m)])==3 for t in ids for m in MODELS)
def manual(t):
 q=str(t.get('question') or '');c=str(t.get('context') or '');table=t.get('table') or [];e=t.get('evidence') or [];text=' '.join((q,c)).lower();cells=[str(v) for row in table if isinstance(row,list) for v in row];numcells=sum(bool(re.search(r'[-+]?[$£€]?\(?\d[\d,.]*%?\)?',v)) for v in cells);ops=sum(text.count(x) for x in ('difference','increase','decrease','ratio','percent','average','total','change','sum','minus','divided'))+len(re.findall(r'[+\-*/]',q));depth=min(5,ops+int(' and ' in q.lower()));cross=int(any(x in text for x in ('respectively','between','compare','from ',' to ','cross-row')));mix=int(bool(table) and bool(c));multi=int(any(x in q.lower() for x in ('which','what are','list','both','分别','哪些')));gold=str(t.get('gold_answer') or '');atype_num=int(bool(re.fullmatch(r'\s*[-+]?[$£€]?\(?[\d,.]+\)?\s*',gold)));atype_pct=int('%' in gold);atype_span=int(not atype_num and not atype_pct);reg=sum(text.count(x) for x in ('section','article','rule','regulation','clause','paragraph'));neg=sum(text.count(x) for x in ('except','unless','notwithstanding','however','but','not ','no ','without'));xref=len(re.findall(r'\b(?:section|article|rule|paragraph|part)\s*[\d.()]+',text));modal=sum(text.count(x) for x in ('must','shall','may','should','required','prohibited'));amb=sum(text.count(x) for x in ('may','could','generally','reasonable','appropriate','material'));evtxt=[json.dumps(x,sort_keys=True) for x in e];redund=1-len(set(evtxt))/max(1,len(evtxt));longdep=len(c)/max(1,len(e));words=re.findall(r'\b\w+\b',q+' '+c);lex=len(set(w.lower() for w in words))/max(1,len(words));ratio=len(q.split())/max(1,len(c.split()))
 return np.asarray([numcells,numcells/max(1,len(cells)),ops,depth,cross,mix,multi,atype_num,atype_pct,atype_span,reg,neg,xref,modal,amb,redund,longdep,lex,ratio],float)
def embed_text(t):
 table=' | '.join(' ; '.join(map(str,row)) for row in (t.get('table') or []) if isinstance(row,list));return 'query: '+str(t.get('question') or '')+' [SEP] '+str(t.get('context') or '')+' [SEP] '+table
cache=OUT/'C3_FROZEN_E5_EMBEDDINGS.npz'
if cache.exists():emb=np.load(cache)['embeddings']
else:
 tok=AutoTokenizer.from_pretrained(str(ENCODER),local_files_only=True);model=AutoModel.from_pretrained(str(ENCODER),local_files_only=True).eval();device='cuda' if torch.cuda.is_available() else 'cpu';model.to(device);all_emb=[]
 texts=[embed_text(tasks[t]) for t in ids]
 with torch.no_grad():
  for start in range(0,len(texts),24):
   batch=tok(texts[start:start+24],padding=True,truncation=True,max_length=512,return_tensors='pt');batch={k:v.to(device) for k,v in batch.items()};h=model(**batch).last_hidden_state;mask=batch['attention_mask'].unsqueeze(-1);v=(h*mask).sum(1)/mask.sum(1).clamp(min=1);v=torch.nn.functional.normalize(v,p=2,dim=1);all_emb.append(v.cpu().numpy())
 emb=np.vstack(all_emb);np.savez_compressed(cache,task_ids=np.asarray(ids),embeddings=emb)
assert emb.shape==(419,384)
base=np.vstack([np.r_[structural(tasks[t]),manual(tasks[t])] for t in ids]);idpos={t:i for i,t in enumerate(ids)};modelpos={m:i for i,m in enumerate(MODELS)}
def design(z,models):
 n=len(models);one=np.zeros((n,len(MODELS)));one[np.arange(n),[modelpos[m] for m in models]]=1;blocks=[z,one]
 for mi in range(len(MODELS)):blocks.append(z*(one[:,mi:mi+1]))
 return np.hstack(blocks)
def train_predict(train_idx,predict_idx,baseline,weighted):
 pca=PCA(n_components=32,random_state=SEED).fit(emb[train_idx]);ztr=np.hstack([base[train_idx],pca.transform(emb[train_idx])]);zpr=np.hstack([base[predict_idx],pca.transform(emb[predict_idx])]);x=[];y=[];w=[];mods=[]
 for local,i in enumerate(train_idx):
  t=ids[i]
  for m in MODELS:
   if m==baseline:continue
   adv=outcomes[(t,m)]['utility']-outcomes[(t,baseline)]['utility'];var=np.var(repeat_lookup[(t,m)],ddof=1)+np.var(repeat_lookup[(t,baseline)],ddof=1);snr=abs(adv)/math.sqrt(var+1e-6);x.append(ztr[local]);mods.append(m);y.append(adv);w.append(float(np.clip(snr,.25,4)))
 X=design(np.asarray(x),mods);pipe=make_pipeline(StandardScaler(),Ridge(alpha=10.0));pipe.fit(X,np.asarray(y),ridge__sample_weight=np.asarray(w) if weighted else None)
 predictions={m:pipe.predict(design(zpr,[m]*len(predict_idx))) for m in MODELS if m!=baseline};return predictions
def nested_advantage(weighted):
 outer=KFold(5,shuffle=True,random_state=SEED);pred_mean={};pred_std={};baselines={}
 for fold,(tr,va) in enumerate(outer.split(ids)):
  means={m:float(np.mean([outcomes[(ids[i],m)]['utility'] for i in tr])) for m in MODELS};baseline=max(means,key=means.get);inner=KFold(5,shuffle=True,random_state=SEED+100+fold);ensemble={m:[] for m in MODELS if m!=baseline}
  for itr,_ in inner.split(tr):
   inner_train=tr[itr];p=train_predict(inner_train,va,baseline,weighted)
   for m,v in p.items():ensemble[m].append(v)
  for local,i in enumerate(va):
   t=ids[i];baselines[t]=baseline;pred_mean[t]={m:float(np.mean(v,axis=0)[local]) for m,v in ensemble.items()};pred_std[t]={m:float(np.std(v,axis=0,ddof=1)[local]) for m,v in ensemble.items()}
 return baselines,pred_mean,pred_std
def choices_from(baselines,means,stds,selective):
 out={}
 for t in ids:
  b=baselines[t];score={m:(means[t][m]-1.645*stds[t][m] if selective else means[t][m]) for m in means[t]};m=max(score,key=score.get);out[t]=m if score[m]>0 else b
 return out
def pairwise_oof():
 outer=KFold(5,shuffle=True,random_state=SEED);pred={p:np.zeros(len(ids)) for p in PAIRS};baselines={}
 X=base
 for tr,va in outer.split(ids):
  means={m:float(np.mean([outcomes[(ids[i],m)]['utility'] for i in tr])) for m in MODELS};b=max(means,key=means.get)
  for i in va:baselines[ids[i]]=b
  for p in PAIRS:
   raw=np.asarray([outcomes[(t,p[0])]['utility']-outcomes[(t,p[1])]['utility'] for t in ids]);keep=np.asarray([i for i in tr if abs(raw[i])>=.01]);prior=float(raw[tr].mean());pipe=make_pipeline(StandardScaler(),Ridge(alpha=10.0)).fit(X[keep],raw[keep]-prior);pred[p][va]=pipe.predict(X[va])
 choices,_=bt_choices(ids,pred);return baselines,choices
def metrics(choices,baselines):
 sel=np.asarray([outcomes[(t,choices[t])]['utility'] for t in ids]);bl=np.asarray([outcomes[(t,baselines[t])]['utility'] for t in ids]);oracle=np.asarray([max(outcomes[(t,m)]['utility'] for m in MODELS) for t in ids]);delta=sel-bl;den=oracle.mean()-bl.mean();rng=np.random.default_rng(SEED);ix=rng.integers(0,len(ids),size=(10000,len(ids)));boot=delta[ix].mean(1);rec=(sel.mean()-bl.mean())/den;oracle_m=[max(MODELS,key=lambda m:outcomes[(t,m)]['utility']) for t in ids];high=[i for i,t in enumerate(ids) if tasks[t]['risk_level']=='high']
 return {'oof_utility':float(sel.mean()),'best_single_utility':float(bl.mean()),'oracle_utility':float(oracle.mean()),'gap_recovery':float(rec),'delta_utility':float(delta.mean()),'delta_utility_bootstrap_ci95':[float(np.quantile(boot,.025)),float(np.quantile(boot,.975))],'bootstrap_probability_delta_positive':float(np.mean(boot>0)),'failure_rate':float(np.mean([outcomes[(t,choices[t])]['failure'] for t in ids])),'best_single_failure_rate':float(np.mean([outcomes[(t,baselines[t])]['failure'] for t in ids])),'high_risk_failure_rate':float(np.mean([outcomes[(ids[i],choices[ids[i]])]['failure'] for i in high])),'best_single_high_risk_failure_rate':float(np.mean([outcomes[(ids[i],baselines[ids[i]])]['failure'] for i in high])),'oracle_match':float(np.mean([choices[t]==oracle_m[i] for i,t in enumerate(ids)])),'selection_counts':dict(Counter(choices.values()))}
def switch_audit(choices,baselines):
 switched=[t for t in ids if choices[t]!=baselines[t]];gains=np.asarray([outcomes[(t,choices[t])]['utility']-outcomes[(t,baselines[t])]['utility'] for t in switched]);benef=gains[gains>0];harm=gains[gains<0];miss=sum(choices[t]==baselines[t] and max(outcomes[(t,m)]['utility'] for m in MODELS)>outcomes[(t,baselines[t])]['utility'] for t in ids)
 return {'switch_count':len(switched),'beneficial_switch_count':int((gains>0).sum()),'harmful_switch_count':int((gains<0).sum()),'neutral_switch_count':int((gains==0).sum()),'missed_opportunity_count':int(miss),'beneficial_mean_gain':float(benef.mean()) if len(benef) else None,'harmful_mean_loss':float(harm.mean()) if len(harm) else None,'net_switch_utility_sum':float(gains.sum()),'net_switch_utility_per_task':float(gains.sum()/len(ids))}
pair_base,pair_choices=pairwise_oof();un_base,un_mean,un_std=nested_advantage(False);wt_base,wt_mean,wt_std=nested_advantage(True);adv_choices=choices_from(un_base,un_mean,un_std,False);noise_choices=choices_from(wt_base,wt_mean,wt_std,False);select_choices=choices_from(wt_base,wt_mean,wt_std,True);best_choices=dict(un_base);oracle_choices={t:max(MODELS,key=lambda m:outcomes[(t,m)]['utility']) for t in ids}
methods={'best_single':metrics(best_choices,un_base),'global_pairwise_c2':metrics(pair_choices,pair_base),'advantage_ridge':metrics(adv_choices,un_base),'noise_aware_advantage':metrics(noise_choices,wt_base),'selective_advantage':metrics(select_choices,wt_base),'oracle':metrics(oracle_choices,un_base)}
audits={name:switch_audit(ch,base) for name,ch,base in [('global_pairwise_c2',pair_choices,pair_base),('advantage_ridge',adv_choices,un_base),('noise_aware_advantage',noise_choices,wt_base),('selective_advantage',select_choices,wt_base)]};s=methods['selective_advantage'];gate={'oof_gap_recovery_above_0':s['gap_recovery']>0,'bootstrap_probability_ge_0.90':s['bootstrap_probability_delta_positive']>=.90,'failure_within_best_plus_0.02':s['failure_rate']<=s['best_single_failure_rate']+.02};status='C3_DEVELOPMENT_PASS' if all(gate.values()) else 'C3_DEVELOPMENT_FAIL'
integrity={'tasks':len(ids),'excluded_diagnostic_overlap':len(set(ids)&excluded),'repeat_keys_complete':True,'raw_embedding_shape':list(emb.shape),'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),'feature_schema_sha256':hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),'external_api_calls':0,'v2_used':False}
report={'status':status,'integrity':integrity,'methods':methods,'development_gate':{**gate,'pass':all(gate.values())}};(OUT/'C3_OOF_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');(OUT/'C3_SWITCH_ERROR_AUDIT.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2)+'\n')
md=f'''# Phase C3 Development Report\n\nStatus: **{status}**\n\nThe 90-task C2 diagnostic set was excluded. Nested OOF used 419 development tasks, with no external API calls.\n\n| Method | Utility | Gap recovery | P(ΔU>0) | Failure | High-risk failure |\n|---|---:|---:|---:|---:|---:|\n'''+''.join(f"| {k} | {v['oof_utility']:.6f} | {v['gap_recovery']:.2%} | {v['bootstrap_probability_delta_positive']:.2%} | {v['failure_rate']:.2%} | {v['high_risk_failure_rate']:.2%} |\n" for k,v in methods.items())+f"\nDevelopment gate: {json.dumps(gate)}\n";(OUT/'PHASE_C3_DEVELOPMENT_REPORT.md').write_text(md);print(json.dumps(report,ensure_ascii=False,indent=2))
