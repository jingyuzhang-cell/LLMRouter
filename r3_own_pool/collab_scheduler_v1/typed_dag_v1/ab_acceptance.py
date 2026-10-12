"""Frozen A/B dispatcher. Preparation is offline; --execute needs new approval.

Each arm runs existing fresh_acceptance with its own ScopedBudget and cache.
No shared inference service, no cross-arm quota loans, no retries/resume.
"""
import argparse,hashlib,json,subprocess,sys,time,signal
from pathlib import Path
from .protocol import digest
from .resource_envelope import ResourceEnvelope,StageBound
from .heterogeneous_models import heterogeneous_wall_preflight

MODES={'A':'semantic','B':'goal_ir'}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def preflight(packet):
    packet=Path(packet);protocol=json.loads((packet/'PROTOCOL.json').read_text())
    for filename,expected in protocol['file_sha256'].items():
        if sha(packet/filename)!=expected:raise ValueError('Frozen input hash mismatch: '+filename)
    for filename,expected in protocol['source_sha256'].items():
        if sha(filename)!=expected:raise ValueError('Frozen source hash mismatch: '+filename)
    manifest=json.loads((packet/'TASK_MANIFEST.json').read_text())
    if len(manifest['tasks'])!=4 or len({t['task_id'] for t in manifest['tasks']})!=4:raise ValueError('Four unique tasks required')
    if sha(packet/'EVALUATION_ONLY.json')!=manifest['evaluation_only_sha256']:raise ValueError('Evaluation hash mismatch')
    for task in manifest['tasks']:
        if set(task)!={'task_id','domain','context','required_outputs'} or set(task['context'])!={'question','ctx_table','ctx_text'} or digest(task)!=manifest['content_sha256'][task['task_id']]:raise ValueError('Public input mismatch or forbidden fields')
    totals=[]
    for arm in MODES:
        plan=json.loads((packet/f'BUDGET_{arm}.json').read_text());e=ResourceEnvelope(stages={k:StageBound(**v) for k,v in plan['stages'].items()},phase_tokens=plan['phase_tokens']);t=e.admit([x['task_id'] for x in manifest['tasks']],plan['caps'])
        wall=heterogeneous_wall_preflight(e,4,plan['caps']['wall_seconds']-960)
        totals.append(dict(arm=arm,per_task=t,stage_a_reserved_s=960,stage_b_wall=wall))
    if json.loads((packet/'BUDGET_A.json').read_text())!=json.loads((packet/'BUDGET_B.json').read_text()):raise ValueError('Unequal arm resources')
    return dict(status='PASS',arms=totals,real_calls=0,execution_authorized=False)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--packet',required=True);ap.add_argument('--output');ap.add_argument('--execute',action='store_true');args=ap.parse_args();packet=Path(args.packet)
    checked=preflight(packet)
    if not args.execute:print(json.dumps(checked,indent=2));return 0
    if not args.output:raise ValueError('--output required')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False);protocol=json.loads((packet/'PROTOCOL.json').read_text());started=time.monotonic();rows=[]
    # No automatic continuation/retry. Per-arm hard budgets stay independent.
    for arm in protocol['arm_order']:
        preflight(packet)
        if protocol['global_wall_seconds']-(time.monotonic()-started)<12000+60:raise RuntimeError('Global wall cannot cover next full independent arm')
        command=[sys.executable,'-u','-m','collab_scheduler_v1.typed_dag_v1.fresh_acceptance','--manifest',str(packet/'TASK_MANIFEST.json'),'--evaluation',str(packet/'EVALUATION_ONLY.json'),'--budget-plan',str(packet/f'BUDGET_{arm}.json'),'--planning-mode',MODES[arm],'--allocation-policy','heterogeneous_type_baseline','--output',str(out/arm),'--execute']
        with (out/f'{arm}.log').open('w') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            try:code=child.wait(timeout=min(12030,protocol['global_wall_seconds']-(time.monotonic()-started)-30))
            except subprocess.TimeoutExpired:
                child.send_signal(signal.SIGINT);code=child.wait(timeout=30)
        result=json.loads((out/arm/'RESULTS.json').read_text()) if (out/arm/'RESULTS.json').exists() else {'abort':'Missing terminal results; usage UNKNOWN'}
        rows.append(dict(arm=arm,returncode=code,result=result));(out/'AB_RESULTS.json').write_text(json.dumps(dict(arms=rows,wall_s=time.monotonic()-started),indent=2))
        if code or result.get('abort'):return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
