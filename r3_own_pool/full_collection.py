"""Supervise the authorized 5000-query collection with separate API/local lanes.
Wait for legacy jobs and environment repair; never kill another session's work.
Does not score, freeze outcomes, or train on an incomplete matrix.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
R=Path(__file__).resolve().parent
C=R/'collect'
OUT=R/'data/full_run_v2'
VENV='/root/autodl-tmp/r3_venv/bin/python'
DEADLINE_SECONDS=24*3600

def processes():
    result=[]
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if int(p.name)==os.getpid():continue
            args=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            cwd=(p/'cwd').resolve()
            result.append((int(p.name),args,str(cwd)))
        except (OSError,ValueError):pass
    return result

def blockers(lane):
    found=[]
    for pid,args,cwd in processes():
        executable=args.split(' ',1)[0]
        if 'python' not in executable and not executable.endswith('/vllm'):continue
        # Legacy runner processes predate advisory locks, so explicitly wait for them.
        if 'runner.py' in args and str(C)==cwd:
            if (lane=='reasoning')==('--collect reasoning' in args):found.append(pid)
        if lane=='local' and str(Path(VENV).parent.parent) in args and ('pip install' in args or '-m pip install' in args):
            found.append(pid)
    return sorted(set(found))

def write_status(lane,phase,**extra):
    doc=dict(lane=lane,phase=phase,updated_at=time.time(),**extra)
    dest=OUT/f'{lane}.json';tmp=dest.with_suffix('.tmp')
    tmp.write_text(json.dumps(doc,indent=2));tmp.replace(dest)
    print(json.dumps(doc),flush=True)

def wait_ready(lane):
    end=time.monotonic()+DEADLINE_SECONDS
    while time.monotonic()<end:
        pids=blockers(lane)
        if not pids:return
        write_status(lane,'WAITING_FOR_EXISTING_WORK',pids=pids)
        time.sleep(30)
    raise RuntimeError('Existing work did not finish within 24 hours')

def weights_ready(slot):
    import sys
    sys.path.insert(0,str(C))
    import runner
    base=Path(runner.SLOTS[slot]['path']())
    index=json.loads((base/'model.safetensors.index.json').read_text())
    for name in set(index['weight_map'].values()):
        p=base/name
        if not p.is_file() or p.stat().st_size==0:raise RuntimeError(f'Missing model shard: {p}')
    for name in ('config.json','tokenizer_config.json','tokenizer.json'):
        if not (base/name).is_file():raise RuntimeError(f'Missing model file: {base/name}')

def run_slot(slot):
    cmd=[VENV if slot!='reasoning' else sys.executable,str(C/'runner.py'),'--collect',slot]
    log=OUT/f'{slot}.log'
    for retry in (False,True):
        with log.open('a') as f:
            proc=subprocess.Popen(cmd+(['--retry-failed'] if retry else []),cwd=C,stdout=f,stderr=subprocess.STDOUT)
            write_status('reasoning' if slot=='reasoning' else 'local','COLLECTING',slot=slot,pid=proc.pid,retry=retry,log=str(log))
            code=proc.wait()
        if code:raise RuntimeError(f'{slot} exited {code}; see {log}')

def lane(name):
    try:
        wait_ready(name)
        if name=='reasoning':
            if not os.environ.get('QWEN_API_KEY'):raise RuntimeError('QWEN_API_KEY unavailable')
            run_slot('reasoning')
        else:
            # Validate imports once repair has completed. A failure stops this lane.
            check=subprocess.run([VENV,'-c','from vllm.model_executor.models.qwen2 import Qwen2ForCausalLM; print("Qwen2 import OK")'],capture_output=True,text=True)
            (OUT/'vllm_preflight.log').write_text(check.stdout+check.stderr)
            if check.returncode:raise RuntimeError('vLLM import preflight failed; see vllm_preflight.log')
            # 7B is available already; 3B downloads can finish while medium/large run.
            for slot in ('medium','large','small'):
                weights_ready(slot)
                run_slot(slot)
        write_status(name,'RAW_COLLECTION_FINISHED',note='Scoring and outcome validation remain required')
    except Exception as exc:
        write_status(name,'BLOCKED',reason=str(exc))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    lock=open(OUT/'supervisor.lock','a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    lock.seek(0);lock.truncate();lock.write(str(os.getpid()));lock.flush()
    # Parse dotenv without shell evaluation; never log credentials.
    from dotenv import dotenv_values
    for key,value in dotenv_values('/root/.env').items():
        if value is not None:os.environ.setdefault(key,value)
    threads=[threading.Thread(target=lane,args=(name,)) for name in ('reasoning','local')]
    for t in threads:t.start()
    for t in threads:t.join()
if __name__=='__main__':main()
