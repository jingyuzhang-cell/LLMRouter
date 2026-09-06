import concurrent.futures,subprocess,pathlib,hashlib,re
root=pathlib.Path(__file__).resolve().parent
url='https://download.pytorch.org/whl/cpu/torch-2.4.0%2Bcpu-cp312-cp312-linux_x86_64.whl'
size=194980071
chunk=8*1024*1024
folder=root/'wheels'
def part(i):
 start=i*chunk;end=min(size-1,start+chunk-1)
 p=folder/f'torch.part{i:03d}'
 subprocess.run(['curl','--http1.1','-fsSL','--retry','4','--retry-all-errors','--max-time','180','--range',f'{start}-{end}',url+f'?part={i}','-o',str(p)],check=True)
 if p.stat().st_size!=end-start+1: raise ValueError((i,p.stat().st_size,end-start+1))
 print(i,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:list(ex.map(part,range((size+chunk-1)//chunk)))
out=folder/'torch-2.4.0+cpu-cp312-cp312-linux_x86_64.whl'
with out.open('wb') as f:
 for p in sorted(folder.glob('torch.part*')):f.write(p.read_bytes())
html=(root/'data/torch-wheel-index.html').read_text()
expected=re.search(r'torch-2\.4\.0%2Bcpu-cp312-cp312-linux_x86_64\.whl#sha256=([a-f0-9]+)',html).group(1)
actual=hashlib.sha256(out.read_bytes()).hexdigest()
assert actual==expected,(actual,expected)
print('VERIFIED',actual,flush=True)
