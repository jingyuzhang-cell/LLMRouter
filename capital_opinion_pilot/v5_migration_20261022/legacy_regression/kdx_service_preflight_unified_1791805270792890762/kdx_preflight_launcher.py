"""Single supported preflight controller, no CLI start and no inference transport."""
import json,os,time,threading
from pathlib import Path
from kdx_service_preflight import validate_package,metadata_request
from kdx_owned_service import OwnedService
from strict_meter import append_sync

class Preflight:
 def __init__(self,package,run_dir,service_factory=OwnedService,metadata=None,gpu_snapshot=None,clock=time.monotonic,sleep=time.sleep,timer=threading.Timer):
  self.package=Path(package);self.run=Path(run_dir);self.factory=service_factory;self.metadata=metadata;self.gpu=gpu_snapshot;self.clock=clock;self.sleep=sleep;self.timer_factory=timer
 def execute(self,*,authorized=False):
  if not authorized:raise ValueError('REAL_PREFLIGHT_NOT_AUTHORIZED')
  protocol=validate_package(self.package)
  if self.metadata is None or self.gpu is None:raise ValueError('BOUNDED_METADATA_AND_GPU_ADAPTERS_REQUIRED')
  # command is only from verified package; no arbitrary script/config execution.
  command=protocol['model_command']
  if len(command)<4 or command[1]!='serve' or any(x in command for x in ['-c','bash','sh']):raise ValueError('UNSUPPORTED_START_ENTRY')
  start=self.clock();primary=None;cleanup=None;watch=None;service=None
  self.run.parent.mkdir(parents=True,exist_ok=True)
  report={'manager_pid':os.getpid(),'model_requests':0,'inference_tokens':0,'command':command,'time_started':time.time(),'deadline_seconds':300,'events':[]}
  try:
   baseline=self.gpu(timeout=5);report['gpu_before']=baseline
   if self.clock()-start>=10:raise TimeoutError('PRESTART_PROBE_BOUND')
   service=self.factory(command,protocol['lock_path'],self.run,wall_seconds=290-(self.clock()-start),request_seconds=3)
   service.start();report['service_pid']=service.process.pid;report['process_group']=service.process.pid
   # Independent of polling loop; starts cleanup with reserved time before 300s.
   def cutoff():
    try:service.stop()
    except BaseException as e:report['watchdog_error']=type(e).__name__
   watch=self.timer_factory(max(0,280-(self.clock()-start)),cutoff);watch.daemon=True;watch.start()
   expected=command[command.index('--served-model-name')+1]
   while self.clock()-start<240:
    if service.process.poll() is not None:raise RuntimeError('SERVICE_EXITED')
    metadata_request('GET','/health')
    healthy=self.metadata('GET','/health',timeout=min(3,240-(self.clock()-start)))
    report['events'].append({'event':'HEALTH_CHECK','elapsed':self.clock()-start})
    if healthy.get('status')==200:
     metadata_request('GET','/v1/models');models=self.metadata('GET','/v1/models',timeout=3)
     service.check_identity(models,expected);report['models']=models;report['ready_metadata']=True;break
    self.sleep(min(1,max(0,240-(self.clock()-start))))
   else:raise TimeoutError('LOAD_HEALTH_DEADLINE')
  except BaseException as e:primary={'type':type(e).__name__,'message':str(e)}
  finally:
   if watch:watch.cancel()
   if service:
    try:service.stop()
    except BaseException as e:cleanup={'type':type(e).__name__,'message':str(e)}
   report['primary_error']=primary;report['cleanup_error']=cleanup
   try:report['gpu_after']=self.gpu(timeout=5)
   except BaseException as e:report['gpu_verification_error']=type(e).__name__
   report['time_ended']=time.time();report['wall_seconds']=self.clock()-start
   report['result']='PASS_METADATA_ONLY' if not primary and not cleanup and 'gpu_after' in report and report['wall_seconds']<=300 else 'FAILED_OR_QUARANTINED'
   # Failed final GPU confirmation requires persistent quarantine, even if process cleanup succeeded.
   if report['result']!='PASS_METADATA_ONLY' and service and service.process is not None:
    from kdx_owned_service import persist_marker
    persist_marker(service.quarantine,{'state':'RESOURCE_QUARANTINED','run_dir':str(self.run),'reason':report['result']})
   if self.run.exists():append_sync(self.run/'PREFLIGHT_RESULT.jsonl',report)
  return report
