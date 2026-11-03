"""Non-generation metadata and GPU inspection; functions are inert until called."""
import json,subprocess,urllib.request
from pathlib import Path
from kdx_service_preflight import metadata_request
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):raise ValueError('PREFLIGHT_REDIRECT_FORBIDDEN')
class MetadataHTTP:
 def __init__(self,port):
  if type(port)!=int or not 1024<=port<=65535:raise ValueError('PORT')
  self.base=f'http://127.0.0.1:{port}';self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
 def __call__(self,method,path,timeout):
  metadata_request(method,path)
  if not 0<timeout<=3:raise ValueError('METADATA_TIMEOUT_BOUND')
  request=urllib.request.Request(self.base+path,method='GET')
  with self.opener.open(request,timeout=timeout) as response:
   body=response.read(65537)
   if len(body)>65536:raise ValueError('METADATA_SIZE_BOUND')
   if path=='/health':return {'status':response.status}
   result=json.loads(body);return result

def gpu_snapshot(timeout=5):
 if not 0<timeout<=5:raise ValueError('GPU_QUERY_BOUND')
 # One process invocation to bound total query latency.
 r=subprocess.run(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_gpu_memory','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=timeout)
 if r.returncode:raise RuntimeError('GPU_QUERY_FAILED')
 rows=[]
 for line in r.stdout.splitlines():
  if line.strip():
   uuid,pid,memory=[s.strip() for s in line.split(',')];rows.append({'gpu_uuid':uuid,'pid':int(pid),'used_gpu_memory':memory})
 return {'processes':rows,'scope':'compute processes; no driver-wide free-memory claim'}

def session_members(session):
 members=[]
 for p in Path('/proc').iterdir():
  if p.name.isdigit():
   try:
    s=(p/'stat').read_text();fields=s[s.rfind(')')+2:].split()
    if int(fields[3])==session:members.append(int(p.name))
   except FileNotFoundError:pass
 return members

def final_exit_probe(session,baseline,snapshot=gpu_snapshot,members=session_members):
 live=members(session);after=snapshot(timeout=5)
 before_ids={r['pid'] for r in baseline['processes']}
 # Unexpected new GPU processes cannot be attributed safely: fail closed, never kill them.
 new=[r for r in after['processes'] if r['pid'] not in before_ids]
 return {'confirmed':not live and not new and all(r['pid']!=session for r in after['processes']),'live_session_pids':live,'unexpected_gpu_processes':new,'gpu_after':after,'other_experiment_pids':[r['pid'] for r in after['processes'] if r['pid'] in before_ids]}
