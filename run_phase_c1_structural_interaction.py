#!/usr/bin/env python3
"""Phase C1 structural, centered delta-utility interaction learning."""

import hashlib
import json
import math
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path("/root")
PROTOCOL = ROOT / "phase_c1/C1_PROTOCOL.json"
SPLIT = ROOT / "target_support_dev_split/TARGET_SUPPORT_DEV_SPLIT.json"
TASKS = ROOT / "gemini_frar_pilot/five_model_v1/gemini_training_pilot_tasks.jsonl"
MATRIX = ROOT / "five_model_routability_audit/five_model_task_model_matrix_frozen.jsonl"
OUT = ROOT / "phase_c1"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
PAIRS = tuple(combinations(MODELS, 2))
SEED = 20260827


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def structural_features(task):
    question = str(task.get("question") or ""); context = str(task.get("context") or "")
    evidence = task.get("evidence") or []; evidence_text = json.dumps(evidence, ensure_ascii=False)
    table = task.get("table") or []; rows = len(table) if isinstance(table, list) else 0
    cols = max((len(row) for row in table if isinstance(row, list)), default=0) if isinstance(table, list) else 0
    all_text = " ".join((question, context, evidence_text)); lower = all_text.lower()
    nums = re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?%?", all_text)
    entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{2,}\b", all_text)
    arithmetic = sum(lower.count(token) for token in ("calculate", "difference", "ratio", "percent", "increase", "decrease", "total", "average", "计算", "比例", "增长", "减少"))
    multispan = sum(lower.count(token) for token in ("both", "respectively", "compare", "which", "分别", "比较", "哪些"))
    multihop = sum(lower.count(token) for token in ("indirect", "two-step", "multi-hop", "through", "间接", "通过"))
    regulation = sum(lower.count(token) for token in ("must", "shall", "require", "regulation", "compliance", "audit", "policy", "应当", "必须", "合规", "审计"))
    ambiguity = sum(lower.count(token) for token in ("may", "could", "approximately", "unclear", "可能", "大约", "不明确"))
    citations = len(re.findall(r"\b(?:section|rule|article|paragraph)\s*[\d.()]+|第[一二三四五六七八九十\d]+条", lower))
    spans = len(evidence) if isinstance(evidence, list) else 0
    risk = str(task.get("risk_level") or "unknown").lower()
    values = [
        len(question), len(context), len(evidence_text), len(question.split()), len(context.split()),
        rows, cols, rows * cols, len(nums), sum(x.endswith("%") for x in nums),
        arithmetic, multispan, multihop, spans, len(set(entities)), regulation, ambiguity, citations,
        len(context) / max(1, spans), spans / max(1, len(context)),
        int(bool(task.get("requires_calculation"))), int(bool(task.get("requires_table_reasoning"))),
        int(bool(task.get("requires_kg_reasoning"))), int(bool(task.get("requires_verification"))),
        int(risk == "low"), int(risk == "medium"), int(risk == "high"), int(len(context) >= 8000),
    ]
    return np.asarray(values, dtype=float)


def bt_choices(ids, predicted):
    choices = {}; score_rows = {}
    for row_index, task_id in enumerate(ids):
        design = []; target = []
        for a, b in PAIRS:
            vector = np.zeros(len(MODELS)); vector[MODELS.index(a)] = 1; vector[MODELS.index(b)] = -1
            design.append(vector); target.append(predicted[(a, b)][row_index])
        design.append(np.ones(len(MODELS))); target.append(0.0)
        scores = np.linalg.lstsq(np.asarray(design), np.asarray(target), rcond=None)[0]
        score_rows[task_id] = {model: float(scores[i]) for i, model in enumerate(MODELS)}
        choices[task_id] = MODELS[int(np.argmax(scores))]
    return choices, score_rows


def entropy(counts, n):
    return -sum((count/n)*math.log(count/n) for count in counts.values() if count) / math.log(len(MODELS))


