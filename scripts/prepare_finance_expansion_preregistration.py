#!/usr/bin/env python3
"""Prepare a no-API 40-task expansion and freeze the split before outcomes exist."""
from __future__ import annotations
import hashlib,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from sklearn.model_selection import train_test_split
from scripts.build_finance_experiment_sample import finqa_records,tatqa_records,obliqa_records,finreflect_records,stratified_sample

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/finance_router/frozen/v1/finance_benchmark_v1.jsonl';ARCHIVE=ROOT.parents[1]/'frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z';RESULT=ARCHIVE/'run_logs/formal_context_v2_rescored_v22_result.json';OUT=ROOT/'run_logs/finance_expansion_preregistration';SEED=20260730

def read_jsonl(path):return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def normalize(x):return str(x).removeprefix('finance_dataset_')

def choose(records,exclude,size,seed):return stratified_sample([x for x in records if x['id'] not in exclude],size,seed)

def fixed_split(records):
 counts=Counter(x['dataset'] for x in records);dataset={x['id']:x['dataset'] for x in records}
 rare=sorted(x['id'] for x in records if counts[x['dataset']]<3);common=sorted(x['id'] for x in records if counts[x['dataset']]>=3)
 trainval,test=train_test_split(common,test_size=28,random_state=SEED,stratify=[dataset[x] for x in common])
 train,validation=train_test_split(trainval,test_size=28,random_state=SEED,stratify=[dataset[x] for x in trainval]);train=list(train)+rare
 assert [len(train),len(validation),len(test)]==[84,28,28]
 assert set(train).isdisjoint(validation) and set(train).isdisjoint(test) and set(validation).isdisjoint(test)
 assert set(train)|set(validation)|set(test)=={x['id'] for x in records}
 return {'train':sorted(train),'validation':sorted(validation),'test':sorted(test)}

def main():
 OUT.mkdir(parents=True,exist_ok=True);pool=read_jsonl(BASE);result=json.loads(RESULT.read_text());used={normalize(x['id']) for x in result['sampled_task_set']};base=[x for x in pool if x['id'] in used];base_ids={x['id'] for x in pool};exclude=used|base_ids
 assert len(base)==100
 candidates=[]
 for i,(name,loader) in enumerate((('FinQA',finqa_records),('TAT-QA',tatqa_records),('ObliQA',obliqa_records),('FinReflectKG-EvalBench-derived',finreflect_records))):candidates+=choose(loader(),exclude,10,SEED+i)
 assert len(candidates)==40 and not ({x['id'] for x in candidates}&base_ids)
 combined=base+candidates;split=fixed_split(combined);coverage={normalize(r['task_id']) for r in result['raw_model_runs']};covered=sum(x['id'] in coverage for x in candidates)
 full=OUT/'candidate_tasks.local.jsonl';full.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in candidates))
 manifest={'version':1,'created_at':datetime.now(timezone.utc).isoformat(),'status':'preregistered_no_api_calls','selection_seed':SEED,'base_tasks':len(base),'new_tasks':len(candidates),'combined_tasks':len(combined),'candidate_counts':dict(Counter(x['dataset'] for x in candidates)),'combined_counts':dict(Counter(x['dataset'] for x in combined)),'candidate_ids':[x['id'] for x in candidates],'existing_four_model_answer_coverage':covered,'label_diversity_assessment':{'empirical_possible':False,'reason':'No frozen four-model answers exist for any candidate; model-optimal labels cannot be inferred from task text without contaminating the evaluation.','proxy_change':'Adds 10 unseen tasks from each of FinQA, TAT-QA, ObliQA, and FinReflectKG; high-risk audit/KG tasks increase structural diversity but do not guarantee GLM-optimal labels.'},'required_new_calls':{'answer_calls':40*4*3,'minimum_judge_attempts_if_two_per_answer':40*4*3*2,'api_execution_authorized':False},'source_sha256':{'base':sha(BASE),'frozen_result':sha(RESULT)},'candidate_file':str(full.relative_to(ROOT))}
 protocol={'protocol_version':'finance-expansion-v1-preregistered','frozen_before_answers':True,'seed':SEED,'combined_task_count':140,'split_counts':{k:len(v) for k,v in split.items()},'split_task_ids':split,'models':['deepseek-chat','glm-5.2','qwen-plus','qwen-turbo'],'repeats':3,'scorer':'objective_scorer_v2.2','primary_analysis':'one fixed split only; no reseeding after outcomes','rare_label_rule':'do not duplicate rare labels; disclose unsupported class recall','stopping_rule':'complete exactly 480 new answer calls or cancel the extension without merging partial results','data_isolation':'existing 1200 responses and final archive remain immutable; extension uses a new checkpoint, result file and archive','routerdc':'deferred'}
 (OUT/'candidate_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');(OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
 lines=['# 金融任务扩展离线预注册','',f"- 状态：{manifest['status']}",f"- 原任务/新增/合计：{len(base)}/{len(candidates)}/{len(combined)}",f"- 新增分布：{manifest['candidate_counts']}",f"- 固定划分：{protocol['split_counts']}",f"- 新任务已有四模型回答：{covered}/40",f"- 若执行需新增回答调用：{manifest['required_new_calls']['answer_calls']}；最低双 Judge 尝试：{manifest['required_new_calls']['minimum_judge_attempts_if_two_per_answer']}",'- 当前不允许 API 执行；不能仅凭任务文本声称 GLM 最优标签增加。','- 40 个任务在答案生成前已锁定；后续不得根据结果换题或换划分。','- 完整候选内容保存在 local JSONL，不进入 Git。']
 (OUT/'report.md').write_text('\n'.join(lines)+'\n');print(json.dumps({'manifest':manifest,'protocol_counts':protocol['split_counts']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
