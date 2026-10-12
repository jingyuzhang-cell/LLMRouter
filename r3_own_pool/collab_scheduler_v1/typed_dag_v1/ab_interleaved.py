"""Eight frozen independent cells in alternating task order; offline by default."""
import argparse,json,subprocess,sys,time,signal
from pathlib import Path
from .ab_acceptance import preflight,MODES
from .service_schema import backend_precheck,to_service_schema
from .resource_envelope import ResourceEnvelope,StageBound
from .heterogeneous_models import heterogeneous_wall_preflight

def check(packet):
    packet=Path(packet);result=preflight(packet);p=json.loads((packet/'PROTOCOL.json').read_text());plan=json.loads((packet/'BUDGET_CELL.json').read_text())
    e=ResourceEnvelope(stages={k:StageBound(**v) for k,v in plan['stages'].items()},phase_tokens=plan['phase_tokens']);e.admit(['cell'],plan['caps']);heterogeneous_wall_preflight(e,1,plan['caps']['wall_seconds']-960)
    for arm in MODES:
        full=json.loads((packet/f'SCHEMA_{arm}.json').read_text());service,audit=to_service_schema(full);backend=backend_precheck(service)
        if backend['vllm']!=p['service_versions']['vllm'] or backend['xgrammar']!=p['service_versions']['xgrammar']:raise ValueError('Service version mismatch')
    expected=[(i,a) for i in range(4) for a in (('A','B') if i%2==0 else ('B','A'))]
    if [(c['task_index'],c['arm']) for c in p['cells']]!=expected:raise ValueError('Interleaved order mismatch')
    for cell in p['cells']:
        m=json.loads((packet/cell['manifest']).read_text());parent=json.loads((packet/'TASK_MANIFEST.json').read_text())
        if m['tasks']!=[parent['tasks'][cell['task_index']]]:raise ValueError('Cell task mismatch')
    if plan['caps']['new_request_attempts']*4!=48 or plan['caps']['new_total_tokens']*4!=136000:raise ValueError('Independent quota mismatch')
    return dict(**result,cells=8,service_precheck='PASS',cell_wall_s=plan['caps']['wall_seconds'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--packet',required=True);ap.add_argument('--output');ap.add_argument('--execute',action='store_true');args=ap.parse_args();packet=Path(args.packet);checked=check(packet)
    if not args.execute:print(json.dumps(checked,indent=2));return 0
    if not args.output:raise ValueError('Output required')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False);p=json.loads((packet/'PROTOCOL.json').read_text());started=time.monotonic();rows=[]
    for cell in p['cells']:
        check(packet)
        remaining=p['global_wall_seconds']-(time.monotonic()-started)
        if remaining<4030:raise RuntimeError('Insufficient global wall for complete next cell')
        label=cell['label'];command=[sys.executable,'-u','-m','collab_scheduler_v1.typed_dag_v1.fresh_acceptance','--manifest',str(packet/cell['manifest']),'--evaluation',str(packet/'EVALUATION_ONLY.json'),'--budget-plan',str(packet/'BUDGET_CELL.json'),'--planning-mode',MODES[cell['arm']],'--output',str(out/label),'--execute']
        with (out/(label+'.log')).open('w') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            try:code=child.wait(timeout=min(4030,remaining-30))
            except subprocess.TimeoutExpired:child.send_signal(signal.SIGINT);code=child.wait(timeout=30)
        r=json.loads((out/label/'RESULTS.json').read_text()) if (out/label/'RESULTS.json').exists() else dict(abort='Unknown terminal and usage; do not settle as zero')
        rows.append(dict(**cell,returncode=code,result=r));(out/'AB_RESULTS.json').write_text(json.dumps(dict(cells=rows,wall_s=time.monotonic()-started),indent=2))
        if code or r.get('abort'):return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