def evaluate(ids, choices, outcomes, best_model):
    selected = np.asarray([outcomes[(task_id, choices[task_id])]["utility"] for task_id in ids])
    best = np.asarray([outcomes[(task_id, best_model)]["utility"] for task_id in ids])
    oracle = np.asarray([max(outcomes[(task_id, model)]["utility"] for model in MODELS) for task_id in ids])
    oracle_models = [max(MODELS, key=lambda model: outcomes[(task_id, model)]["utility"]) for task_id in ids]
    gap = float(oracle.mean() - best.mean()); counts = Counter(choices.values())
    return {"mean_utility": float(selected.mean()), "best_single_utility": float(best.mean()), "oracle_utility": float(oracle.mean()),
            "oracle_gap": gap, "gap_recovery": float((selected.mean()-best.mean())/gap) if gap > 0 else None,
            "oracle_match": float(np.mean([choices[task_id] == oracle_models[i] for i, task_id in enumerate(ids)])),
            "best_single_oracle_match": float(np.mean([best_model == model for model in oracle_models])),
            "selection_counts": dict(counts), "selection_entropy_normalized": entropy(counts, len(ids))}


def bootstrap(ids, choices, outcomes, best_model):
    selected=np.asarray([outcomes[(t,choices[t])]["utility"] for t in ids]);best=np.asarray([outcomes[(t,best_model)]["utility"] for t in ids]);oracle=np.asarray([max(outcomes[(t,m)]["utility"] for m in MODELS) for t in ids])
    rng=np.random.default_rng(SEED);idx=rng.integers(0,len(ids),size=(10000,len(ids)));den=oracle[idx].mean(1)-best[idx].mean(1);rec=np.divide(selected[idx].mean(1)-best[idx].mean(1),den,out=np.full_like(den,np.nan),where=den>0)
    return {"mean":float(np.nanmean(rec)),"ci95_low":float(np.nanquantile(rec,.025)),"ci95_high":float(np.nanquantile(rec,.975)),"positive_probability":float(np.nanmean(rec>0))}


def fit_predict(train_ids, predict_ids, tasks, outcomes):
    x_train=np.vstack([structural_features(tasks[t]) for t in train_ids]);x_predict=np.vstack([structural_features(tasks[t]) for t in predict_ids]);predicted={};stats={}
    for pair in PAIRS:
        a,b=pair;raw=np.asarray([outcomes[(t,a)]["utility"]-outcomes[(t,b)]["utility"] for t in train_ids]);prior=float(raw.mean());target=raw-prior
        model=make_pipeline(StandardScaler(),Ridge(alpha=10.0)).fit(x_train,target);residual=model.predict(x_predict);predicted[pair]=residual
        raw_prediction=prior+model.predict(x_train);baseline=np.full(len(train_ids),prior);keep=np.abs(raw)>=.01
        stats[f"{a}__vs__{b}"]={"n":len(raw),"tie_n":int(np.sum(~keep)),"global_delta_mean":prior,
            "train_sign_accuracy":float(np.mean(np.sign(raw_prediction[keep])==np.sign(raw[keep]))) if np.any(keep) else None,
            "global_prior_sign_accuracy":float(np.mean(np.sign(baseline[keep])==np.sign(raw[keep]))) if np.any(keep) else None,
            "centered_r2":float(model.score(x_train,target))}
    return bt_choices(predict_ids,predicted)+(stats,)


def oof(train_ids,tasks,outcomes):
    folds=KFold(5,shuffle=True,random_state=SEED);predicted={pair:np.zeros(len(train_ids)) for pair in PAIRS};correct=[];prior_correct=[]
    x=np.vstack([structural_features(tasks[t]) for t in train_ids])
    for tr,va in folds.split(train_ids):
        for pair in PAIRS:
            a,b=pair;raw=np.asarray([outcomes[(t,a)]["utility"]-outcomes[(t,b)]["utility"] for t in train_ids]);prior=float(raw[tr].mean());target=raw[tr]-prior
            model=make_pipeline(StandardScaler(),Ridge(alpha=10.0)).fit(x[tr],target);res=model.predict(x[va]);predicted[pair][va]=res
            keep=[i for i in va if abs(raw[i])>=.01];correct.extend([np.sign(prior+res[list(va).index(i)])==np.sign(raw[i]) for i in keep]);prior_correct.extend([np.sign(prior)==np.sign(raw[i]) for i in keep])
    choices,scores=bt_choices(train_ids,predicted)
    return choices,scores,float(np.mean(correct)),float(np.mean(prior_correct))


