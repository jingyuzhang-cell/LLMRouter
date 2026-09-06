import pathlib,time,subprocess,json
r=pathlib.Path(__file__).resolve().parent
last=None
while True:
 files=sorted((r/'runs').glob('*/REPRO_RESULTS.json'))
 signature=tuple((str(p),p.stat().st_mtime_ns) for p in files)
 if signature!=last:
  subprocess.run([str(r/'.venv/bin/python'),str(r/'aggregate_results.py')],check=True)
  last=signature
 if len(files)==9 or any(json.loads(p.read_text())['status']=='EXECUTION_ERROR' for p in files):break
 time.sleep(30)
