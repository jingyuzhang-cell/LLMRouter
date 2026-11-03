"""Owned-process lifecycle; constructor and tests never load a model."""
import fcntl,json,os,signal,subprocess,threading,time
from pathlib import Path
from strict_meter import append_sync
def persist_marker(path,row):
 with path.open('w') as f:
  json.dump(row,f);f.flush();os.fsync(f.fileno())
def verify_session_gpu_exit(session_id):
 # Fail closed on unavailable GPU accounting or any live member of the owned session.
 for entry in Path('/proc').iterdir():
  if entry.name.isdigit():
   try:
    raw=(entry/'stat').read_text();fields=raw[raw.rfind(')')+2:].split()
    if int(fields[3])==session_id:return False
   except (FileNotFoundError,ProcessLookupError):continue
   except (PermissionError,ValueError):return False
 result=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5)
 if result.returncode:return False
 # A session already absent cannot have live CUDA-owning Linux processes; stale own leader is rejected.
 return str(session_id) not in result.stdout.split()

class OwnedService:
 def __init__(self,command,lock_path,run_dir,wall_seconds,request_seconds=60,popen=subprocess.Popen,killpg=os.killpg,exit_probe=verify_session_gpu_exit):
  self.exit_probe=exit_probe;self.quarantine=Path(str(lock_path)+'.quarantine.json');self.command=command;self.lock_path=Path(lock_path);self.run_dir=Path(run_dir);self.wall_seconds=wall_seconds;self.request_seconds=request_seconds;self.popen=popen;self.killpg=killpg;self.process=None;self.lock=None;self.timer=None;self.start_time=None;self.guard=threading.Lock();self.closed=False;self.created=False
 def event(self,event,**data):append_sync(self.run_dir/'SERVICE_EVENTS.jsonl',dict(event=event,time=time.time(),**data))
 def start(self):
  self.lock=self.lock_path.open('a+')
  try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BaseException:self.lock.close();self.lock=None;raise
  try:
   if self.quarantine.exists():raise ValueError('RESOURCE_QUARANTINED')
   self.run_dir.mkdir(exist_ok=False);self.created=True;self.start_time=time.monotonic()
   persist_marker(self.quarantine,{'state':'RESOURCE_ACTIVE_OR_INTERRUPTED','run_dir':str(self.run_dir),'created':time.time()})
   self.event('START_ATTEMPT',command=self.command)
   self.log=(self.run_dir/'SERVICE.log').open('ab')
   self.process=self.popen(self.command,start_new_session=True,stdout=self.log,stderr=subprocess.STDOUT)
   self.event('OWNED_PROCESS',pid=self.process.pid)
   self.timer=threading.Timer(self.wall_seconds,self.stop);self.timer.daemon=True;self.timer.start()
  except BaseException:
   self.stop();raise
 def check_identity(self,models_response,expected):
  if not self.process or self.process.poll() is not None:raise ValueError('OWN_SERVICE_NOT_RUNNING')
  if [r.get('id') for r in models_response.get('data',[])]!=[expected]:raise ValueError('MODEL_IDENTITY_MISMATCH')
  self.event('IDENTITY_CONFIRMED',model=expected)
 def request(self,fn,cleanup_reserve=10):
  if not self.process or self.closed:raise ValueError('SERVICE_NOT_AVAILABLE')
  if time.monotonic()-self.start_time+self.request_seconds+cleanup_reserve>self.wall_seconds:raise ValueError('WALLCLOCK_ADMISSION')
  timer=threading.Timer(self.request_seconds,self.stop);timer.daemon=True;timer.start()
  try:return fn()
  except BaseException:
   self.stop();raise
  finally:timer.cancel()
 def stop(self):
  with self.guard:
   if self.closed:return
   self.closed=True
   if self.timer:self.timer.cancel()
   failed=None
   cleanup_deadline=min(time.monotonic()+10, (self.start_time or time.monotonic())+self.wall_seconds+10)
   try:
    if self.process is not None:
     # PID is only a Popen child created here with a new session, never discovered from another experiment.
     self.event('STOP_SIGNAL_SENT',pid=self.process.pid,signal='SIGKILL',cleanup_deadline_monotonic=cleanup_deadline)
     try:self.killpg(self.process.pid,signal.SIGKILL)
     except ProcessLookupError:pass
     self.process.wait(timeout=min(5,max(.01,cleanup_deadline-time.monotonic())))
     self.event('OWNED_PROCESS_STOPPED',pid=self.process.pid)
     from kdx_cleanup_wait import wait_for_exit
     wait_for_exit(lambda:self.exit_probe(self.process.pid),cleanup_deadline,on_sample=lambda row:self.event('EXIT_CONFIRMATION_SAMPLE',**row))
   except BaseException as e:failed=e;self.event('CLEANUP_FAILED',error=type(e).__name__)
   finally:
    if hasattr(self,'log'):self.log.close()
    if failed:
     persist_marker(self.quarantine,{'state':'RESOURCE_QUARANTINED','run_dir':str(self.run_dir),'owned_pid':None if self.process is None else self.process.pid,'error':type(failed).__name__})
    elif self.lock:
     if self.created and self.quarantine.exists():self.quarantine.unlink()
     self.lock.close();self.lock=None
   if self.created:self.event('END',elapsed=None if self.start_time is None else time.monotonic()-self.start_time,cleanup_ok=failed is None)
   if failed:raise RuntimeError('OWNED_SERVICE_CLEANUP_FAILED') from failed
 def __enter__(self):self.start();return self
 def __exit__(self,typ,value,tb):
  try:self.stop()
  except BaseException:
   if typ is None:raise
  return False
