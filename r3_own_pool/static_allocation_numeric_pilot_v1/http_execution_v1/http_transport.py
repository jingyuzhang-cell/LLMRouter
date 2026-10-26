"""One-shot official HTTP request, child-process absolute client deadline.

The mock session passes through the SAME request construction and response
reading code. No server is contacted by mock mode.
"""
import hashlib,json,multiprocessing as mp,time
from binding import Halt

MAX_RESPONSE_BYTES=4*1024*1024

class MockSession:
    def __init__(self,fixture):self.fixture=fixture;self.trust_env=True;self.retries=None
    def mount(self,prefix,adapter):self.retries=adapter.max_retries.total
    def close(self):pass
    def post(self,url,**kwargs):
        expected={'allow_redirects':False,'stream':True,'verify':True}
        assert self.trust_env is False and self.retries==0
        assert all(kwargs[k]==v for k,v in expected.items())
        assert kwargs['headers']['Authorization'].startswith('Bearer ')
        assert kwargs['timeout'][0]<=10
        assert isinstance(kwargs['data'],bytes)
        if self.fixture.get('worker_exit'):
            import os;os._exit(7)
        time.sleep(self.fixture.get('delay_s',0))
        return MockResponse(self.fixture)

class MockResponse:
    def __init__(self,f):self.fixture=f;self.status_code=f.get('status',200);self.headers={'Date':'mock-date'}
    def iter_content(self,chunk_size):
        data=self.fixture['raw_body'].encode()
        for i in range(0,len(data),chunk_size):yield data[i:i+chunk_size]
    def close(self):pass

def _worker(conn,r,key,timeout_s,fixture):
    session=None
    try:
        # Importing requests is not inference. A real Session is constructed
        # ONLY in real mode, after authorization in the parent.
        import requests
        from requests.adapters import HTTPAdapter
        session=MockSession(fixture) if fixture is not None else requests.Session()
        session.trust_env=False;session.mount('https://',HTTPAdapter(max_retries=0))
        wire=json.dumps(r['body'],ensure_ascii=False,sort_keys=True).encode()
        wire_sha=hashlib.sha256(wire).hexdigest()
        conn.send({'kind':'POST_START','worker_monotonic':time.monotonic(),'wire_body_sha256':wire_sha})
        t=time.monotonic()
        response=session.post(r['endpoint'],data=wire,
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},
            timeout=(min(10,timeout_s),timeout_s),allow_redirects=False,stream=True,verify=True)
        chunks=[];size=0;complete=True
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:continue
            if size+len(chunk)>MAX_RESPONSE_BYTES:
                chunks.append(chunk[:MAX_RESPONSE_BYTES-size]);complete=False;break
            chunks.append(chunk);size+=len(chunk)
        raw=b''.join(chunks);original_sha=hashlib.sha256(raw).hexdigest()
        # Never persist an accidentally reflected credential.
        safe=raw.replace(key.encode(),b'[REDACTED_AUTH_REFLECTION]') if key else raw
        headers={k:v for k,v in response.headers.items() if k.lower() in ['date','x-request-id','request-id']}
        conn.send({'kind':'HTTP_RESPONSE','http_status':response.status_code,'raw_body':safe,
            'original_raw_sha256':original_sha,'credential_reflection_redacted':safe!=raw,
            'body_complete':complete,'response_headers':headers,'http_worker_wall_s':time.monotonic()-t,
            'request_options':{'retries':0,'redirects':False,'trust_env':False,'tls_verify':True,'stream_response_only':True,'wire_body_sha256':wire_sha}})
        response.close()
    except BaseException as exc:
        # Do not serialize exception reprs carrying credentials or headers.
        try:conn.send({'kind':'WORKER_ERROR','error_type':type(exc).__name__})
        except (BrokenPipeError,EOFError,OSError):pass
    finally:
        if session is not None:session.close()
        conn.close()

def call_once(r,key,timeout_s=180,fixture=None):
    if timeout_s<=0:raise Halt('NO_REMAINING_CLIENT_TIME')
    ctx=mp.get_context('spawn');reader,writer=ctx.Pipe(duplex=False)
    p=ctx.Process(target=_worker,args=(writer,r,key,timeout_s,fixture))
    started=time.monotonic();events=[];result=None
    try:
        p.start();writer.close()
        while True:
            remaining=timeout_s-(time.monotonic()-started)
            if remaining<=0:
                result={'kind':'CLIENT_TIMEOUT','remote_cancel_confirmed':False};break
            if reader.poll(min(remaining,.1)):
                try:message=reader.recv()
                except EOFError:
                    result={'kind':'WORKER_DIED','exitcode':p.exitcode};break
                if message['kind']=='POST_START':events.append(message);continue
                result=message;break
            if not p.is_alive():
                result={'kind':'WORKER_DIED','exitcode':p.exitcode};break
    finally:
        if p.is_alive():p.terminate()
        p.join(timeout=1)
        if p.is_alive():p.kill();p.join(timeout=1)
        reader.close()
        writer.close()
    result.update(client_call_wall_s=time.monotonic()-started,worker_events=events,
                  evidence_class='MOCK_HTTP' if fixture is not None else 'REAL_HTTP_ATTEMPT')
    return result

def parse_response(envelope,r,accepted_models):
    if envelope['kind']!='HTTP_RESPONSE':raise Halt(envelope['kind'])
    if envelope['http_status']!=200:raise Halt('HTTP_STATUS_'+str(envelope['http_status']))
    if not envelope['body_complete']:raise Halt('HTTP_BODY_SIZE_LIMIT')
    try:d=json.loads(envelope['raw_body'])
    except (ValueError,UnicodeDecodeError):raise Halt('HTTP_JSON_PARSE')
    if not isinstance(d,dict):raise Halt('HTTP_RESPONSE_CONTAINER')
    if str(d.get('model','')).lower() not in {m.lower() for m in accepted_models}:raise Halt('RETURNED_MODEL_MISMATCH')
    choices=d.get('choices');u=d.get('usage')
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(u,dict):raise Halt('RESPONSE_CHOICES_OR_USAGE')
    if any(type(u.get(k)) is not int or u[k]<0 for k in ['prompt_tokens','completion_tokens','total_tokens']):raise Halt('UNKNOWN_OR_INVALID_USAGE')
    if u['total_tokens']!=u['prompt_tokens']+u['completion_tokens']:raise Halt('USAGE_TOTAL_MISMATCH')
    completion_details=u.get('completion_tokens_details') or {}
    if not isinstance(completion_details,dict):raise Halt('REASONING_USAGE_CONTAINER')
    reasoning=completion_details.get('reasoning_tokens')
    if reasoning is not None and (type(reasoning) is not int or not 0<=reasoning<=u['completion_tokens']):raise Halt('REASONING_USAGE_INVALID')
    details=u.get('prompt_tokens_details') or {}
    if not isinstance(details,dict):raise Halt('CACHE_USAGE_CONTAINER')
    cached=details.get('cached_tokens',u.get('prompt_cache_hit_tokens'))
    if cached is not None and (type(cached) is not int or not 0<=cached<=u['prompt_tokens']):raise Halt('CACHE_USAGE_INVALID')
    message=choices[0].get('message',{});answer=message.get('content')
    if not isinstance(answer,str) or not answer.strip():raise Halt('EMPTY_CONTENT')
    return {'raw_output':answer,'usage':u,'finish_reason':choices[0].get('finish_reason'),
            'model_returned':d.get('model'),'response_id':d.get('id'),
            'system_fingerprint':d.get('system_fingerprint'),'reasoning_tokens':reasoning,'cached_tokens':cached}
