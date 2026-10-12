"""Pre-load offline gate. No model server, HTTP, gold contents or weight loading."""
import hashlib,json
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()

def check(packet,p,configs):
 required=p.get('required_files',[])
 if 'MODEL_POOL_OFFLINE.json' not in required:raise ValueError('NO_GO: model snapshot not mandatory')
 for name in required:
  path=packet/name
  if not path.is_file():raise ValueError('NO_GO: missing required file '+name)
  if name not in p['file_sha256'] or sha(path)!=p['file_sha256'][name]:raise ValueError('NO_GO: file hash '+name)
  if path.suffix=='.json':json.loads(path.read_text())
 pool=json.loads((packet/'MODEL_POOL_OFFLINE.json').read_text())
 for slot,cfg in configs.items():
  m=pool.get(slot,{})
  if m.get('path')!=str(Path(cfg['path']).resolve()) or m.get('served')!=cfg['served']:raise ValueError('NO_GO: model binding '+slot)
  if not Path(m['path']).is_dir() or not m.get('weights_verified'):raise ValueError('NO_GO: model path/weights '+slot)
  for group in ('config_sha256','tokenizer_sha256'):
   for name,h in m[group].items():
    if not (Path(m['path'])/name).is_file() or sha(Path(m['path'])/name)!=h:raise ValueError('NO_GO: '+group+' '+slot+'/'+name)
  for name in m['weight_sha256']:
   if not (Path(m['path'])/name).is_file():raise ValueError('NO_GO: missing weight '+slot+'/'+name)
 # Full weight contents are rehashed in main() audit_pool before service activation.
 if p['requests']!=sum(x['requests_upper'] for x in p['cells']) or p['total_tokens']!=sum(x['tokens_upper'] for x in p['cells']):raise ValueError('NO_GO: budget sum')
 return dict(status='OFFLINE_GO',real_execution_authorized=False,weight_content_gate='snapshot freshly computed; runtime audit_pool rechecks full manifest before loading')
