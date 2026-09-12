"""Collect only locally selected frozen-route alternatives."""
import argparse,json
from pathlib import Path
from .data import load_cohort,read_rows,sha
from . import collect_repeat_compatibility_115 as collector
ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'router_v2/ridge_confirmation_100';OUT=ROOT/'data/ridge_confirmation_100_selected'
MODELS={'medium':collector.MODELS['medium'],'large':{'repo':'Qwen/Qwen2.5-14B-Instruct','revision':'official-gptq-int8-repository-state-recorded-in-manifest','path':Path('/root/autodl-tmp/models/Qwen2.5-14B-Instruct-GPTQ-Int8')}}

def prepare():
 protocol=json.loads((FROZEN/'PROTOCOL.json').read_text())
 if sha(FROZEN/'PANEL.jsonl')!=protocol['source_sha256']['panel'] or sha(FROZEN/'FROZEN_DECISIONS.jsonl')!=protocol['source_sha256']['decisions']:raise ValueError('Frozen files changed')
 panel={r['query_id']:r for r in read_rows(FROZEN/'PANEL.jsonl')};decisions=read_rows(FROZEN/'FROZEN_DECISIONS.jsonl');OUT.mkdir(parents=True,exist_ok=True);result={}
 for slot in ['medium','large']:
  rows=[panel[d['query_id']] for d in decisions if d['choice_slot']==slot];path=FROZEN/f'PANEL_{slot}.jsonl';content=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
  if path.exists() and path.read_text()!=content:raise ValueError('Derived panel changed')
  path.write_text(content);result[slot]=path
 manifest={'frozen_protocol_sha256':sha(FROZEN/'PROTOCOL.json'),'decisions_sha256':sha(FROZEN/'FROZEN_DECISIONS.jsonl'),'derived_panels':{s:{'n':len(read_rows(p)),'sha256':sha(p)} for s,p in result.items()}}
 (FROZEN/'SELECTED_COLLECTION_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n');return result

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--slot',choices=['medium','large'],required=True);a=ap.parse_args();paths=prepare();cohort,split=load_cohort(ROOT/'data/cohort_full_v2');rows=read_rows(paths[a.slot]);panel={r['query_id']:{**r,'ground_truth':cohort[r['query_id']]['ground_truth']} for r in rows};collector.OUT=OUT;collector.MODELS[a.slot]=MODELS[a.slot];collector.collect(a.slot,panel,cohort)
if __name__=='__main__':main()
