"""Shadow adaptation of saved runs; writes only this new analysis directory."""
import json,hashlib,sys
from pathlib import Path
from collections import Counter
from adapter import adapt,project_slots
ROOT=Path(__file__).resolve().parent
OLD=Path('/root/research_outputs/mvr_batch1')
BASE=Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence')
SCORER=Path('/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
sys.path.insert(0,str(SCORER))
from terminal_quality import evaluate_terminal_quality

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
paths={'MVR1':BASE/'MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json','MVR2':BASE/'MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json'}
protected=[OLD/'pairs.jsonl',OLD/'runner.py',OLD/'reevaluate.py',OLD/'final_report.json',SCORER/'terminal_quality.py',*paths.values()]
before={str(p):sha(p) for p in protected}
contracts={t:json.loads(p.read_text()) for t,p in paths.items()}
rows=[];counts=Counter()
for line in (OLD/'pairs.jsonl').read_text().splitlines():
 pair=json.loads(line);tid=pair['task'];contract=contracts[tid]
 # Adapter gets only public schemas and documents, never reference values.
 slots=project_slots(contract['required_facts']);sources=contract['source_pages']
 for arm,a in pair['arms'].items():
  terminal,issues=adapt(a['terminal'],slots,sources)
  assert [x['value'] for x in terminal['claims']]==[x['value'] for x in a['terminal']['claims']]
  for issue in issues:counts[issue.get('citation_result',issue.get('reason'))]+=1
  view={k:v for k,v in contract.items() if k!='source_pages'}
  score=evaluate_terminal_quality(view,terminal,sources)
  rows.append({'task':tid,'pair':pair['pair'],'arm':arm,
    'historical_online_f1':a['eval']['fact_metrics']['f1'],
    'shadow_fact_metrics':score['fact_metrics'],'shadow_gate':score['critical_gate'],
    'shadow_Q_final':score['Q_final'],'blocking':score['blocking_reasons'],
    'terminal':terminal,'adapter_issues':issues,'model_values_unchanged':True})
assert before=={str(p):sha(p) for p in protected}
result={'evidence':'POST_HOC_SHADOW_ADAPTER_CHECK_NOT_NEW_EXPERIMENT','rows':rows,
 'source_hashes':before,'original_files_unchanged':True,'citation_diagnostics':dict(counts),
 'new_model_calls':0,'gold_or_protocol_adjudication':'NOT_PERFORMED',
 'limitations':['Supplies only declared task slot metadata, never fills model values',
 'Exact full quote with whitespace normalization and unique location; no prefix guessing or quote expansion',
 'Source raw hashes copied from existing manifest; page text hashes recomputed',
 'Existing reference exposure/quality limitations remain; this is not an independent Q claim']}
(ROOT/'SHADOW_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({'runs':len(rows),'nonzero_shadow_f1':sum(x['shadow_fact_metrics']['f1']>0 for x in rows),'gates':dict(Counter(x['shadow_gate']['status'] for x in rows)),'citations':dict(counts),'original_files_unchanged':True},ensure_ascii=False))
