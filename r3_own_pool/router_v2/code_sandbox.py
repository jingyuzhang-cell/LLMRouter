"""Root-owned relocated Python; unprivileged Landlock/seccomp code grading."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from .data import sha
from .embed_queries import write_json
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path('/tmp/r3-code-runtime-v3')


def build(runtime=RUNTIME):
    runtime=Path(runtime)
    if runtime.exists():raise FileExistsError('Refuse runtime overwrite')
    runtime.mkdir(mode=0o755)
    base=Path('/root/miniconda3')
    (runtime/'bin').mkdir();(runtime/'lib').mkdir()
    shutil.copy2(base/'bin/python3.12',runtime/'bin/python3.12')
    exclude=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip','*.a')
    shutil.copytree(base/'lib/python3.12',runtime/'lib/python3.12',ignore=exclude)
    binaries=[runtime/'bin/python3.12',*list((runtime/'lib/python3.12/lib-dynload').glob('*.so'))]
    dependencies={}
    for binary in binaries:
        output=subprocess.run(['ldd',str(binary)],capture_output=True,text=True).stdout
        # Resolve conda dependencies from original extensions; relocated ones may lack them initially.
        if binary.suffix=='.so':
            output += subprocess.run(['ldd',str(base/'lib/python3.12/lib-dynload'/binary.name)],capture_output=True,text=True).stdout
        for name,source in re.findall(r'^\s*(\S+)\s+=>\s+(/\S+)',output,re.M):
            if str(base) in source:
                target=runtime/'lib'/name
                if not target.exists():shutil.copy2(source,target)
                dependencies[name]=source
    shutil.copy2(Path(__file__).with_name('code_worker.py'),runtime/'worker.py')
    for path in runtime.rglob('*'):
        if path.is_dir():path.chmod(0o755)
        elif path==runtime/'bin/python3.12':path.chmod(0o755)
        else:path.chmod(0o644)
    files={str(p.relative_to(runtime)):sha(p) for p in sorted(runtime.rglob('*')) if p.is_file()}
    write_json(runtime/'MANIFEST.json',dict(files=files,dependencies=dependencies,
        worker_source_sha256=sha(Path(__file__).with_name('code_worker.py')),
        role='stdlib-only controlled Python 3.12 code evaluation; no third-party packages'))
    return dict(runtime=str(runtime),files=len(files),bytes=sum(p.stat().st_size for p in runtime.rglob('*') if p.is_file()))


def verify_runtime(runtime=RUNTIME):
    runtime=Path(runtime)
    manifest=json.loads((runtime/'MANIFEST.json').read_text())
    if sha(runtime/'worker.py') != sha(Path(__file__).with_name('code_worker.py')):
        raise ValueError('Sandbox worker implementation changed')
    for path in [runtime,*runtime.rglob('*')]:
        if path.stat().st_uid!=0 or path.stat().st_mode & 0o022:
            raise ValueError('Runtime must be root-owned and not writable by sandbox uid')
    for name,value in manifest['files'].items():
        if sha(runtime/name)!=value:raise ValueError('Runtime hash mismatch: '+name)
    return sha(runtime/'MANIFEST.json')


def execute(program,runtime=RUNTIME,timeout=12):
    runtime=Path(runtime)
    nonce=secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix='r3-code-work-') as work:
        os.chown(work,65534,65534);os.chmod(work,0o700)
        with tempfile.TemporaryFile() as output:
            started=time.monotonic()
            try:
                proc=subprocess.run([str(runtime/'bin/python3.12'),'-I','-S',str(runtime/'worker.py')],
                    input=json.dumps(dict(program=program,nonce=nonce)).encode(),stdout=output,stderr=output,
                    cwd=work,env={'LANG':'C.UTF-8','PATH':'','PYTHONDONTWRITEBYTECODE':'1'},
                    user=65534,group=65534,extra_groups=[],close_fds=True,start_new_session=True,timeout=timeout)
                code=proc.returncode
            except subprocess.TimeoutExpired:
                output.seek(0);text=output.read(65536).decode(errors='replace')
                ready=('R3_SANDBOX_READY '+nonce) in text
                return dict(sandbox_ready=ready,passed=False,error_type='Timeout',elapsed_seconds=time.monotonic()-started)
            output.seek(0);text=output.read(65536).decode(errors='replace')
            markers=[line.split('R3_SANDBOX_RESULT ',1)[1] for line in text.split('\n') if line.startswith('R3_SANDBOX_RESULT ')]
            if markers:
                try:result=json.loads(markers[-1])
                except ValueError:result={}
                if result.get('nonce')==nonce and result.get('sandbox_ready') is True and code==0:
                    result.pop('nonce')
                    return dict(**result,elapsed_seconds=time.monotonic()-started)
            return dict(sandbox_ready=('R3_SANDBOX_READY '+nonce) in text,passed=False,error_type='BootstrapOrAbnormalExit',
                        returncode=code,diagnostic=text[-3000:],elapsed_seconds=time.monotonic()-started)


def probe(runtime=RUNTIME):
    # A readable host canary proves path confinement beyond ordinary Unix permissions.
    with tempfile.NamedTemporaryFile(prefix='r3-host-canary-',mode='w',delete=False) as f:
        path=f.name;f.write('host canary; no secrets')
    os.chmod(path,0o644)
    cases={
        'normal_python':"import math,random,re,json\nassert math.sqrt(81)==9\nassert sum(range(10))==45",
        'filesystem_read_denied':f"try:\n open({path!r}).read()\n raise AssertionError('host readable')\nexcept PermissionError: pass",
        'network_denied':"import socket\ntry:\n socket.socket()\n raise AssertionError('socket created')\nexcept PermissionError: pass",
        'fork_denied':"import os\ntry:\n os.fork()\n raise AssertionError('fork allowed')\nexcept PermissionError: pass",
        'execute_denied':"import os\ntry:\n os.execve('/bin/true',['true'],{})\n raise AssertionError('exec allowed')\nexcept PermissionError: pass",
        'truncate_denied':f"import os\ntry:\n os.truncate({path!r},0)\n raise AssertionError('truncate allowed')\nexcept PermissionError: pass",
        'filesystem_write_denied':"try:\n open('temporary.txt','w')\n raise AssertionError('filesystem writable')\nexcept PermissionError: pass",
    }
    try:results={name:execute(program,runtime) for name,program in cases.items()}
    finally:os.unlink(path)
    success=all(r.get('sandbox_ready') is True and r['passed'] for r in results.values())
    return dict(status='PASS' if success else 'FAIL',checks=results,runtime=str(runtime),runtime_manifest_sha256=sha(Path(runtime)/'MANIFEST.json'),
                architecture='unprivileged UID/GID 65534 + Landlock ABI1 + seccomp + resource limits',
                limitations=['No network/PID namespaces available; kernel syscall/path restrictions used instead',
                    'Pure-function stdlib profile; filesystem-writing or third-party tasks need separate environment review',
                    'Not a proof against kernel exploits or adversarial in-process test spoofing'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage',choices=('build','probe'));ap.add_argument('--output')
    a=ap.parse_args()
    result=build() if a.stage=='build' else probe()
    if a.output:write_json(a.output,result)
    print(json.dumps(result,indent=2))
    if result.get('status')=='FAIL':raise SystemExit(1)

if __name__=='__main__':main()
