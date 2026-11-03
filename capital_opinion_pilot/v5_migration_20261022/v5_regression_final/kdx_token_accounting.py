"""Offline-only request construction and strict token-accounting comparison."""
MODEL='Qwen/Qwen2.5-7B-Instruct'
def build_request(ids,max_tokens=8):
 if not ids or any(type(i)!=int or i<0 for i in ids):raise ValueError('INTEGER_PROMPT_REQUIRED')
 if type(max_tokens)!=int or not 1<=max_tokens<=8:raise ValueError('OUTPUT_CAP')
 if len(ids)+max_tokens>16384:raise ValueError('CONTEXT_CAP')
 return {'model':MODEL,'prompt':list(ids),'max_tokens':max_tokens,'temperature':0,'n':1,'stream':False,'echo':False,'add_special_tokens':False,'return_token_ids':True}
def compare(request,response):
 if response.get('model')!=request['model']:raise ValueError('MODEL_IDENTITY')
 choices=response.get('choices',[])
 if len(choices)!=1:raise ValueError('CHOICE_COUNT')
 c=choices[0];u=response.get('usage',{});out=c.get('token_ids');inp=c.get('prompt_token_ids')
 if not isinstance(out,list) or any(type(i)!=int or i<0 for i in out):raise ValueError('OUTPUT_IDS_MISSING')
 if len(out)>request['max_tokens']:raise ValueError('OUTPUT_BOUND_VIOLATION')
 if any(type(u.get(k))!=int or u[k]<0 for k in ('prompt_tokens','completion_tokens','total_tokens')):raise ValueError('UNKNOWN_USAGE_RETAIN_FULL_RESERVE')
 if u['prompt_tokens']!=len(request['prompt']) or u['completion_tokens']!=len(out) or u['total_tokens']!=len(request['prompt'])+len(out):raise ValueError('USAGE_COUNT_MISMATCH')
 if inp is None:return {'status':'COUNT_ONLY','input_id_equality':'UNKNOWN','output_tokens':len(out)}
 if inp!=request['prompt']:raise ValueError('INPUT_ID_MISMATCH')
 return {'status':'TOKEN_IDS_AND_USAGE_MATCH','input_id_equality':True,'output_tokens':len(out),'finish_reason':c.get('finish_reason'),'boundary':'server-reported IDs, not independent GPU instrumentation'}
