#!/usr/bin/env python3
"""Leakage-safe five-model pairwise compatibility and FRAR-v2 experiment."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold


ROOT = Path("/root")
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
DATA_ROOT = PROJECT / "data/finance_router"
PILOT = ROOT / "gemini_frar_pilot/five_model_v1"
OUT = ROOT / "frar_v2_five_model_outputs"
V2 = DATA_ROOT / "safety_expansion_v2_counterexample_enrichment"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo", "gemini-2.5-flash")
PAIRS = tuple(combinations(MODELS, 2))
SEED = 20260825


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def task_text(task: dict) -> str:
    evidence = json.dumps(task.get("evidence") or [], ensure_ascii=False)
    flags = " ".join(k for k in ("requires_calculation", "requires_table_reasoning", "requires_kg_reasoning", "requires_verification") if task.get(k))
    return " ".join((str(task.get("dataset", "")), str(task.get("task_type", "")), str(task.get("risk_level", "")), flags,
                     str(task.get("question", "")), str(task.get("context", "")), evidence))


def utility(row: dict) -> float:
    return (0.45 * row["quality"] + 0.20 / (1 + row["cost_usd"] * 1000) +
            0.15 / (1 + row["latency_ms"] / 1000) + 0.20 * row["reliability"])


def build_training_matrix(tasks: list[dict]) -> list[dict]:
    old_models = MODELS[:-1]
    source_cache: dict[str, dict[tuple[str, str], list[dict]]] = {}
    for source in sorted({t["_source_dataset_dir"] for t in tasks}):
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in read_jsonl(DATA_ROOT / source / "scored_responses.jsonl"):
            if row.get("quality") is not None:
                grouped[(row["task_id"], row["model"])].append(row)
        source_cache[source] = grouped

    gemini_responses = {(r["task_id"], int(r["repeat"])): r for r in read_jsonl(PILOT / "gemini_training_pilot_responses.jsonl") if r.get("success")}
    judge_latest = {}
    for row in read_jsonl(PILOT / "gemini_training_pilot_judges.jsonl"):
        judge_latest[(row["task_id"], int(row["repeat"]), row["judge_model"])] = row

    matrix = []
    for task in tasks:
        task_id = task["id"]
        for model in old_models:
            rows = source_cache[task["_source_dataset_dir"]][(task_id, model)]
            assert len(rows) == 3, (task_id, model, len(rows))
            matrix.append({"task_id": task_id, "model": model, "dataset": task.get("dataset"), "task_type": task.get("task_type"),
                           "risk_level": task.get("risk_level"), "quality": float(np.mean([float(x["quality"]) for x in rows])),
                           "failure": float(np.mean([float(x["quality"]) < .5 for x in rows])),
                           "cost_usd": float(np.mean([float(x.get("cost_usd") or 0) for x in rows])),
                           "latency_ms": float(np.mean([float(x.get("latency_ms") or 0) for x in rows])),
                           "reliability": float(np.mean([float(x.get("reliability", 1)) for x in rows]))})
        qualities = []
        responses = []
        for repeat in range(3):
            response = gemini_responses[(task_id, repeat)]
            scores = [float(judge_latest[(task_id, repeat, judge)]["score"]) for judge in ("deepseek-chat", "qwen-plus")]
            assert len(scores) == 2
            qualities.append(float(np.mean(scores)))
            responses.append(response)
        matrix.append({"task_id": task_id, "model": "gemini-2.5-flash", "dataset": task.get("dataset"), "task_type": task.get("task_type"),
                       "risk_level": task.get("risk_level"), "quality": float(np.mean(qualities)),
                       "failure": float(np.mean([x < .5 for x in qualities])),
                       "cost_usd": float(np.mean([float(x.get("cost_usd") or 0) for x in responses])),
                       "latency_ms": float(np.mean([float(x.get("latency_ms") or 0) for x in responses])), "reliability": 1.0})
    assert len(matrix) == len(tasks) * len(MODELS)
    return matrix


def load_test_outcomes() -> tuple[dict[str, dict], dict[tuple[str, str], dict]]:
    tasks = {x["id"]: x for x in read_jsonl(V2 / "tasks.jsonl")}
    rows = read_jsonl(PILOT / "five_model_task_matrix.jsonl")
    outcomes = {}
    for row in rows:
        outcomes[(row["task_id"], row["model"])] = {"quality": float(row["quality"]), "failure": float(row["repeat_failure_rate"]),
                                                     "cost_usd": float(row.get("cost_usd") or 0), "latency_ms": float(row.get("latency_ms") or 0),
                                                     "reliability": 1.0}
    assert len(outcomes) == len(tasks) * len(MODELS)
    return tasks, outcomes


class ConstantClassifier:
    def __init__(self, value: float): self.value = float(value)
    def predict_proba(self, x): return np.column_stack((np.full(x.shape[0], 1-self.value), np.full(x.shape[0], self.value)))


def pair_labels(task_ids: list[str], outcomes: dict[tuple[str, str], dict], pair: tuple[str, str]) -> np.ndarray:
    a, b = pair
    values = []
    for tid in task_ids:
        qa, qb = outcomes[(tid, a)]["quality"], outcomes[(tid, b)]["quality"]
        values.append(1 if qb > qa else 0)
    return np.asarray(values)


def fit_pairwise(train_tasks: dict[str, dict], train_outcomes: dict[tuple[str, str], dict]):
    ids = sorted(train_tasks); texts = [task_text(train_tasks[x]) for x in ids]
    vectorizer = TfidfVectorizer(max_features=12000, ngram_range=(1,2), min_df=2, sublinear_tf=True)
    x = vectorizer.fit_transform(texts); models = {}; cv = {}
    groups = np.arange(len(ids)); splitter = GroupKFold(5)
    for pair in PAIRS:
        y = pair_labels(ids, train_outcomes, pair); oof = np.zeros(len(ids))
        for tr, va in splitter.split(x, y, groups):
            if len(np.unique(y[tr])) < 2: predictor = ConstantClassifier(float(np.mean(y[tr])))
            else: predictor = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=SEED).fit(x[tr], y[tr])
            oof[va] = predictor.predict_proba(x[va])[:,1]
        cv[f"{pair[0]}__vs__{pair[1]}"] = {"n": len(y), "positive_rate": float(np.mean(y)),
            "accuracy": float(accuracy_score(y, oof >= .5)), "auc": float(roc_auc_score(y, oof)) if len(np.unique(y)) == 2 else None,
            "log_loss": float(log_loss(y, np.clip(oof, 1e-6, 1-1e-6), labels=[0,1]))}
        models[pair] = (ConstantClassifier(float(np.mean(y))) if len(np.unique(y)) < 2 else
                        LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=SEED).fit(x, y))
    return vectorizer, models, cv


def compatibility_scores(ids: list[str], tasks: dict[str, dict], vectorizer, pair_models) -> dict[str, dict[str, float]]:
    x = vectorizer.transform([task_text(tasks[tid]) for tid in ids]); scores = {tid: {m: 0.0 for m in MODELS} for tid in ids}
    for pair, model in pair_models.items():
        p_b = model.predict_proba(x)[:,1]
        for i, tid in enumerate(ids):
            scores[tid][pair[0]] += float(1-p_b[i]); scores[tid][pair[1]] += float(p_b[i])
    for tid in ids:
        for model in MODELS: scores[tid][model] /= len(MODELS)-1
    return scores


def pointwise_predictions(train_tasks, train_outcomes, test_tasks):
    train_ids = sorted(train_tasks); test_ids = sorted(test_tasks)
    texts=[]; quality=[]; failure=[]
    for tid in train_ids:
        base=task_text(train_tasks[tid])
        for model in MODELS:
            texts.append(model.replace('-','_')+' '+base); quality.append(train_outcomes[(tid,model)]["quality"]); failure.append(train_outcomes[(tid,model)]["failure"])
    vec=TfidfVectorizer(max_features=20000,ngram_range=(1,2),min_df=2,sublinear_tf=True);x=vec.fit_transform(texts)
    q=Ridge(alpha=8.0,solver='lsqr').fit(x,np.asarray(quality));r=Ridge(alpha=8.0,solver='lsqr').fit(x,np.asarray(failure))
    pred={}
    for tid in test_ids:
        z=vec.transform([m.replace('-','_')+' '+task_text(test_tasks[tid]) for m in MODELS]);
        for m,qh,rh in zip(MODELS,np.clip(q.predict(z),0,1),np.clip(r.predict(z),0,1)):pred[(tid,m)]={'quality_hat':float(qh),'risk_hat':float(rh)}
    telemetry={m:{k:float(np.median([train_outcomes[(tid,m)][k] for tid in train_ids])) for k in ('cost_usd','latency_ms','reliability')} for m in MODELS}
    for key,v in pred.items():
        t=telemetry[key[1]];v['utility_hat']=0.45*v['quality_hat']+0.20/(1+t['cost_usd']*1000)+0.15/(1+t['latency_ms']/1000)+0.20*t['reliability']
    return pred,telemetry


def summarize(decisions, outcomes, tasks):
    result={}; records={}
    for name,picks in decisions.items():
        rows=[]
        for tid,model in picks.items():
            out=outcomes[(tid,model)];oracle=max(utility(outcomes[(tid,m)]) for m in MODELS);u=utility(out)
            rows.append({"task_id":tid,"model":model,**out,"utility":u,"regret":oracle-u,"risk_level":str(tasks[tid].get('risk_level','')).lower()})
        high=[x for x in rows if x['risk_level']=='high']
        result[name]={"n_tasks":len(rows),"mean_quality":float(np.mean([x['quality'] for x in rows])),"failure_rate":float(np.mean([x['failure'] for x in rows])),
            "high_risk_failure_rate":float(np.mean([x['failure'] for x in high])),"mean_cost_usd":float(np.mean([x['cost_usd'] for x in rows])),
            "mean_latency_ms":float(np.mean([x['latency_ms'] for x in rows])),"mean_utility":float(np.mean([x['utility'] for x in rows])),
            "mean_regret":float(np.mean([x['regret'] for x in rows])),"selection_counts":dict(Counter(x['model'] for x in rows))}
        records[name]=rows
    return result,records


def main():
    OUT.mkdir(parents=True,exist_ok=True);training_tasks_list=read_jsonl(PILOT/'gemini_training_pilot_tasks.jsonl');training_tasks={x['id']:x for x in training_tasks_list}
    matrix=build_training_matrix(training_tasks_list);matrix_path=OUT/'five_model_training_matrix.jsonl';matrix_path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in matrix),encoding='utf-8')
    train_out={(x['task_id'],x['model']):x for x in matrix};test_tasks,test_out=load_test_outcomes();assert not (set(training_tasks)&set(test_tasks))
    vectorizer,pair_models,cv=fit_pairwise(training_tasks,train_out);test_ids=sorted(test_tasks);compat=compatibility_scores(test_ids,test_tasks,vectorizer,pair_models);pred,telemetry=pointwise_predictions(training_tasks,train_out,test_tasks)
    training_mean={m:float(np.mean([train_out[(tid,m)]['quality'] for tid in training_tasks])) for m in MODELS};best=max(training_mean,key=training_mean.get);rng=np.random.default_rng(SEED)
    decisions={"random":{tid:str(rng.choice(MODELS)) for tid in test_ids},"best_single":{tid:best for tid in test_ids},
      "cost_only":{tid:min(MODELS,key=lambda m:telemetry[m]['cost_usd']) for tid in test_ids},
      "route_pairwise":{tid:max(MODELS,key=lambda m:compat[tid][m]) for tid in test_ids},
      "utility_only":{tid:max(MODELS,key=lambda m:pred[(tid,m)]['utility_hat']) for tid in test_ids},
      "rank_safety":{tid:max(MODELS,key=lambda m:pred[(tid,m)]['utility_hat']-.3*pred[(tid,m)]['risk_hat']) for tid in test_ids},
      "frar_v2":{tid:max(MODELS,key=lambda m:.6*pred[(tid,m)]['utility_hat']+.3*compat[tid][m]-.1*pred[(tid,m)]['risk_hat']) for tid in test_ids},
      "oracle":{tid:max(MODELS,key=lambda m:utility(test_out[(tid,m)])) for tid in test_ids}}
    metrics,records=summarize(decisions,test_out,test_tasks);best_single_model=best
    for name in decisions:
        if name!='best_single':metrics[name]['selection_change_vs_best_single']=float(np.mean([decisions[name][tid]!=best_single_model for tid in test_ids]))
    payload={"protocol":{"version":"frar-v2-five-model-v1","models":MODELS,"train_tasks":len(training_tasks),"test_tasks":len(test_tasks),"train_test_overlap":0,
      "pairwise_pairs":len(PAIRS),"frar_v2_score":"0.6*utility_hat + 0.3*compatibility - 0.1*risk_hat","selection_outcome_separation":True,"seed":SEED},
      "integrity":{"training_matrix_sha256":hashlib.sha256(matrix_path.read_bytes()).hexdigest()},"training":{"mean_quality":training_mean,"best_single":best,"telemetry":telemetry},
      "pairwise_cv":cv,"metrics":metrics}
    (OUT/'frar_v2_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (OUT/'frar_v2_task_decisions.jsonl').open('w',encoding='utf-8') as f:
        for tid in test_ids:f.write(json.dumps({"task_id":tid,"compatibility":compat[tid],"predictions":{m:pred[(tid,m)] for m in MODELS},"decisions":{n:d[tid] for n,d in decisions.items()}},ensure_ascii=False)+'\n')
    print(json.dumps(payload,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
