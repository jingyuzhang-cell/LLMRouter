"""Copies test inputs; never writes original ledgers or uses network credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path('/root/capital_opinion_pilot')
OUT=ROOT/'v5_migration_20261022'
SUITES=['test_budget_guard.py','dry_run_tests.py','test_meter_v22.py','test_fixes_v2.py','test_joint_executor.py','test_v5_modules.py']

def prepare(name, legacy=False):
    dest=OUT/name
    if dest.exists():
        raise RuntimeError('Refusing to overwrite prior sandbox: '+str(dest))
    shutil.copytree(ROOT,dest,ignore=shutil.ignore_patterns('legacy','v5_migration_20261022','__pycache__'))
    if legacy:
        for p in (ROOT/'legacy/scheduler_v4_20261022/src').glob('*.py'):
            target=dest/p.name
            if target.exists():target.chmod(0o644)
            shutil.copyfile(p,target)
    else:
        # Historical reproduction scripts explicitly import the archived algorithm.
        shutil.copytree(ROOT/'legacy',dest/'legacy')
    for p in dest.rglob('*.py'):
        if 'legacy' in p.relative_to(dest).parts:continue
        p.chmod(0o644)
        p.write_text(p.read_text().replace(str(ROOT),str(dest)))
    (dest/'sitecustomize.py').write_text('''import sys
import urllib.request

def deny(*args, **kwargs):
    raise RuntimeError("ZERO_API_TEST_NETWORK_DENIED")
urllib.request.urlopen=deny
sys.addaudithook(lambda event,args: deny() if event in ('socket.connect','socket.getaddrinfo') else None)
import pilot_common
pilot_common._api_key=deny
''')
    return dest

results=[]
for label,old in [('v5_acceptance_final',False)]:
    dest=prepare(label,old)
    suites=SUITES+([] if old else ['test_v5_migration.py'])
    for suite in suites:
        env={**os.environ,'PYTHONPATH':str(dest),'PYTHONDONTWRITEBYTECODE':'1'}
        r=subprocess.run([sys.executable,'-u',str(dest/suite)],cwd=dest,env=env,capture_output=True,text=True,timeout=90)
        log=OUT/f'{label}_{suite}.log';log.write_text(r.stdout+'\nSTDERR\n'+r.stderr)
        results.append({'version':label,'suite':suite,'exit_code':r.returncode,'log':str(log)})
        print(label,suite,r.returncode,flush=True)
(OUT/'REGRESSION_RESULTS.json').write_text(json.dumps(results,indent=2)+'\n')
