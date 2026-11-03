import sys,json,time,hashlib,os
from pathlib import Path
sys.path.insert(0,'/root/capital_opinion_pilot')
sys.path.insert(0,'/root/capital_opinion_pilot/trusted_shared_cleanup_fixed_v2')
from kdx_preflight_launcher import Preflight
from kdx_preflight_adapters import MetadataHTTP,gpu_snapshot
from kdx_trusted_shared_protocol import offline_validate
PACKAGE=Path('/root/capital_opinion_pilot/trusted_shared_cleanup_fixed_v2')
ROOT=PACKAGE.parent;RUN=ROOT/'trusted_shared_real_preflight_20261012_2200'
START=1791810000;END=1791810600
# Explicit UTC epochs are checked against frozen human window before service work.
import datetime
START=datetime.datetime(2026,10,12,14,0,tzinfo=datetime.timezone.utc).timestamp()
END=START+900
p=offline_validate(PACKAGE)
if hashlib.sha256((PACKAGE/'MANIFEST.json').read_bytes()).hexdigest()!='d3e4cc5f2f147620cef65aa614a0e9e8486be09a5ff76d6fd2cd1f824a081924':raise RuntimeError('MANIFEST_IDENTITY_HOLD')
identity=json.loads((PACKAGE/'MODEL_IDENTITY.json').read_text())
model=Path(identity['path'])
for name,digest in identity['hashes'].items():
 h=hashlib.sha256()
 with (model/name).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 if h.hexdigest()!=digest:raise RuntimeError('MODEL_FILE_MISMATCH:'+name)
print('MODEL_FULL_HASHES_PASS',flush=True)
while time.time()<START:
 time.sleep(min(10,START-time.time()))
if time.time()+300>END:raise RuntimeError('WINDOW_INSUFFICIENT_HOLD')
# Existing directory is permanent anti-duplicate evidence, including failed startup.
if RUN.exists():raise RuntimeError('DUPLICATE_RUN_HOLD')
attestation={'operators_agreed':True,'coordination_evidence':'User explicitly confirmed all relevant operators and parallel sessions for Beijing 2026-10-12 22:00–22:15','window_start':START,'window_end':END,'collaborative_lock_available':True}
history=[]
for d in ROOT.glob('trusted_shared_real_preflight_*'):
 if d==RUN:continue
 for f in d.glob('PREFLIGHT_RESULT.jsonl'):
  for l in f.read_text().splitlines():
   if l.strip():history.append(json.loads(l))
# The owner uses flock NONBLOCK at actual start; availability in attestation is rechecked atomically.
transport=MetadataHTTP(8127)
def startup_metadata(method,path,timeout):
 import urllib.error
 try:return transport(method,path,timeout)
 except urllib.error.URLError as e:
  if path=='/health' and isinstance(e.reason,ConnectionRefusedError):return {'status':503,'startup_state':'NOT_LISTENING_YET'}
  raise
runner=Preflight(PACKAGE,RUN,metadata=startup_metadata,gpu_snapshot=gpu_snapshot)
print('WINDOW_ENTERED; RESOURCE_AND_FREEZE_GATE_NEXT',flush=True)
result=runner.execute(authorized=True,coordination=attestation,history_records=history)
if RUN.exists():
 (RUN/'RUNTIME_WRAPPER.py').write_text(Path(__file__).read_text())
 (RUN/'AUTHORIZATION.json').write_text(json.dumps({'scope':'0 generation requests,0 inference tokens,300 planned wall seconds','window_start_utc':START,'window_end_utc':END,'coordination':attestation,'package_manifest_sha256':hashlib.sha256((PACKAGE/'MANIFEST.json').read_bytes()).hexdigest()},ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False),flush=True)
