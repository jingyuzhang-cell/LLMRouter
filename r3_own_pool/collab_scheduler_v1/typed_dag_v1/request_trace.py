"""Client observations, never inferred server phase timing."""
import json,time,uuid
from .resource_envelope import request_deadline

def new_id():return 'typed-'+uuid.uuid4().hex

def mark(path,rid,stage,**fields):
 row=dict(request_id=rid,stage=stage,monotonic_s=time.monotonic(),unix_s=time.time(),**fields)
 with path.open('a') as f:f.write(json.dumps(row)+'\n')
 return row

def exchange(opener,req,timeout,path,rid):
 mark(path,rid,'dispatch',timeout_s=timeout,server_receive='UNKNOWN',schema='UNKNOWN',prefill='UNKNOWN',decode='UNKNOWN')
 started=time.monotonic()
 try:
  with request_deadline(timeout):
   with opener.open(req,timeout=timeout) as response:
    mark(path,rid,'headers_received',http_status=response.status,server_request_id=response.headers.get('X-Request-Id'),connect_vs_wait='NOT_SEPARATELY_OBSERVED')
    raw=response.read().decode()
    mark(path,rid,'body_complete',elapsed_s=time.monotonic()-started)
    return response.status,raw
 except BaseException as exc:
  mark(path,rid,'request_error',exception_type=type(exc).__name__,exception=str(exc),elapsed_s=time.monotonic()-started,server_cancel_confirmed=False,server_may_continue=True)
  raise