protocol=json.loads(PROTOCOL.read_text());split=json.loads(SPLIT.read_text());tasks={x['id']:x for x in read_jsonl(TASKS)};matrix=read_jsonl(MATRIX);outcomes={(x['task_id'],x['model']):x for x in matrix}
train_ids=split['train_task_ids'];validation_ids=split['validation_task_ids'];train_mean={m:float(np.mean([outcomes[(t,m)]['utility'] for t in train_ids])) for m in MODELS};best=max(train_mean,key=train_mean.get)
oof_choices,_,pair_acc,prior_acc=oof(train_ids,tasks,outcomes);oof_result=evaluate(train_ids,oof_choices,outcomes,best)
validation_choices,validation_scores,fit_stats=fit_predict(train_ids,validation_ids,tasks,outcomes);validation=evaluate(validation_ids,validation_choices,outcomes,best);validation['gap_recovery_bootstrap']=bootstrap(validation_ids,validation_choices,outcomes,best)

groups={"TAT-low":[t for t in train_ids+validation_ids if tasks[t].get('dataset')=='TAT-QA' and tasks[t].get('risk_level')=='low'],
        "TAT-medium":[t for t in train_ids+validation_ids if tasks[t].get('dataset')=='TAT-QA' and tasks[t].get('risk_level')=='medium'],
        "Obli-high":[t for t in train_ids+validation_ids if tasks[t].get('dataset')=='ObliQA' and tasks[t].get('risk_level')=='high']}
logo={}
all_support=sorted(set(sum(groups.values(),[])))
for name,heldout in groups.items():
    training=sorted(set(all_support)-set(heldout));means={m:float(np.mean([outcomes[(t,m)]['utility'] for t in training])) for m in MODELS};group_best=max(means,key=means.get);choices,_,_=fit_predict(training,heldout,tasks,outcomes);logo[name]=evaluate(heldout,choices,outcomes,group_best);logo[name]['gap_recovery_bootstrap']=bootstrap(heldout,choices,outcomes,group_best)

gates={"validation_recovery_ge_0.20":validation['gap_recovery']>=.20,"validation_utility_above_best_single":validation['mean_utility']>validation['best_single_utility'],
       "pairwise_accuracy_lift_ge_0.03":pair_acc-prior_acc>=.03,"oof_recovery_ge_0.20":oof_result['gap_recovery']>=.20,
       "validation_oracle_match_lift_ge_0.05":validation['oracle_match']-validation['best_single_oracle_match']>=.05,
       "bootstrap_positive_probability_ge_0.95":validation['gap_recovery_bootstrap']['positive_probability']>=.95}
report={"protocol":protocol,"integrity":{"protocol_sha256":hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),"split_sha256":hashlib.sha256(SPLIT.read_bytes()).hexdigest(),"v2_used":False,"dataset_id_feature":False,"task_type_id_feature":False,"feature_count":len(structural_features(tasks[train_ids[0]]))},
        "training_best_single":{"model":best,"utilities":train_mean},"pairwise_interaction":{"oof_sign_accuracy":pair_acc,"oof_global_prior_accuracy":prior_acc,"lift":pair_acc-prior_acc,"full_fit_diagnostics":fit_stats},
        "oof":oof_result,"development_validation":validation,"leave_one_group_out":logo,"c1_gate":{**gates,"pass":all(gates.values())}}
(OUT/'C1_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');
with (OUT/'C1_VALIDATION_DECISIONS.jsonl').open('w') as f:
    for t in sorted(validation_ids):f.write(json.dumps({'task_id':t,'latent_scores':validation_scores[t],'selected_model':validation_choices[t]},ensure_ascii=False)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
