"""Pure request/response helpers for the bounded planning-only HTTP diagnosis."""
import json,hashlib
from .protocol import canonical,Limits,validate
from .service_schema import full_validate,to_service_schema
from .goal_ir import compile_goal_ir
from .producer_plan import compile_producer_plan,verify_producer_bindings
from .semantic_ids import assemble_semantic

def call_key(uid):
    if not isinstance(uid,str) or not uid or ':' in uid:raise ValueError('Exact diagnostic UID required')
    return 'typed:generate:v1:generate:0:'+uid

def build_request(served,prompt,full_schema):
    if not isinstance(served,str) or not served or not isinstance(prompt,str) or not prompt:raise ValueError('Model and prompt required')
    service,audit=to_service_schema(full_schema)
    payload=dict(model=served,messages=[dict(role='user',content=prompt)],temperature=0,top_p=1,max_tokens=768,stream=False,response_format=dict(type='json_schema',json_schema=dict(name='diagnostic_plan',strict=True,schema=service)))
    return payload,audit

def decode_response(data,served):
    if not isinstance(data,dict) or data.get('model')!=served:raise ValueError('Provider identity mismatch')
    choices=data.get('choices');usage=data.get('usage')
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):raise ValueError('Malformed provider choices')
    if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens','total_tokens')) or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:raise ValueError('Malformed provider usage; reservation retained')
    choice=choices[0];content=choice.get('message',{}).get('content')
    if not isinstance(content,str) or not content:raise ValueError('Malformed provider content')
    return dict(status='delivered',answer=content,usage=usage,finish_reason=choice.get('finish_reason'),provider_model=data['model'])

def assess_plan(text,finish_reason,mode,full,task):
    r=dict(json_complete=False,full_schema_pass=False,legal_dag=False,error=None)
    try:plan=json.loads(text);r['json_complete']=True
    except (ValueError,TypeError) as exc:r['error']=dict(error_code='RESPONSE_JSON_INVALID',message=str(exc));return r,None
    if finish_reason=='length':r['error']=dict(error_code='GENERATION_TRUNCATED');return r,None
    try:
        full_validate(plan,full);r['full_schema_pass']=True
        if mode=='goal_ir':plan,_=compile_goal_ir(plan,limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5))
        elif mode!='semantic':raise ValueError('Unknown planning mode')
        plan,evidence=compile_producer_plan(plan);g=assemble_semantic(plan,task['task_id'],task['context'],task['required_outputs'],limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5));verify_producer_bindings(g,evidence);validate(g,task['required_outputs'],Limits(max_nodes=5,max_depth=5,max_llm_calls=5));r['legal_dag']=True;return r,g
    except (ValueError,TypeError,KeyError) as exc:r['error']=getattr(exc,'feedback',dict(error_code='PLANNING_INVALID',message=str(exc)));return r,None
