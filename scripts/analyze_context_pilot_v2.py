#!/usr/bin/env python3
import json,statistics,sys,hashlib
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from openclaw_router.experiment_protocol import canonical_dataset,objective_score,OBJECTIVE_FEASIBILITY_THRESHOLD
from openclaw_router.routerbench import _bootstrap_ci,_paired_t_test,_wilcoxon_signed_rank
NEW=Path('/tmp/llmrouter_context_pilot_v2_result.json');OLD=ROOT/'run_logs/formal_100_final_result.json'
OUT=ROOT/'run_logs/context_pilot_v2_analysis.json';MD=ROOT/'run_logs/context_pilot_v2_analysis.md'
def f(x):
 try:return float(x)
 except:return 0.0
def summary(vals):return {'n':len(vals),'mean':round(statistics.mean(vals),4) if vals else None,'exact_rate':round(sum(x>=.999 for x in vals)/len(vals),4) if vals else None,'feasible_rate':round(sum(x>=OBJECTIVE_FEASIBILITY_THRESHOLD for x in vals)/len(vals),4) if vals else None}
def main():
 n=json.loads(NEW.read_text());o=json.loads(OLD.read_text());tasks={x['id']:x for x in n['sampled_task_set']};new=n['raw_model_runs'];ids=set(tasks)
 old=[x for x in o['raw_model_runs'] if x['task_id'] in ids]
 old_by=defaultdict(list)
 for x in old:old_by[(x['task_id'],x['model'])].append(objective_score(tasks[x['task_id']],x.get('response','')))
 old_scores={k:statistics.mean(v) for k,v in old_by.items() if v and all(x is not None for x in v)}
 new_scores={(x['task_id'],x['model']):objective_score(tasks[x['task_id']],x.get('response','')) for x in new}
 new_scores={k:v for k,v in new_scores.items() if v is not None}
 common=sorted(set(old_scores)&set(new_scores));diffs=[f(new_scores[k])-f(old_scores[k]) for k in common];ci=_bootstrap_ci(diffs,samples=2000)
 by_dataset={};by_model={}
 for label,getter,target in [('dataset',lambda x:canonical_dataset(tasks[x['task_id']]),by_dataset),('model',lambda x:x['model'],by_model)]:
  keys=sorted(set(getter(x) for x in new))
  for key in keys:
   nr=[f(new_scores[(x['task_id'],x['model'])]) for x in new if getter(x)==key and (x['task_id'],x['model']) in new_scores]
   ok={(x['task_id'],x['model']) for x in new if getter(x)==key}
   ov=[f(old_scores[k]) for k in ok if k in old_scores]
   target[key]={'new':summary(nr),'old_same_tasks_rescored':summary(ov),'mean_delta':round(statistics.mean(nr)-statistics.mean(ov),4) if nr and ov else None}
 audits=[x.get('prompt_audit') or {} for x in new]
 checks={'all_48_success':len(new)==48 and all(x.get('ok') is True for x in new),'model_counts':dict(Counter(x['model'] for x in new)),'dataset_task_counts':dict(Counter(canonical_dataset(x) for x in tasks.values())),'dataset_run_counts':dict(Counter(canonical_dataset(tasks[x['task_id']]) for x in new)),'all_context_present':all((a.get('context_chars',0)+a.get('table_chars',0)+a.get('evidence_chars',0))>0 for a in audits),'no_context_truncation':all(a.get('context_truncated') is False for a in audits),'no_gold_field_injection':all(a.get('gold_answer_field_injected') is False for a in audits),'prompt_template_versions':dict(Counter(a.get('prompt_template_version') for a in audits)),'answer_format_versions':dict(Counter(a.get('answer_format_version') for a in audits)),'dual_judge_coverage':round(sum(len(x.get('judge_scores') or [])>=2 for x in new)/len(new),4),'final_answer_format_rate':round(sum(('最终答案' in x.get('response','') or 'final answer' in x.get('response','').lower()) for x in new)/len(new),4)}
 answer_cost=sum(f(x.get('raw_cost_usd')) for x in new);judge_cost=sum(f(x.get('judge_cost_usd')) for x in new)
 report={'experiment':'context_fix_validation_v2','excluded_from_final_analysis':True,'signature':n['checkpoint']['signature'],'prompt_protocol':n.get('prompt_protocol'),'checks':checks,'overall':{'paired_n':len(common),'unpaired_new_count':len(new_scores)-len(common),'new_all_48':summary(list(new_scores.values())),'new':summary([f(new_scores[k]) for k in common]),'old_same_tasks_rescored':summary([f(old_scores[k]) for k in common]),'paired_mean_delta':ci['mean'],'bootstrap_ci95':[ci['low'],ci['high']],'paired_t':_paired_t_test(diffs),'wilcoxon':_wilcoxon_signed_rank(diffs)},'by_dataset':by_dataset,'by_model':by_model,'costs':{'answer_usd':round(answer_cost,8),'judge_usd':round(judge_cost,8),'total_usd':round(answer_cost+judge_cost,8)},'gate':{'minimum_overall_feasible_rate':.50,'minimum_finkg_feasible_rate':.50,'requires_no_truncation':True,'requires_no_gold_field_injection':True}}
 report['gate']['passed']=bool(report['overall']['new']['feasible_rate']>=.50 and by_dataset['FinKG']['new']['feasible_rate']>=.50 and checks['no_context_truncation'] and checks['no_gold_field_injection'] and checks['all_48_success'])
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['# Context-grounded v2 修复验证','',f"- 签名：`{report['signature']}`",f"- 48/48成功：{checks['all_48_success']}",f"- 双裁判覆盖：{checks['dual_judge_coverage']:.2%}",f"- 无上下文截断：{checks['no_context_truncation']}",f"- 未注入gold字段：{checks['no_gold_field_injection']}",f"- 旧同题重评分均值：{report['overall']['old_same_tasks_rescored']['mean']}",f"- v2均值：{report['overall']['new']['mean']}",f"- 配对提升：{report['overall']['paired_mean_delta']}，95% CI {report['overall']['bootstrap_ci95']}",f"- 正式重跑门禁：{'PASS' if report['gate']['passed'] else 'FAIL'}",'', '| 数据集 | 旧均值/可行率 | v2均值/可行率 | 均值变化 |','|---|---:|---:|---:|']
 for ds,x in by_dataset.items():lines.append(f"| {ds} | {x['old_same_tasks_rescored']['mean']:.3f}/{x['old_same_tasks_rescored']['feasible_rate']:.1%} | {x['new']['mean']:.3f}/{x['new']['feasible_rate']:.1%} | {x['mean_delta']:+.3f} |")
 MD.write_text('\n'.join(lines)+'\n')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
