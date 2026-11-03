"""Offline preparation and opt-in local completion transport; never starts service."""
import json,time,urllib.request
from strict_meter import StrictMeter

def render_tokens(tokenizer,system,user):
 return tokenizer.apply_chat_template([{'role':'system','content':system},{'role':'user','content':user}],tokenize=True,add_generation_prompt=True)

def attach_local_transport(meter,tokenizer,served_model,endpoint,context_limit=8192):
 if type(meter) is not StrictMeter:raise ValueError('STRICT_METER_REQUIRED')
 if not endpoint.startswith('http://127.0.0.1:'):raise ValueError('LOCAL_ENDPOINT_REQUIRED')
 def transport(alias,system,user,max_tokens,timeout_s):
  if alias!='local_qwen7b':raise ValueError('LOCAL_MODEL_ALIAS_REQUIRED')
  ids=render_tokens(tokenizer,system,user)
  if len(ids)+max_tokens>context_limit:raise ValueError('CONTEXT_CAP')
  # Integer-token completion bypasses server chat template; no hidden system fields.
  body={'model':served_model,'prompt':ids,'max_tokens':max_tokens,'temperature':0,'stream':False}
  req=urllib.request.Request(endpoint+'/v1/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
  start=time.monotonic()
  with urllib.request.urlopen(req,timeout=timeout_s) as r:data=json.loads(r.read())
  if data.get('model')!=served_model:raise ValueError('SERVICE_MODEL_MISMATCH')
  return {'usage':{'input_tokens':data['usage']['prompt_tokens'],'output_tokens':data['usage']['completion_tokens']},'text':data['choices'][0]['text'],'stop_reason':'max_tokens' if data['choices'][0]['finish_reason']=='length' else data['choices'][0]['finish_reason'],'latency_s':time.monotonic()-start}
 meter._transport=transport
 return lambda system,user:len(render_tokens(tokenizer,system,user))
