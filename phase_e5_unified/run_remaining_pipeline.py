"""Continue after collection, fail closed on budget or missing labels; no hidden agent."""
import fcntl,hashlib,json,subprocess,sys,time
from pathlib import Path
ROOT=Path('/root');OUT=ROOT/'phase_e5_unified'
def dump(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def run(script,*args):
 with (OUT/(Path(script).stem+'_'+('_'.join(args) or 'run')+'.log')).open('a') as log:
  r=subprocess.run([sys.executable,str(ROOT/script),*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError(f'{script} {args} stopped; see its log/status')
def main():
 # Wait for the already-authorized collection process; never start a second collector.
 while True:
  p=OUT/'COLLECT_STATUS.json'
  if p.exists():
   status=json.loads(p.read_text())
   if status['status']!='COMPLETE':raise RuntimeError('Collection stopped: '+str(status))
   break
  time.sleep(20)
 run('phase_e5_unified/execute.py','score')
 frozen=json.loads((OUT/'POLICY_IMPLEMENTATION_FREEZE.json').read_text())
 for name,digest in frozen['code_sha256'].items():assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest,name
 run('phase_e5_unified/train_policies.py')
 files=['phase_e5_unified/PAIRED_EXECUTION_MANIFEST.jsonl','phase_e5_unified/POLICY_BANK_FROZEN.json','phase_e5_unified/paired_execute.py','phase_e5_unified/analyze_final.py','phase_e5_unified/execute.py','phase_e5_unified/common.py','phase_e5_unified/EXECUTION_PROTOCOL.json','run_e4_0_b_exploration.py']
 dump('PAIRED_EXECUTION_FREEZE.json',{'status':'FROZEN_BEFORE_PAIRED_API_CALLS','evidence_role':'OOF development evaluation, not fresh holdout','artifact_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}})
 run('phase_e5_unified/paired_execute.py')
 run('phase_e5_unified/analyze_final.py')
 dump('PIPELINE_STATUS.json',{'status':'UNIFIED_DEVELOPMENT_COMPLETE','fresh_holdout':'NOT_RUN'})
if __name__=='__main__':
 with (OUT/'PIPELINE.lock').open('w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:main()
  except Exception as exc:dump('PIPELINE_STATUS.json',{'status':'STOPPED','reason':str(exc)});raise
