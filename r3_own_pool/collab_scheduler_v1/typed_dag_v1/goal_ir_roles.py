"""Optional role-keyed Goal IR adapter; never infers or repairs producers."""
import copy
from .goal_ir import goal_ir_schema,OPERATIONS,ROLES,reject
from .service_schema import full_validate
ROLE_TYPES={'facts':['source_facts'],'expression':['expression'],'value':['calculated_value','verified_value']}
def role_schema(max_nodes=5):
 s=goal_ir_schema(max_nodes)
 for variant in s['properties']['steps']['items']['anyOf']:
  p=variant['properties'];op=p['operation']['enum'][0];roles=OPERATIONS[op][1]
  atom=copy.deepcopy(p['inputs']['items']);groups={}
  for role in roles:
   a=copy.deepcopy(atom);a['properties']['type']={'enum':ROLE_TYPES[role]}
   groups[role]=dict(type='array',minItems=1,maxItems=max_nodes if role=='facts' else 1,items=a)
  p['inputs']=dict(type='object',additionalProperties=False,required=list(roles),properties=groups)
 return s

def normalize_role_ir(plan,max_nodes=5):
 """Validate declarations and flatten explicit groups for the original compiler."""
 full_validate(plan,role_schema(max_nodes));out=copy.deepcopy(plan);links=[]
 for step in out['steps']:
  grouped=step['inputs'];flat=[]
  for role in OPERATIONS[step['operation']][1]:
   for value in grouped[role]:
    if ROLES[value['type']]!=role:reject('IR_ROLE_TYPE',step['ref'],'inputs.'+role,role,value['type'])
    flat.append(value);links.append(dict(consumer_ref=step['ref'],role=role,symbol=value['symbol']))
  step['inputs']=flat
 return out,dict(protocol='goal-symbol-roles.v1',explicit_links=links,invented_edges=0,semantic_guarantee=False)
