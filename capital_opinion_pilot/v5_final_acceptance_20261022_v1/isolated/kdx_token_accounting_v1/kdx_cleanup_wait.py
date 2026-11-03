"""Bounded confirmation sampling; no signal escalation, model or HTTP calls."""
import time

def wait_for_exit(probe,deadline,*,probe_bound=5,interval=.2,clock=time.monotonic,sleep=time.sleep,on_sample=lambda row:None):
 if probe_bound<=0 or interval<=0:raise ValueError('CLEANUP_BOUNDS')
 samples=0
 while deadline-clock()>=probe_bound:
  started=clock();ok=probe();ended=clock();samples+=1
  on_sample({'sample':samples,'confirmed':bool(ok),'duration':ended-started,'remaining':max(0,deadline-ended)})
  if ended>deadline or ended-started>probe_bound:raise TimeoutError('CLEANUP_PROBE_BOUND_EXCEEDED')
  if ok:return samples
  if deadline-clock()<probe_bound+interval:break
  sleep(interval)
 raise TimeoutError('GPU_OR_WORKER_EXIT_DEADLINE')
