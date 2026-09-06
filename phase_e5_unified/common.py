"""Frozen E5 common metrics, prompts, and leakage-safe request features."""
import json
import numpy as np
from phase_e4_0.execution_controls import parse_json_object,canonicalize_node_output,node_schema_valid
MODELS=('deepseek-chat','glm-5.2','qwen-plus','qwen-turbo')
NODES=('N1','N2','N3','N4')
WEIGHTS={'Q':[1,0,0,0],'Q+T':[.7,0,.3,0],'Q+C+T+R':[.45,.2,.15,.2]}
LADDERS={'N1':(16384,32768,65536),'N2':(4096,8192,16384,32768),'N3':(1600,3200,6400,12800),'N4':(1200,2400,4800,9600)}
FINAL='Return exactly one JSON object with exactly these keys: answer (non-empty string), citations (list of source-reference strings), confidence (number between 0 and 1). No markdown. Do not introduce unsupported facts.'
def whole_prompt(task):
 return f"QUESTION:\n{task['question']}\n\nTASK_CONTEXT:\n{task['context']}\n\nTABLE:\n{json.dumps(task.get('table') or [],ensure_ascii=False)}\n\nINSTRUCTION:\nAnswer the financial question using only the supplied context and table. Include the calculation and final conclusion in answer; state evidence limitations when needed.\n{FINAL}"
def delivery(raw,provider_success=True,binding=False):
 obj,valid,_=parse_json_object(raw)
 obj,_=canonicalize_node_output('N4',obj)
 ok=bool(provider_success and valid and node_schema_valid('N4',obj,valid) and not binding)
 return ok,obj

def components(q,c,t,r):
 return np.array([q,1-min(c/.02,1),1-min(t/10000,1),float(r)],dtype=float)
def vector(task,model,node,fields):
 f=task['observable_features']
 return [float(f.get(k,0) or 0) for k in fields]+[float(model==m) for m in MODELS]+[float(node==n) for n in NODES]
