#!/usr/bin/env python3
"""Assess GraphRouter/RouterDC readiness and create a named-review worksheet."""
from __future__ import annotations
import csv,hashlib,json,platform
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import torch

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT.parents[1]/'frozen-archives/finance-router-context-v2-1200-final-20260729T072524Z'
SOURCE=ARCHIVE/'run_logs/formal_context_v2_rescored_v22_result.json'
OUT_JSON=ROOT/'run_logs/router_training_cost_audit.json';OUT_MD=ROOT/'run_logs/router_training_cost_audit.md';OUT_CSV=ROOT/'run_logs/judge_disagreement_named_review.csv'

def count_lines(path):return sum(1 for x in path.read_text(encoding='utf-8').splitlines() if x.strip()) if path.exists() else 0

def main():
 d=json.loads(SOURCE.read_text());raw=d['raw_model_runs'];tasks={x['id']:x for x in d['sampled_task_set']}
 weight=ROOT/'saved_models/graphrouter/graphrouter.pt';train=ROOT/'data/example_data/routing_data/multi_provider_graph_train.jsonl';embed=ROOT/'run_logs/offline_knn_baseline/longformer_embeddings.pt'
 state=torch.load(weight,map_location='cpu',weights_only=False) if weight.exists() else {};tensors=[x for x in state.values() if isinstance(x,torch.Tensor)] if isinstance(state,dict) else []
 graph={'implementation_present':(ROOT/'llmrouter/models/graphrouter/router.py').exists(),'torch_geometric_version':getattr(__import__('torch_geometric'),'__version__',None),'demo_weight_present':weight.exists(),'demo_weight_bytes':weight.stat().st_size if weight.exists() else 0,'demo_parameter_count':sum(x.numel() for x in tensors),'demo_training_rows':count_lines(train),'financial_embeddings_ready':embed.exists(),'financial_embedding_bytes':embed.stat().st_size if embed.exists() else 0,'financial_routing_rows_required':400,'configured_epochs':30,'readiness':'Code and dependencies are ready. Demo weights are incompatible with the 100-task/4-model financial label space; a new leakage-safe graph dataset and training run are required.','cost_assessment':'No API cost and the 100 Longformer embeddings can be reused. Expected compute is a small 30-epoch GNN run; measured wall time is deferred until leakage-safe graph edges are built.'}
 dc=ROOT/'llmrouter/models/dcrouter';dc_weights=list((ROOT/'saved_models').glob('**/*dcrouter*'))
 routerdc={'implementation_present':dc.exists(),'config_present':any((ROOT/'configs').glob('**/*dcrouter*')),'weights_present':bool(dc_weights),'deberta_cache_present':any(Path('/root/.cache/huggingface/hub').glob('models--*deberta*')),'readiness':'Blocked: no RouterDC implementation, config, weights, or cached DeBERTa checkpoint in this checkout.','cost_assessment':'A defensible measured cost is impossible here. Importing and pinning RouterDC plus its encoder may require network access and substantially more GPU memory/time than KNN.'}
 rows=[]
 for r in raw:
  if float(r.get('judge_disagreement') or 0)<.20-1e-12:continue
  t=tasks[r['task_id']];scores=';'.join(f"{x.get('model')}={x.get('score')}" for x in r.get('judge_scores') or [])
  rows.append({'priority':round(float(r.get('judge_disagreement') or 0),3),'task_id':r['task_id'],'dataset':t.get('dataset'),'candidate_model':r.get('model'),'repeat':r.get('repeat'),'query':str(t.get('query') or '').replace('\n',' '),'reference_answer':str(t.get('gold_answer') or '').replace('\n',' '),'candidate_response':str(r.get('response') or '').replace('\n',' '),'objective_score':r.get('objective_score'),'final_quality':r.get('quality'),'judge_scores':scores,'judge_disagreement':r.get('judge_disagreement'),'reviewer_identity':'','reviewed_at_utc':'','verdict':'','adjudicated_score':'','reviewer_notes':''})
 rows.sort(key=lambda x:(-x['priority'],x['task_id'],x['candidate_model'],x['repeat']))
 with OUT_CSV.open('w',encoding='utf-8-sig',newline='') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 report={'report_type':'router_training_cost_and_named_review','generated_at':datetime.now(timezone.utc).isoformat(),'offline_only':True,'api_calls':0,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'environment':{'python':platform.python_version(),'torch':torch.__version__,'cuda_available':torch.cuda.is_available(),'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},'graphrouter':graph,'routerdc':routerdc,'named_manual_review':{'rows':len(rows),'by_model':dict(Counter(x['candidate_model'] for x in rows)),'by_dataset':dict(Counter(str(x['dataset']) for x in rows)),'worksheet':str(OUT_CSV.relative_to(ROOT)),'reviewer_identity_required':True,'completed_rows':0,'status':'awaiting human adjudication'}}
 OUT_JSON.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 lines=['# GraphRouter / RouterDC 训练成本与实名裁决准备','',f"- API 调用：0",f"- GPU：{report['environment']['gpu']}",'','## GraphRouter','',f"- 实现/依赖：{graph['implementation_present']} / torch-geometric {graph['torch_geometric_version']}",f"- demo 权重：{graph['demo_weight_bytes']} bytes，{graph['demo_parameter_count']} parameters；demo 训练行：{graph['demo_training_rows']}",f"- 金融嵌入已就绪：{graph['financial_embeddings_ready']}；需构建 400 条任务—模型边。",f"- 结论：{graph['readiness']}",f"- 成本：{graph['cost_assessment']}",'','## RouterDC','',f"- 实现/配置/权重：{routerdc['implementation_present']}/{routerdc['config_present']}/{routerdc['weights_present']}",f"- 结论：{routerdc['readiness']}",f"- 成本：{routerdc['cost_assessment']}",'','## 高分歧实名人工裁决','',f"- 待裁决：{len(rows)} 条。",f"- 按模型：{report['named_manual_review']['by_model']}",f"- 工作表：`{OUT_CSV.relative_to(ROOT)}`",'- 必填：reviewer_identity、reviewed_at_utc、verdict、adjudicated_score、reviewer_notes。','- 当前 completed_rows=0；未经真实人员签名，不得标记为人工裁决完成。']
 OUT_MD.write_text('\n'.join(lines)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
