"""Serial, locked, denied-network regression runner. Never replaces prior logs."""
from pathlib import Path
import fcntl,os,sys,json,shutil,subprocess,time,hashlib
OUT=Path(__file__).resolve().parent;ROOT=OUT.parent
lock=(OUT/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
DEST=OUT/'isolated';DEST.mkdir(exist_ok=False)
for child in ROOT.iterdir():
    if child.name in {'legacy','__pycache__','.git'} or child.name.startswith(('v5_migration_','v5_final_acceptance_')):continue
    if child.is_dir():shutil.copytree(child,DEST/child.name)
    else:shutil.copy2(child,DEST/child.name)
shutil.copytree(ROOT/'legacy',DEST/'legacy')
shutil.copyfile(OUT/'test_final_acceptance.py',DEST/'test_final_acceptance.py')
for p in DEST.rglob('*.py'):
    if 'legacy' in p.relative_to(DEST).parts:continue
    p.chmod(0o644);p.write_text(p.read_text().replace(str(ROOT),str(DEST)))
(DEST/'sitecustomize.py').write_text('''import sys
import urllib.request
from pathlib import Path
BLOCKS=Path(__file__).parent/'NETWORK_OR_CREDENTIAL_DENIALS.log'
def deny(*a,**kw):
    with BLOCKS.open('a') as f:f.write('blocked network or credential access\\n')
    raise RuntimeError('ZERO_API_ACCEPTANCE_DENIED')
def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):deny()
    if event=='open' and isinstance(args[0],str) and (args[0].startswith('/root/.zcode/') or args[0].startswith('/root/.env')):deny()
sys.addaudithook(audit)
urllib.request.urlopen=deny
import pilot_common
pilot_common._api_key=deny
''')
env={**os.environ,'PYTHONPATH':str(DEST),'PYTHONDONTWRITEBYTECODE':'1','CUDA_VISIBLE_DEVICES':''}
suites=['test_budget_guard.py','dry_run_tests.py','test_meter_v22.py','test_fixes_v2.py',
        'test_joint_executor.py','test_v5_modules.py','test_v5_migration.py','test_final_acceptance.py']
rows=[]
for suite in suites:
    start=time.monotonic();command=[sys.executable,'-u',str(DEST/suite)]
    try:
        r=subprocess.run(command,cwd=DEST,env=env,capture_output=True,text=True,timeout=90)
        code,stdout,stderr=r.returncode,r.stdout,r.stderr
    except subprocess.TimeoutExpired as e:
        code=124;stdout=(e.stdout or b'').decode() if isinstance(e.stdout,bytes) else (e.stdout or '');stderr='TIMEOUT_90S'
    with (OUT/(suite+'.log')).open('x') as f:f.write(stdout+'\nSTDERR\n'+stderr+'\nEXIT_CODE='+str(code)+'\n')
    rows.append({'suite':suite,'exit_code':code,'elapsed_s':time.monotonic()-start,'log':str(OUT/(suite+'.log')),
                 'original_test_sha256':hashlib.sha256((ROOT/suite if (ROOT/suite).exists() else OUT/suite).read_bytes()).hexdigest()})
    with (OUT/'TEST_RESULTS_PROGRESS.json').open('w') as f:json.dump(rows,f,indent=2)
    print(suite,'exit',code,flush=True)
with (OUT/'TEST_RESULTS.json').open('x') as f:json.dump(rows,f,indent=2)
if all(r['exit_code']==0 for r in rows):
    r=subprocess.run([sys.executable,'-u',str(OUT/'run_matrix.py')],cwd=DEST,env=env,capture_output=True,text=True,timeout=90)
    with (OUT/'MATRIX_RUN.log').open('x') as f:f.write(r.stdout+'\nSTDERR\n'+r.stderr+'\nEXIT_CODE='+str(r.returncode)+'\n')
    with (OUT/'MATRIX_EXIT.json').open('x') as f:json.dump({'exit_code':r.returncode},f)
    print('matrix exit',r.returncode,flush=True)
else:print('Matrix not run: regression failure',flush=True)
assert not (DEST/'NETWORK_OR_CREDENTIAL_DENIALS.log').exists(),'Network/credential attempt occurred'
