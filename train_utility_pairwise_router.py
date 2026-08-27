#!/usr/bin/env python3
"""Utility-pairwise compatibility router with interaction learnability gates."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold


ROOT = Path("/root")
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
DATA_ROOT = PROJECT / "data/finance_router"
PILOT = ROOT / "gemini_frar_pilot/five_model_v1"
AUDIT = ROOT / "five_model_routability_audit"
OUT = ROOT / "utility_pairwise_router_outputs"
V2 = DATA_ROOT / "safety_expansion_v2_counterexample_enrichment"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
PAIRS = tuple(combinations(MODELS, 2))
TIE_MARGIN = .01
SEED = 20260825

sys.path.insert(0, str(PROJECT))
from openclaw_router.experiment_protocol import objective_score as frozen_objective_score


def objective_score(task: dict, response: str):
    return frozen_objective_score(task, response + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def task_text(task: dict) -> str:
    flags = " ".join(key for key in ("requires_calculation", "requires_table_reasoning", "requires_kg_reasoning", "requires_verification") if task.get(key))
    return " ".join((str(task.get("dataset", "")), str(task.get("task_type", "")), str(task.get("risk_level", "")), flags,
        str(task.get("question", "")), str(task.get("context", "")), json.dumps(task.get("evidence") or [], ensure_ascii=False)))


def utility(quality: float, cost: float, latency: float, reliability: float) -> float:
    return .45*quality + .20*(1-min(cost/.02,1)) + .15*(1-min(latency/10000,1)) + .20*reliability


def aggregate_repeat_rows(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows: grouped[(row["task_id"], row["model"])].append(row)
    matrix=[]
    for (tid,model),values in sorted(grouped.items()):
        assert sorted(x["repeat"] for x in values)==[0,1,2]
        q=float(np.mean([x["quality"] for x in values]));c=float(np.mean([x["cost_usd"] for x in values]));l=float(np.mean([x["latency_ms"] for x in values]));r=float(np.mean([x["reliability"] for x in values]))
        matrix.append({"task_id":tid,"model":model,"quality":q,"failure":bool(r<1 or q<.6),"cost_usd":c,"latency_ms":l,"reliability":r,"utility":utility(q,c,l,r),"repeats":3})
    return matrix


def build_unified_v2() -> tuple[dict[str,dict],list[dict],list[dict]]:
    tasks={x["id"]:x for x in read_jsonl(V2/"tasks.jsonl")};old_responses={(x["task_id"],x["model"],int(x.get("repeat",0))):x for x in read_jsonl(V2/"responses.jsonl") if x.get("success")}
    old_judges={}
    for x in read_jsonl(ROOT/"phase3_2a1y22_outputs/utility_matrix_v2_frozen.jsonl"):old_judges[(x["task_id"],x["model"],int(x["repeat"]))]=[float(v) for v in x.get("judge_scores") or []]
    gemini_responses={(x["task_id"],"gemini-2.5-flash",int(x["repeat"])):x for x in read_jsonl(PILOT/"gemini_v2_responses.jsonl") if x.get("success")}
    gemini_judge_latest={}
    for x in read_jsonl(PILOT/"gemini_v2_judges.jsonl"):gemini_judge_latest[(x["task_id"],int(x["repeat"]),x["judge_model"])]=x
    responses={**old_responses,**gemini_responses};repeat_rows=[]
    for tid in sorted(tasks):
        task=tasks[tid]
        for model in MODELS:
            for repeat in range(3):
                response=responses[(tid,model,repeat)];obj=float(objective_score(task,str(response.get("answer") or "")) or 0);q=obj
                if task.get("task_type")=="financial_audit_compliance_qa":
                    if model=="gemini-2.5-flash":scores=[float(gemini_judge_latest[(tid,repeat,j)]["score"]) for j in ("deepseek-chat","qwen-plus")]
                    else:scores=old_judges[(tid,model,repeat)]
                    assert len(scores)>=2,(tid,model,repeat,len(scores));q=.55*obj+.45*float(np.mean(scores[:2]))
                repeat_rows.append({"task_id":tid,"model":model,"repeat":repeat,"quality":q,"objective_score":obj,
                    "cost_usd":float(response.get("cost_usd") or 0),"latency_ms":float(response.get("latency_ms") or 0),"reliability":float(response.get("error") is None)})
    assert len(repeat_rows)==140*5*3 and len({(x['task_id'],x['model'],x['repeat']) for x in repeat_rows})==len(repeat_rows)
    return tasks,repeat_rows,aggregate_repeat_rows(repeat_rows)


def labels(ids: list[str], outcomes: dict, pair: tuple[str,str]) -> np.ndarray:
    a,b=pair;delta=np.asarray([outcomes[(tid,b)]["utility"]-outcomes[(tid,a)]["utility"] for tid in ids]);return np.where(delta>TIE_MARGIN,1,np.where(delta<-TIE_MARGIN,0,-1))


def entropy(counts: Counter, n: int) -> float:
    value=-sum((c/n)*math.log(c/n) for c in counts.values() if c);return value/math.log(len(MODELS))


def scores_to_choices(ids: list[str], pair_prob: dict[tuple[str,str],np.ndarray]) -> tuple[dict[str,str],dict[str,dict[str,float]]]:
    scores={tid:{m:0.0 for m in MODELS} for tid in ids}
    for (a,b),prob in pair_prob.items():
        for i,tid in enumerate(ids):scores[tid][a]+=float(1-prob[i]);scores[tid][b]+=float(prob[i])
    for tid in ids:
        for m in MODELS:scores[tid][m]/=len(MODELS)-1
    return {tid:max(MODELS,key=lambda m:scores[tid][m]) for tid in ids},scores


def fit_and_oof(train_tasks: dict, outcomes: dict):
    ids=sorted(train_tasks);texts=np.asarray([task_text(train_tasks[x]) for x in ids],dtype=object);kf=KFold(5,shuffle=True,random_state=SEED)
    oof_prob={pair:np.zeros(len(ids)) for pair in PAIRS};pair_stats={};folds=list(kf.split(ids))
    for pair in PAIRS:
        y=labels(ids,outcomes,pair);correct=[];prior_correct=[];non_ties=0
        for tr,va in folds:
            tr_keep=tr[y[tr]>=0];va_keep=va[y[va]>=0];assert len(tr_keep)>0 and len(va_keep)>0
            vec=TfidfVectorizer(max_features=12000,ngram_range=(1,2),min_df=2,sublinear_tf=True);xtr=vec.fit_transform(texts[tr_keep]);xva=vec.transform(texts[va])
            target=y[tr_keep];majority=int(np.mean(target)>=.5)
            if len(np.unique(target))<2:prob=np.full(len(va),float(majority))
            else:prob=LogisticRegression(C=1,max_iter=2000,class_weight='balanced',random_state=SEED).fit(xtr,target).predict_proba(xva)[:,1]
            oof_prob[pair][va]=prob;correct.extend(((prob[va_keep-va[0]]>=.5).astype(int)==y[va_keep]).tolist() if np.array_equal(va,np.arange(va[0],va[-1]+1)) else [])
            # Index directly through a fold-local map; KFold indices are not guaranteed contiguous.
            local={global_i:i for i,global_i in enumerate(va)};correct.extend([int(prob[local[i]]>=.5)==int(y[i]) for i in va_keep] if not np.array_equal(va,np.arange(va[0],va[-1]+1)) else [])
            prior_correct.extend([majority==int(y[i]) for i in va_keep]);non_ties+=len(va_keep)
        pair_stats[f"{pair[0]}__vs__{pair[1]}"]={"non_tie_n":non_ties,"tie_n":int(np.sum(y<0)),"pairwise_accuracy":float(np.mean(correct)),"global_prior_accuracy":float(np.mean(prior_correct)),"lift":float(np.mean(correct)-np.mean(prior_correct))}
    oof_choices,oof_scores=scores_to_choices(ids,oof_prob)
    final={}
    for pair in PAIRS:
        y=labels(ids,outcomes,pair);keep=np.where(y>=0)[0];vec=TfidfVectorizer(max_features=12000,ngram_range=(1,2),min_df=2,sublinear_tf=True);x=vec.fit_transform(texts[keep]);target=y[keep]
        model=None if len(np.unique(target))<2 else LogisticRegression(C=1,max_iter=2000,class_weight='balanced',random_state=SEED).fit(x,target)
        final[pair]=(vec,model,float(np.mean(target)))
    return ids,oof_choices,oof_scores,pair_stats,final


def predict(ids: list[str],tasks: dict,models: dict):
    texts=[task_text(tasks[x]) for x in ids];probs={}
    for pair,(vec,model,prior) in models.items():probs[pair]=np.full(len(ids),prior) if model is None else model.predict_proba(vec.transform(texts))[:,1]
    return scores_to_choices(ids,probs)


def evaluate(ids: list[str],choices: dict[str,str],outcomes: dict,best_model: str):
    selected=np.asarray([outcomes[(tid,choices[tid])]["utility"] for tid in ids]);best=np.asarray([outcomes[(tid,best_model)]["utility"] for tid in ids]);oracle=np.asarray([max(outcomes[(tid,m)]["utility"] for m in MODELS) for tid in ids]);oracle_models=[max(MODELS,key=lambda m:outcomes[(tid,m)]["utility"]) for tid in ids]
    denom=float(oracle.mean()-best.mean());counts=Counter(choices.values())
    return {"mean_utility":float(selected.mean()),"best_single_utility":float(best.mean()),"oracle_utility":float(oracle.mean()),"oracle_gap":float(oracle.mean()-best.mean()),
        "oracle_match":float(np.mean([choices[tid]==oracle_models[i] for i,tid in enumerate(ids)])),"best_single_oracle_match":float(np.mean([best_model==m for m in oracle_models])),
        "gap_recovery":float((selected.mean()-best.mean())/denom) if denom>0 else None,"selection_counts":dict(counts),"selection_entropy_normalized":entropy(counts,len(ids)),"selection_change_vs_best_single":float(np.mean([choices[tid]!=best_model for tid in ids]))}


def main():
    OUT.mkdir(parents=True,exist_ok=True);train_tasks={x['id']:x for x in read_jsonl(PILOT/'gemini_training_pilot_tasks.jsonl')};train_matrix=read_jsonl(AUDIT/'five_model_task_model_matrix_frozen.jsonl');train_out={(x['task_id'],x['model']):x for x in train_matrix}
    test_tasks,test_repeats,test_matrix=build_unified_v2();assert not(set(train_tasks)&set(test_tasks));test_repeat_path=OUT/'v2_unified_repeat_outcomes.jsonl';test_matrix_path=OUT/'v2_unified_task_model_matrix.jsonl';test_repeat_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in test_repeats));test_matrix_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in test_matrix));test_out={(x['task_id'],x['model']):x for x in test_matrix}
    train_ids,oof_choices,oof_scores,pair_stats,models=fit_and_oof(train_tasks,train_out);test_ids=sorted(test_tasks);test_choices,test_scores=predict(test_ids,test_tasks,models)
    train_mean={m:float(np.mean([train_out[(tid,m)]['utility'] for tid in train_ids])) for m in MODELS};best=max(train_mean,key=train_mean.get);oof_eval=evaluate(train_ids,oof_choices,train_out,best);test_eval=evaluate(test_ids,test_choices,test_out,best)
    weighted_acc=float(np.average([x['pairwise_accuracy'] for x in pair_stats.values()],weights=[x['non_tie_n'] for x in pair_stats.values()]));weighted_prior=float(np.average([x['global_prior_accuracy'] for x in pair_stats.values()],weights=[x['non_tie_n'] for x in pair_stats.values()]))
    gates={"pairwise_accuracy_lift_ge_0.03":weighted_acc-weighted_prior>=.03,"oof_oracle_match_lift_ge_0.05":oof_eval['oracle_match']-oof_eval['best_single_oracle_match']>=.05,"oof_selection_entropy_ge_0.20":oof_eval['selection_entropy_normalized']>=.20,"oof_gap_recovery_ge_0.20":oof_eval['gap_recovery']>=.20,"independent_gap_recovery_positive":test_eval['gap_recovery']>0,"train_test_overlap_zero":True}
    report={"protocol":{"target":"1[U_b-U_a>0.01], 0[U_a-U_b>0.01], ties excluded","pairs":10,"folds":5,"grouping_unit":"task","seed":SEED,"frar_training_performed":False},"integrity":{"train_tasks":len(train_ids),"test_tasks":len(test_ids),"overlap":0,"test_repeat_rows":len(test_repeats),"test_matrix_rows":len(test_matrix),"test_matrix_sha256":hashlib.sha256(test_matrix_path.read_bytes()).hexdigest()},"training_best_single":{"model":best,"mean_utility":train_mean[best],"all_models":train_mean},"pairwise_cv":{"weighted_accuracy":weighted_acc,"weighted_global_prior_accuracy":weighted_prior,"weighted_lift":weighted_acc-weighted_prior,"by_pair":pair_stats},"oof_interaction_audit":oof_eval,"independent_v2":test_eval,"interaction_learnability_gate":{**gates,"pass":all(gates.values())}}
    (OUT/'utility_pairwise_router_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');
    with (OUT/'utility_pairwise_v2_decisions.jsonl').open('w') as f:
        for tid in test_ids:f.write(json.dumps({"task_id":tid,"compatibility":test_scores[tid],"selected_model":test_choices[tid]},ensure_ascii=False)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
