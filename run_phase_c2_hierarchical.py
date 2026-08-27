#!/usr/bin/env python3
"""Run frozen C2 global-vs-hierarchical tie-aware compatibility audit."""
import hashlib, json
from collections import Counter
from itertools import combinations
from pathlib import Path
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path('/root'); EXP=ROOT/'target_support_expansion_v1'; OUT=ROOT/'phase_c2'; PROTOCOL=OUT/'C2_PROTOCOL.json'; SEED=20260827
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash'); PAIRS=tuple(combinations(MODELS,2)); FAMILIES=('TAT-QA:low','TAT-QA:medium','ObliQA:high'); TIE=.01
source=(ROOT/'run_phase_c1_structural_interaction.py').read_text().split("protocol=json.loads(PROTOCOL.read_text())",1)[0]; ns={'__name__':'frozen_c1_functions'}; exec(compile(source,'frozen_c1_functions','exec'),ns)
features=ns['structural_features']; bt_choices=ns['bt_choices']; bootstrap=ns['bootstrap']
def read(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
tasks={x['id']:x for x in read(EXP/'combined_509_tasks_frozen.jsonl')}; outcomes={(x['task_id'],x['model']):x for x in read(EXP/'combined_509_task_model_matrix_frozen.jsonl')}
old=json.loads((ROOT/'target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json').read_text()); new=json.loads((EXP/'EXPANSION_DEV_VALIDATION_SPLIT.json').read_text()); train=sorted(set(old['train_task_ids']+old['validation_task_ids']+new['train_task_ids'])); validation=sorted(new['validation_task_ids'])
def family(t): return f"{tasks[t]['dataset']}:{tasks[t]['risk_level']}"
def xbase(ids): return np.vstack([features(tasks[t]) for t in ids])
def xhier(ids):
    base=xbase(ids); blocks=[base]
    for fam in FAMILIES: blocks.append(base*np.asarray([family(t)==fam for t in ids])[:,None])
    return np.hstack(blocks)
def targets(ids,pair,kind):
    a,b=pair; raw=np.asarray([outcomes[(t,a)]['utility']-outcomes[(t,b)]['utility'] for t in ids]); centered=np.empty(len(ids)); means={}
    if kind=='global': means['global']=float(raw.mean()); centered=raw-means['global']
    else:
        for fam in FAMILIES:
            ix=np.asarray([family(t)==fam for t in ids]); means[fam]=float(raw[ix].mean()); centered[ix]=raw[ix]-means[fam]
    return raw,centered,means
def fit_predict(train_ids,predict_ids,kind):
    xt=xbase(train_ids) if kind=='global' else xhier(train_ids); xp=xbase(predict_ids) if kind=='global' else xhier(predict_ids); pred={}; diagnostics={}
    for pair in PAIRS:
        raw,y,means=targets(train_ids,pair,kind); keep=np.abs(raw)>=TIE
        model=make_pipeline(StandardScaler(),Ridge(alpha=10.0)).fit(xt[keep],y[keep]); pred[pair]=model.predict(xp)
        diagnostics['__vs__'.join(pair)]={'train_n':int(keep.sum()),'tie_n':int((~keep).sum()),'centering_means':means,'train_centered_r2':float(model.score(xt[keep],y[keep]))}
    choices,scores=bt_choices(predict_ids,pred); return choices,scores,diagnostics
def oof(ids,kind):
    folds=KFold(5,shuffle=True,random_state=SEED); pred={p:np.zeros(len(ids)) for p in PAIRS}; sign=[]
    xb=xbase(ids) if kind=='global' else xhier(ids)
    for tr,va in folds.split(ids):
        trids=[ids[i] for i in tr]
        for pair in PAIRS:
            raw_all=np.asarray([outcomes[(t,pair[0])]['utility']-outcomes[(t,pair[1])]['utility'] for t in ids]); raw_tr,y_tr,means=targets(trids,pair,kind); keep=np.abs(raw_tr)>=TIE; model=make_pipeline(StandardScaler(),Ridge(alpha=10.0)).fit(xb[tr][keep],y_tr[keep]); p=model.predict(xb[va]); pred[pair][va]=p
            for local,i in enumerate(va):
                if abs(raw_all[i])<TIE: continue
                mean=means['global'] if kind=='global' else means[family(ids[i])]; sign.append(np.sign(mean+p[local])==np.sign(raw_all[i]))
    choices,_=bt_choices(ids,pred); return choices,float(np.mean(sign))
def evaluate(ids,choices,best):
    selected=np.asarray([outcomes[(t,choices[t])]['utility'] for t in ids]); baseline=np.asarray([outcomes[(t,best)]['utility'] for t in ids]); oracle=np.asarray([max(outcomes[(t,m)]['utility'] for m in MODELS) for t in ids]); gap=float(oracle.mean()-baseline.mean()); failures=float(np.mean([outcomes[(t,choices[t])]['failure'] for t in ids])); base_fail=float(np.mean([outcomes[(t,best)]['failure'] for t in ids])); high=[t for t in ids if tasks[t]['risk_level']=='high']
    return {'mean_utility':float(selected.mean()),'global_prior_utility':float(baseline.mean()),'oracle_utility':float(oracle.mean()),'oracle_gap':gap,'gap_recovery':float((selected.mean()-baseline.mean())/gap) if gap>0 else None,'failure_rate':failures,'global_prior_failure_rate':base_fail,'high_risk_failure_rate':float(np.mean([outcomes[(t,choices[t])]['failure'] for t in high])) if high else None,'global_prior_high_risk_failure_rate':float(np.mean([outcomes[(t,best)]['failure'] for t in high])) if high else None,'selection_counts':dict(Counter(choices.values()))}
means={m:float(np.mean([outcomes[(t,m)]['utility'] for t in train])) for m in MODELS}; best=max(means,key=means.get); prior_val={t:best for t in validation}; prior_oof={t:best for t in train}
results={'global_prior':{'oof':evaluate(train,prior_oof,best),'validation':evaluate(validation,prior_val,best)}}
for kind,name in [('global','global_tie_aware_pairwise'),('hierarchical','hierarchical_tie_aware_pairwise')]:
    oc,acc=oof(train,kind); vc,scores,diag=fit_predict(train,validation,kind); results[name]={'oof':evaluate(train,oc,best),'oof_pairwise_sign_accuracy':acc,'validation':evaluate(validation,vc,best),'fit_diagnostics':diag}; results[name]['validation']['gap_recovery_bootstrap']=bootstrap(validation,vc,outcomes,best)
hier=results['hierarchical_tie_aware_pairwise']['validation']; gates={'recovery_ge_0.20':hier['gap_recovery']>=.20,'utility_above_global_prior':hier['mean_utility']>hier['global_prior_utility'],'bootstrap_positive_probability_ge_0.95':hier['gap_recovery_bootstrap']['positive_probability']>=.95,'failure_not_above_global_prior':hier['failure_rate']<=hier['global_prior_failure_rate']}
report={'protocol':json.loads(PROTOCOL.read_text()),'integrity':{'train_tasks':len(train),'reused_holdout_tasks':len(validation),'overlap':len(set(train)&set(validation)),'feature_count_global':28,'feature_count_hierarchical':112,'protocol_sha256':hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),'v2_used':False},'training_global_prior':{'model':best,'utilities':means},'methods':results,'c2_gate':{**gates,'pass':all(gates.values())},'interpretation':'development audit only; a pass permits method freeze and new v3, not a confirmatory claim'}
(OUT/'C2_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
