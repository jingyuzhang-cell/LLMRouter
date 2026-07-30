"""One-time, paired evaluation for a complete routing matrix."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Mapping
import numpy as np
import pandas as pd

class EvaluationLockedError(RuntimeError): pass

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _bootstrap(delta, repeats, seed):
    delta=np.asarray(delta,dtype=float); rng=np.random.default_rng(seed)
    idx=rng.integers(0,len(delta),size=(repeats,len(delta)))
    values=delta[idx].mean(1)
    return [float(x) for x in np.quantile(values,[.025,.975])]

def _metric(selection, perf, costs, sizes, strong, cheap):
    queries=perf.index; chosen=np.array([selection[q] for q in queries])
    col={m:i for i,m in enumerate(perf.columns)}
    vals=np.array([perf.iloc[i,col[m]] for i,m in enumerate(chosen)])
    c=np.array([costs.iloc[i,col[m]] for i,m in enumerate(chosen)])
    z=np.array([sizes[m] for m in chosen],dtype=float)
    sv=perf[strong].to_numpy(); different=chosen!=strong
    harm=different&(vals<sv); rescue=different&(vals>sv)
    return {"performance":float(vals.mean()),"actual_token_cost":float(c.sum()),"mean_cost":float(c.mean()),"mean_size_b":float(z.mean()),"small_model_coverage":float(np.mean([m==cheap for m in chosen])),"non_strong_coverage":float(different.mean()),"harm_count":int(harm.sum()),"harm_rate":float(harm.mean()),"rescue_count":int(rescue.sum()),"_values":vals,"_costs":c,"_chosen":chosen}

def _clean(x):
    return {k:v for k,v in x.items() if not k.startswith("_")}

def evaluate_matrix_once(results, queries, router_predictions, model_info, output_dir, preregistration=None, repeats=10000, seed=20260726, random_simulations=1000):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True); lock=out/"EVALUATED_ONCE"; result_path=out/"RESULT.json"
    if lock.exists(): raise EvaluationLockedError("confirmation matrix was already evaluated")
    required={"query","task_name","model_name","repeat_index","performance","prompt_tokens","completion_tokens","success"}
    missing=required-set(results.columns)
    if missing: raise ValueError(f"missing result columns: {sorted(missing)}")
    qlist=queries["query"].drop_duplicates().tolist(); models=list(model_info)
    good=results[results.success & results.performance.notna()].copy()
    counts=good.groupby(["query","model_name"]).repeat_index.nunique()
    expected=pd.MultiIndex.from_product([qlist,models],names=["query","model_name"])
    counts=counts.reindex(expected,fill_value=0)
    if (counts<2).any(): raise ValueError(f"incomplete matrix: {int((counts<2).sum())} pairs below two repeats")
    if set(router_predictions)!=set(qlist): raise ValueError("router predictions do not exactly cover sealed queries")
    if not set(router_predictions.values())<=set(models): raise ValueError("router predicted an unknown model")
    if preregistration is not None:
        pre=Path(preregistration)
        lock.write_text(json.dumps({"state":"started","results_sha256":_sha(results.attrs["source_path"]) if results.attrs.get("source_path") else None,"preregistration_sha256":_sha(pre)},indent=2))
    else: lock.write_text(json.dumps({"state":"started"},indent=2))
    agg=good.groupby(["query","model_name"]).agg(performance=("performance","mean"),prompt_tokens=("prompt_tokens","mean"),completion_tokens=("completion_tokens","mean")).reset_index()
    perf=agg.pivot(index="query",columns="model_name",values="performance").reindex(index=qlist,columns=models)
    input_prices={m:float(model_info[m]["input_price"]) for m in models}; output_prices={m:float(model_info[m]["output_price"]) for m in models}
    agg["cost"]=agg.apply(lambda r:(r.prompt_tokens*input_prices[r.model_name]+r.completion_tokens*output_prices[r.model_name])/1_000_000,axis=1)
    costs=agg.pivot(index="query",columns="model_name",values="cost").reindex(index=qlist,columns=models)
    sizes={m:float(model_info[m]["size_b"]) for m in models}; strong=max(models,key=lambda m:sizes[m]); cheap=min(models,key=lambda m:(input_prices[m]+output_prices[m],sizes[m]))
    selections={"router":router_predictions,"always_strong":{q:strong for q in qlist},"always_cheap":{q:cheap for q in qlist},"round_robin":{q:models[i%len(models)] for i,q in enumerate(qlist)}}
    selections["oracle"]={q:min(models,key=lambda m:(-perf.loc[q,m],costs.loc[q,m])) for q in qlist}
    metrics={name:_metric(sel,perf,costs,sizes,strong,cheap) for name,sel in selections.items()}
    rng=np.random.default_rng(seed); random_rows=[]
    for _ in range(random_simulations):
        sel={q:models[int(rng.integers(len(models)))] for q in qlist};random_rows.append(_metric(sel,perf,costs,sizes,strong,cheap))
    random_summary={k:float(np.mean([r[k] for r in random_rows])) for k in ["performance","actual_token_cost","mean_cost","mean_size_b","small_model_coverage","non_strong_coverage","harm_rate"]}
    base=metrics["always_strong"]; router=metrics["router"]
    paired={"performance_delta":float(np.mean(router["_values"]-base["_values"])),"performance_delta_ci95":_bootstrap(router["_values"]-base["_values"],repeats,seed),"cost_delta":float(np.mean(router["_costs"]-base["_costs"])),"cost_delta_ci95":_bootstrap(router["_costs"]-base["_costs"],repeats,seed+1)}
    overall={k:_clean(v) for k,v in metrics.items()};overall["random_1000_mean"]=random_summary
    points=[(k,v["performance"],v["actual_token_cost"]) for k,v in overall.items() if "performance" in v]
    pareto=[name for name,p,c in points if not any((p2>=p and c2<=c and (p2>p or c2<c)) for n2,p2,c2 in points if n2!=name)]
    per_task={}
    qmeta=queries.drop_duplicates("query").set_index("query")
    for task,idx in qmeta.groupby("task_name").groups.items():
        qs=list(idx);tp=perf.loc[qs];tc=costs.loc[qs]
        task_methods={name:_clean(_metric({q:sel[q] for q in qs},tp,tc,sizes,strong,cheap)) for name,sel in selections.items()}
        task_points=[(name,value["performance"],value["actual_token_cost"]) for name,value in task_methods.items()]
        task_methods["pareto_methods"]=[name for name,p,c in task_points if not any((p2>=p and c2<=c and (p2>p or c2<c)) for n2,p2,c2 in task_points if n2!=name)]
        per_task[task]=task_methods
    degenerate=[];nondeg=0
    chosen=pd.Series(router["_chosen"],index=qlist)
    for task,idx in qmeta.groupby("task_name").groups.items():
        vc=chosen.loc[list(idx)].value_counts(normalize=True);ok=len(idx)>=20 and int((vc>=.10).sum())>=2
        nondeg+=int(ok)
        if not ok:degenerate.append(task)
    strong_cost=base["actual_token_cost"]; savings=1-router["actual_token_cost"]/strong_cost if strong_cost else 0
    criteria={"test_queries_at_least_1000":len(qlist)>=1000,"small_model_coverage_at_least_20pct":router["small_model_coverage"]>=.20,"actual_cost_saving_at_least_15pct":savings>=.15,"accuracy_delta_ci_lower_at_least_minus_0_5pp":paired["performance_delta_ci95"][0]>=-.005,"harm_rate_at_most_3pct":router["harm_rate"]<=.03,"nondegenerate_tasks_at_least_2":nondeg>=2}
    report={"queries":len(qlist),"models":models,"strong_model":strong,"cheap_model":cheap,"overall":overall,"per_task":per_task,"paired_router_vs_strong":paired,"router_cost_saving_fraction":float(savings),"pareto_methods":pareto,"nondegenerate_task_count":nondeg,"degenerate_task_alarm":bool(degenerate),"degenerate_tasks":degenerate,"success_criteria":criteria,"primary_success":all(criteria.values())}
    result_path.write_text(json.dumps(report,indent=2))
    lock.write_text(json.dumps({"state":"complete","result_sha256":_sha(result_path)},indent=2))
    return report
