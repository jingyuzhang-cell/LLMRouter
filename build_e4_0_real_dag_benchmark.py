#!/usr/bin/env python3
"""Build frozen E4.0 real-task sequential DAG manifest without model calls."""
import hashlib,json
from pathlib import Path
from phase_e4_0.interfaces import DAGNode
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'phase_e4_0'; PILOT=ROOT/'c10_prep/C10_PILOT_60.jsonl'; SOURCE=ROOT/'phase_c9_0/C9_DEV_TASKS.jsonl'; RESERVED=ROOT/'c10_prep/C10_REMAINING_60.jsonl'
MODELS=['deepseek-chat','glm-5.2','qwen-plus','qwen-turbo','gemini-2.5-flash']
NODES=[
 DAGNode('N1','evidence_localization',(),"Locate every passage/table cell needed for QUESTION using only TASK_CONTEXT. Return evidence items with exact quoted text and confidence.",{'evidence_items':'list','confidence':'float'}),
 DAGNode('N2','structured_extraction',('N1',),"Using only N1_EVIDENCE, extract entities, periods, quantities, units, relations, and regulatory facts needed for QUESTION. Mark missing fields; do not perform final reasoning.",{'fields':'object','missing':'list','confidence':'float'}),
 DAGNode('N3','financial_reasoning',('N2',),"Using N2_EXTRACTION and its linked N1 evidence, perform the required financial/regulatory reasoning step by step. Return intermediate result, assumptions, and evidence links; do not write the final response.",{'intermediate_result':'object','assumptions':'list','confidence':'float'}),
 DAGNode('N4','final_synthesis',('N3',),"Synthesize the final answer to QUESTION from N3_REASONING and linked upstream evidence. Do not introduce unsupported facts. Return answer and citations.",{'answer':'string','citations':'list','confidence':'float'})]
def rows(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
pilot=rows(PILOT); source={x['task_id']:x for x in rows(SOURCE)}; reserved_ids={x['task_id'] for x in rows(RESERVED)}; assert len(pilot)==60 and not {x['task_id'] for x in pilot}&reserved_ids
manifest=[]
for p in pilot:
 t=source[p['task_id']]
 nodes=[{'node_id':n.node_id,'node_type':n.node_type,'depends_on':list(n.depends_on),'prompt_template':n.prompt_template,'output_schema':n.output_schema} for n in NODES]
 manifest.append({'task_id':p['task_id'],'source_dataset':t['source_dataset'],'source_document_id':t.get('source_document_id'),'question_sha256':hashlib.sha256(t['question'].encode()).hexdigest(),'context_sha256':hashlib.sha256(t['context'].encode()).hexdigest(),'observable_features':t['observable_features'],'models':MODELS,'nodes':nodes,'reference_in_manifest':False})
path=OUT/'E4_0_DAG_MANIFEST.jsonl'; path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in manifest))
report={'status':'E4_0_BENCHMARK_PREPARED','tasks':len(manifest),'nodes':sum(len(x['nodes']) for x in manifest),'edges':sum(sum(len(n['depends_on']) for n in x['nodes']) for x in manifest),'reserved_holdout_accessed':False,'reference_answers_in_manifest':False,'external_api_calls':0,'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'pilot_sha256':hashlib.sha256(PILOT.read_bytes()).hexdigest(),'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
(OUT/'E4_0_PREPARATION_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
