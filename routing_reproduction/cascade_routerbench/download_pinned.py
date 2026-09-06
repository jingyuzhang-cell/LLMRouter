from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess
r=Path(__file__).resolve().parent
lines=(r/'requirements-without-torch.txt').read_text().splitlines()
def job(i):
 p=r/f'logs/requirements-part{i}.txt';p.write_text('\n'.join(lines[i::8])+'\n')
 with (r/f'logs/pip-download-{i}.log').open('w') as f:
  subprocess.run([str(r/'.venv/bin/python'),'-m','pip','download','--no-deps','-r',str(p),'-d',str(r/'wheels'),'--index-url','https://pypi.org/simple'],stdout=f,stderr=subprocess.STDOUT,check=True)
 print('downloaded',i,flush=True)
with ThreadPoolExecutor(max_workers=8) as e:list(e.map(job,range(8)))
