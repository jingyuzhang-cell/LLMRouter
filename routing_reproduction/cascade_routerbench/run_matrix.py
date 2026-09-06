import os,pathlib,subprocess,json,time
r=pathlib.Path(__file__).resolve().parent
pools={3:'9,4,5',5:'0,9,4,3,5',11:'0,1,2,3,4,5,6,7,8,9,10'}
assert json.loads((r/'runs/gsm8k_3/REPRO_RESULTS.json').read_text())['status']=='PASS'
env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
for n in (3,5,11):
 for dataset in ('mbpp','mmlu','gsm8k'):
  if n==3 and dataset=='gsm8k':continue
  name=f'{dataset}_{n}'
  out=r/'runs'/name;out.mkdir(parents=True,exist_ok=True)
  result=out/'REPRO_RESULTS.json'
  if result.exists() and json.loads(result.read_text()).get('status') in ('PASS','FAIL'):
   print('SKIP_COMPLETED',name,flush=True)
   continue
  print('START',name,time.strftime('%Y-%m-%d %H:%M:%S'),flush=True)
  with (out/'run.log').open('a') as log:
   code=subprocess.call([str(r/'.venv/bin/python'),str(r/'run_reproduction.py'),'--dataset',dataset,'--models',pools[n],'--output-dir',str(out)],cwd=r,env=env,stdout=log,stderr=subprocess.STDOUT)
  print('END',name,'exit',code,time.strftime('%Y-%m-%d %H:%M:%S'),flush=True)
  if code:raise SystemExit(code)
print('MATRIX_COMPLETE',flush=True)
