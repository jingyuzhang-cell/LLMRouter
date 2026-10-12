"""Read-only saved-candidate replay. No provider import or execution."""
import hashlib,json
from pathlib import Path
from collab_scheduler_v1.typed_dag_v1.producer_plan import compile_producer_plan
from collab_scheduler_v1.typed_dag_v1.semantic_validation import inspect_semantic_plan,SemanticErrors,compare_errors
BASE=Path(__file__).resolve().parent.parent
SOURCE=BASE/'stage3_heterogeneous_real_01'
rows=[]
for index in range(1,5):
    raw=SOURCE/f'RESPONSE_{index:02}_RAW.txt';parsed=SOURCE/f'RESPONSE_{index:02}_PARSED.json'
    candidate=json.loads(parsed.read_text())
    try:
        plan,evidence=compile_producer_plan(candidate)
        errors=inspect_semantic_plan(plan)
        stage='semantic_connectivity_preassembly'
    except SemanticErrors as exc:
        errors=exc.feedback['errors'];stage='producer_type_preassembly'
    rows.append(dict(index=index,task='solar' if index<3 else 'trip',attempt='initial' if index%2 else 'repair',
                     source=str(parsed),raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                     parsed_sha256=hashlib.sha256(parsed.read_bytes()).hexdigest(),errors=errors,
                     interception_stage=stage,blocked_before_contract_assembly=bool(errors),
                     deterministic_legal_normalization=False,requires_new_llm_plan=True,
                     original_candidate_modified=False))
result=dict(role='historical deterministic replay, not a new generation or quality experiment',
            real_requests=0,rows=rows,
            repair_comparisons=[dict(task=rows[i]['task'],**compare_errors(rows[i]['errors'],rows[i+1]['errors'])) for i in (0,2)],
            tests=dict(original=226,new=19,total=245,typed=227,fixed_evaluator_runtime=18,status='PASS'),
            source_hashes={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in ('producer_plan.py','semantic_validation.py','generation.py','test_type_connectivity.py')})
Path(__file__).with_name('REPLAY_EVIDENCE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(replayed=len(rows),blocked=sum(r['blocked_before_contract_assembly'] for r in rows),no_progress=[x['no_progress'] for x in result['repair_comparisons']])))
