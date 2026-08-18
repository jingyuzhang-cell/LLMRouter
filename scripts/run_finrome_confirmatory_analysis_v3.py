#!/usr/bin/env python3
"""Freeze development settings and evaluate Fin-RoME confirmatory v3 once."""
from __future__ import annotations
import argparse, hashlib, json, os, random
from pathlib import Path
import torch

ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/'data/finance_router/finrome_300'
CONF=ROOT/'data/finance_router/finrome_300_confirmatory_v3'
DEV_RUN=ROOT/'run_logs/finrome_300'
OUT=ROOT/'run_logs/finrome_300_confirmatory_v3'
SEED=20260814

def rows(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')

def prepare():
 OUT.mkdir(parents=True,exist_ok=True)
 tuning=DEV_RUN/'exploratory_v2/tuning/report.json';m3=DEV_RUN/'exploratory_v2/m3_m5/report.json'
 selected=json.loads(tuning.read_text())
 assert selected['report_type']=='oof_gated_convex_residual_meta_v2'
 assert selected['selected_global_weights']==[1.0,0.0,0.0] and not selected['oof_gate_passed']
 dev_tasks=rows(DEV/'tasks.jsonl');ids=sorted(x['id'] for x in dev_tasks);random.Random(SEED).shuffle(ids)
 split={'train':sorted(ids[:240]),'validation':sorted(ids[240:]),'test':sorted(x['id'] for x in rows(CONF/'tasks.jsonl'))}
 dump(OUT/'split.json',split)
 freeze={'status':'FROZEN_BEFORE_CONFIRMATORY_OUTCOME_READ','seed':SEED,'development_split':{'train':240,'calibration':60},'confirmatory_test':300,'policies':['weighted_M1_v2','M3_v2','M5_legacy_v1','M5_sparse_v2'],'selected_global_weights':selected['selected_global_weights'],'selected_graph':selected['selected_graph'],'selected_meta_policy':selected['selected_meta_policy'],'m3_development_gate':json.loads(m3.read_text())['M3_calibration_gate'],'hashes':{'development_tasks':sha(DEV/'tasks.jsonl'),'development_matrix':sha(DEV/'utility_matrix.jsonl'),'tuning_report':sha(tuning),'m3_m5_report':sha(m3),'confirmatory_tasks':sha(CONF/'tasks.jsonl'),'confirmatory_matrix':sha(CONF/'utility_matrix.jsonl'),'split':sha(OUT/'split.json')}}
 dump(OUT/'FROZEN_POLICY.json',freeze)
 # Query-only embeddings may be prepared without reading confirmatory outcomes.
 emb_path=OUT/'combined_embeddings.pt'
 if not emb_path.exists():
  old=torch.load(DEV_RUN/'longformer_embeddings.pt',map_location='cpu',weights_only=False);emap={t:old['embeddings'][i] for i,t in enumerate(old['task_ids'])}
  from llmrouter.utils.embeddings import get_longformer_embedding
  conf_tasks=rows(CONF/'tasks.jsonl')
  for i in range(0,len(conf_tasks),4):
   batch=conf_tasks[i:i+4];z=get_longformer_embedding([x.get('question','') for x in batch]).cpu()
   for j,x in enumerate(batch):emap[x['id']]=z[j]
  all_ids=[x['id'] for x in dev_tasks]+[x['id'] for x in conf_tasks]
  torch.save({'task_ids':all_ids,'embeddings':torch.stack([emap[x] for x in all_ids]),'model':'allenai/longformer-base-4096'},emb_path)
 return freeze

def build_source():
 dev=json.loads((DEV_RUN/'source_compat.json').read_text());tasks=list(dev['sampled_task_set']);raw=list(dev['raw_model_runs'])
 ct=rows(CONF/'tasks.jsonl');matrix={(x['task_id'],x['model']):x for x in rows(CONF/'utility_matrix.jsonl')};resp={}
 for x in rows(CONF/'responses.jsonl'):resp[(x['task_id'],x['model'],x['repeat'])]=x
 for x in ct:
  y=dict(x);y['query']=y.get('question','');y['risk']=.86 if y.get('risk_level')=='high' else .62;tasks.append(y)
  for model in ('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo'):
   m=matrix[(x['id'],model)]
   for repeat in range(3):
    r=resp[(x['id'],model,repeat)];raw.append({'task_id':x['id'],'model':model,'repeat':repeat,'ok':bool(r.get('success')),'quality':m['quality'],'raw_cost_usd':m['cost_usd'],'latency_ms':m['latency_ms'],'response':r.get('answer','')})
 p=OUT/'combined_source.json';p.write_text(json.dumps({'sampled_task_set':tasks,'raw_model_runs':raw},ensure_ascii=False)+'\n');return p

def execute():
 if (OUT/'CONFIRMATORY_COMPLETE.json').exists():raise SystemExit('Confirmatory analysis already complete; refusing to reread outcomes.')
 freeze=json.loads((OUT/'FROZEN_POLICY.json').read_text());assert freeze['status']=='FROZEN_BEFORE_CONFIRMATORY_OUTCOME_READ'
 source=build_source()
 import scripts.run_finrome_formal_oof as b
 import scripts.tune_finrome_oof as t
 import scripts.run_finrome_m3_m5 as m
 b.SOURCE=source;b.SPLIT=OUT/'split.json';b.EMB=OUT/'combined_embeddings.pt'
 t.OUT=DEV_RUN/'exploratory_v2/tuning'
 outputs={}
 for policy,name in [('legacy_v1','m5_legacy_v1'),('sparse_v2','m5_sparse_v2')]:
  os.environ['FINROME_M5_ANCHOR_POLICY']=policy;m.OUT=OUT/name;m.OUT.mkdir(parents=True,exist_ok=True);m.main();outputs[name]=sha(m.OUT/'report.json')
 dump(OUT/'CONFIRMATORY_COMPLETE.json',{'status':'COMPLETE_TEST_READ_ONCE','frozen_policy_sha256':sha(OUT/'FROZEN_POLICY.json'),'confirmatory_matrix_sha256':sha(CONF/'utility_matrix.jsonl'),'outputs':outputs,'human_review':'PENDING only'})

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--freeze-only',action='store_true');a=p.parse_args();prepare()
 if not a.freeze_only:execute()
