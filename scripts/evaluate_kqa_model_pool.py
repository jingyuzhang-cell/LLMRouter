#!/usr/bin/env python3
"""Compute reproducible endpoint-level KQAPro routing metrics."""
import argparse, json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from kqa_routing_utils import MODEL_SPECS, load_jsonl, normalized_status, question_type, validate_file
ROOT=Path(__file__).resolve().parents[1]; DEFAULT_DIR=ROOT/"data/kqapro/router_data"; VAL=ROOT/"data/kqapro/KQAPro_Baselines/dataset/val.json"
def quantile(values,p):
    if not values:return 0.0
    values=sorted(values); pos=(len(values)-1)*p; lo=math.floor(pos); hi=math.ceil(pos)
    return values[lo] if lo==hi else values[lo]*(hi-pos)+values[hi]*(pos-lo)
def ratio(a,b): return a/b if b else 0.0
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data-dir",type=Path,default=DEFAULT_DIR); ap.add_argument("--models",nargs="+",default=["deepseek","qwen","zhipu","gemini","qwen-3b-local"],choices=MODEL_SPECS); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--markdown",type=Path); ap.add_argument("--provisional",action="store_true"); a=ap.parse_args()
    val=json.loads(VAL.read_text()); qtypes={f"kqapro-val-{i:05d}":question_type(item) for i,item in enumerate(val)}
    tables={}; validations={}
    for model in a.models:
        path=a.data_dir/MODEL_SPECS[model]["file"]; check=validate_file(path); validations[model]=check
        if not check["passed"]: raise SystemExit(f"validation failed for {model}: {json.dumps(check,ensure_ascii=False)}")
        rows,_=load_jsonl(path); tables[model]={r["task_id"]:r for r in rows}
    ids=sorted(set.intersection(*(set(t) for t in tables.values()))); per_model={}
    correct_matrix={m:{tid:float(tables[m][tid].get("correct",0)) for tid in ids} for m in a.models}
    for model in a.models:
        spec=MODEL_SPECS[model]; rows=[tables[model][tid] for tid in ids]; answered=[r for r in rows if normalized_status(r)=="ok"]
        lat=[float(r.get("response_time") or 0) for r in rows]; inp=sum(int(r.get("input_tokens") or 0) for r in rows); out=sum(int(r.get("output_tokens") or 0) for r in rows)
        by_type={}
        for typ in sorted(set(qtypes.values())):
            subset=[r for r in rows if qtypes[r["task_id"]]==typ]; ans=[r for r in subset if normalized_status(r)=="ok"]
            by_type[typ]={"n":len(subset),"accuracy":ratio(sum(float(r.get("correct",0)) for r in subset),len(subset)),"conditional_accuracy":ratio(sum(float(r.get("correct",0)) for r in ans),len(ans)),"coverage":ratio(len(ans),len(subset))}
        per_model[model]={"display":spec["display"],"n":len(rows),"correct":int(sum(float(r.get("correct",0)) for r in rows)),"overall_accuracy":ratio(sum(float(r.get("correct",0)) for r in rows),len(rows)),"answered":len(answered),"conditional_accuracy":ratio(sum(float(r.get("correct",0)) for r in answered),len(answered)),"coverage":ratio(len(answered),len(rows)),"provider_refusals":sum(normalized_status(r)=="provider_refusal" for r in rows),"refusal_rate":ratio(sum(normalized_status(r)=="provider_refusal" for r in rows),len(rows)),"invalid_responses":sum(normalized_status(r)=="invalid_response" for r in rows),"invalid_response_rate":ratio(sum(normalized_status(r)=="invalid_response" for r in rows),len(rows)),"latency_seconds":{"mean":statistics.fmean(lat),"median":quantile(lat,.5),"p95":quantile(lat,.95),"total":sum(lat)},"tokens":{"input":inp,"output":out,"total":inp+out},"estimated_cost":{"amount":(inp*spec["input_price"]+out*spec["output_price"])/1_000_000,"currency":spec["currency"],"basis":"configured per-million-token rates"},"mean_cost_proxy":statistics.fmean(float(r.get("cost_proxy") or 0) for r in rows),"by_question_type":by_type}
    pairwise={}
    for i,left in enumerate(a.models):
        for right in a.models[i+1:]:
            lc=correct_matrix[left]; rc=correct_matrix[right]; pairwise[f"{left}__{right}"]={"both_correct":sum(lc[t]==1 and rc[t]==1 for t in ids),"left_only_correct":sum(lc[t]==1 and rc[t]==0 for t in ids),"right_only_correct":sum(lc[t]==0 and rc[t]==1 for t in ids),"both_wrong":sum(lc[t]==0 and rc[t]==0 for t in ids)}
    unique={m:[tid for tid in ids if correct_matrix[m][tid]==1 and all(correct_matrix[o][tid]==0 for o in a.models if o!=m)] for m in a.models}
    oracle_ids=[tid for tid in ids if any(correct_matrix[m][tid]==1 for m in a.models)]
    dominated=[]
    for weak in a.models:
        for strong in a.models:
            if weak==strong:continue
            w,s=per_model[weak],per_model[strong]
            same_currency=w["estimated_cost"]["currency"]==s["estimated_cost"]["currency"]
            cost_worse=(same_currency and w["estimated_cost"]["amount"]>s["estimated_cost"]["amount"]) or w["mean_cost_proxy"]>s["mean_cost_proxy"]
            if w["overall_accuracy"]<s["overall_accuracy"] and w["latency_seconds"]["mean"]>s["latency_seconds"]["mean"] and cost_worse and not unique[weak]: dominated.append({"model":weak,"dominated_by":strong,"criterion":"lower_accuracy_higher_latency_higher_comparable_cost_no_globally_unique_correct"})
    report={"schema":"kqapro-model-pool-evaluation-v1","provisional":a.provisional,"excludes":["llama"] if a.provisional else [],"created_utc":datetime.now(timezone.utc).isoformat(),"task_count":len(ids),"price_note":"Estimated from rates locked in scripts/kqa_routing_utils.py; currencies are not converted or summed.","question_type_basis":"final KQAPro program function mapped to stable semantic groups","models":per_model,"pairwise_complementarity":pairwise,"globally_unique_correct":{"counts":{m:len(v) for m,v in unique.items()},"task_ids":unique},"oracle":{"correct":len(oracle_ids),"accuracy":ratio(len(oracle_ids),len(ids))},"strictly_dominated_candidates":dominated}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    if a.markdown:
        lines=["# KQAPro Provisional Model-Pool Evaluation","","**PROVISIONAL — Llama excluded. Do not treat Oracle or pool selection as final.**","",f"Common tasks: {len(ids)}  ",f"Oracle accuracy: {report['oracle']['accuracy']:.4%}","","| Model | Accuracy | Conditional | Coverage | Refusal | Invalid | Mean latency (s) | Cost |","|---|---:|---:|---:|---:|---:|---:|---:|"]
        for m in a.models:
            x=per_model[m]; c=x["estimated_cost"]; lines.append(f"| {x['display']} | {x['overall_accuracy']:.4%} | {x['conditional_accuracy']:.4%} | {x['coverage']:.4%} | {x['refusal_rate']:.4%} | {x['invalid_response_rate']:.4%} | {x['latency_seconds']['mean']:.3f} | {c['amount']:.6f} {c['currency']} |")
        lines += ["","## Globally unique correct",""]+[f"- {m}: {len(unique[m])}" for m in a.models]+["","## Strictly dominated candidates","",json.dumps(dominated,ensure_ascii=False)]
        a.markdown.parent.mkdir(parents=True,exist_ok=True); a.markdown.write_text("\n".join(lines)+"\n")
    print(json.dumps({"output":str(a.output),"markdown":str(a.markdown) if a.markdown else None,"provisional":a.provisional,"task_count":len(ids),"oracle_accuracy":report["oracle"]["accuracy"],"dominated":dominated},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
