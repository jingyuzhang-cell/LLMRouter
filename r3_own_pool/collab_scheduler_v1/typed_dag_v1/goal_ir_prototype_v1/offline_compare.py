"""Synthetic offline comparison. No inference services or real tasks."""
import json,hashlib,shutil
from pathlib import Path
from collab_scheduler_v1.typed_dag_v1.test_goal_ir import ir,IRLoopTests
from collab_scheduler_v1.typed_dag_v1.test_producer_plan import producers
from collab_scheduler_v1.typed_dag_v1.test_semantic_ids import CTX
from collab_scheduler_v1.typed_dag_v1.generation import InitialDAGGenerator
from collab_scheduler_v1.typed_dag_v1.goal_ir import goal_ir_schema
from collab_scheduler_v1.typed_dag_v1.heterogeneous_models import allocate
from collab_scheduler_v1.typed_dag_v1.producer_plan import compile_producer_plan
from collab_scheduler_v1.typed_dag_v1.semantic_validation import inspect_semantic_plan,SemanticErrors
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
rows=[]
for mode in ('semantic','goal_ir'):
    for size in (3,5):
        fixture=IRLoopTests('test_ir_three_five_metered_execution')
        candidate=ir(size) if mode=='goal_ir' else producers(size)
        fixture.candidates=iter([candidate]);ex=fixture.executor(fixture.dispatch_ir)
        try:
            g,r=InitialDAGGenerator(ex,'medium',planning_mode=mode).generate_and_execute('offline-'+mode+str(size),'financial_arithmetic',CTX,{'answer':'sum'},lambda graph:allocate(graph,ex.bindings)['assignment'])
            target=ROOT/(mode+'_'+str(size));target.mkdir(exist_ok=True)
            for source in ex.directory.glob('*.jsonl'):shutil.copyfile(source,target/source.name)
            (target/'INPUT_PLAN.json').write_text(json.dumps(candidate,indent=2)+'\n')
            rows.append(dict(mode=mode,size=size,status=g.status,execution=r['status'],answer=r['final_outputs'].get('answer'),graph=g.graph.to_dict(),accounting=r['pipeline_accounting'],search_spend=r['search_spend'],value_lineage=r['value_lineage'],claim='hand-authored Stub plan, NOT real LLM generation'))
        finally:fixture.doCleanups()
history=[]
for i in range(1,5):
    path=BASE/'stage3_heterogeneous_real_01'/f'RESPONSE_{i:02}_PARSED.json'
    p=json.loads(path.read_text())
    try:q,_=compile_producer_plan(p);es=inspect_semantic_plan(q)
    except SemanticErrors as e:es=e.feedback['errors']
    history.append(dict(source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),legacy_errors=es,ir_conversion_attempted=False,reason='Different planning protocol; assigning data symbols and intended operations needs replanning, not automatic laundering'))
(ROOT/'SCHEMA.json').write_text(json.dumps(goal_ir_schema(),indent=2)+'\n')
(ROOT/'OFFLINE_EVIDENCE.json').write_text(json.dumps(dict(role='offline prototype feasibility, no algorithm superiority claim',real_requests=0,stub_runs=rows,historical_replay=history,source_hashes={name:hashlib.sha256((BASE/name).read_bytes()).hexdigest() for name in ('goal_ir.py','generation.py','test_goal_ir.py')}),indent=2)+'\n')
print(json.dumps(dict(stub_complete=sum(r['execution']=='COMPLETE' for r in rows),runs=len(rows),real_requests=0)))
