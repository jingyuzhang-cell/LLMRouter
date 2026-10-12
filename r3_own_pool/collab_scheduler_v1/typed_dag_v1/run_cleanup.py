"""Owned-service cleanup survives trace errors and preserves original failure."""
import time
from .request_trace import mark

def finish(service,directory,start,request_ids=()):
 began=time.monotonic();errors=[]
 def log(stage,**kw):
  try:mark(directory/'CLEANUP_TRACE.jsonl','run',stage,**kw)
  except BaseException as exc:errors.append(dict(stage='cleanup_logging',error=repr(exc)))
 log('service_stop_requested',request_ids=list(request_ids))
 try:
  if service is not None:service.close()
 except BaseException as exc:errors.append(dict(stage='service_close',error=repr(exc)));log('cleanup_failed',error=repr(exc))
 stopped=service is None or service.active is None
 log('cleanup_finished',service_stopped=stopped)
 end=time.monotonic()
 return dict(cleanup_start_monotonic_s=began,cleanup_end_monotonic_s=end,cleanup_wall_s=end-began,total_wall_s=end-start,finish_unix_s=time.time(),service_stopped=stopped,errors=errors)
