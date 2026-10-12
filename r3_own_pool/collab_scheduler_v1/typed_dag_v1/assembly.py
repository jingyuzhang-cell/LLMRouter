"""Semantic plan -> existing Graph, by exact registered port types only."""
import re
from .protocol import Graph,Node,Binding,Output,CONTRACTS,ValidationError,validate,digest,Limits
from static_dag_v0.core import topology

class ConstraintError(ValidationError):
    def __init__(self,code,node_id=None,field=None,expected=None,actual=None,repairable=True):
        self.feedback=dict(error_code=code,node_id=node_id,field=field,expected_contract=expected,actual_contract=actual,repairable=repairable)
        super().__init__(str(self.feedback))

def assemble(plan,task_id,context,required_outputs,registry=None,limits=Limits()):
    registry=CONTRACTS if registry is None else registry
    if not isinstance(plan,dict) or set(plan)!={'nodes','final_outputs'}:raise ConstraintError('PLAN_FORMAT',field='root',expected=['nodes','final_outputs'])
    rows=plan['nodes']
    if not isinstance(rows,list) or not rows or len(rows)>limits.max_nodes:raise ConstraintError('NODE_COUNT',field='nodes',expected=f'1..{limits.max_nodes}')
    ids=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'id','type','subtask','dependencies','context_field'}:raise ConstraintError('PLAN_NODE_FORMAT',actual=row)
        u=row.get('id');ids.append(u)
        if not isinstance(u,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]*',u):raise ConstraintError('NODE_ID',actual=u)
        if row.get('type') not in {x[0] for x in registry.values()}:raise ConstraintError('NODE_TYPE',u,'type',sorted({x[0] for x in registry.values()}),row.get('type'))
        if not isinstance(row.get('subtask'),str) or not row['subtask'].strip():raise ConstraintError('SUBTASK',u,'subtask')
        deps=row.get('dependencies')
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):raise ConstraintError('DEPENDENCY_FORMAT',u,'dependencies',actual=deps)
    if len(set(ids))!=len(ids):raise ConstraintError('DUPLICATE_NODE',field='id')
    by_id={n['id']:n for n in rows}
    for row in rows:
        bad=[d for d in row['dependencies'] if d not in by_id or d==row['id']]
        if bad:raise ConstraintError('DEPENDENCY_REFERENCE',row['id'],'dependencies',ids,bad)
    try:layers=topology([dict(id=n['id'],deps=n['dependencies']) for n in rows])
    except ValueError as exc:raise ConstraintError('CYCLE',field='dependencies',actual=str(exc)) from exc
    built={};bindings_evidence={}
    for layer in layers:
        for u in layer:
            row=by_id[u];deps=row['dependencies'];options=[]
            for cid,(typ,ports,outputs) in registry.items():
                if typ!=row['type']:continue
                bindings=[];used=set();valid=True
                for port,dtype in ports.items():
                    if port=='question':bindings.append(Binding(port,'task','question'));continue
                    if port=='context':
                        field=row.get('context_field')
                        if field not in context or field not in ('ctx_table','ctx_text') or deps:valid=False;break
                        bindings.append(Binding(port,'task',field));continue
                    matches=[]
                    for d in deps:
                        for out,kind in registry[built[d].output_contract][2].items():
                            if kind==dtype:matches.append((d,out))
                    if not matches or (dtype!='facts' and len(matches)!=1):valid=False;break
                    for d,out in matches:bindings.append(Binding(port,'node',out,d));used.add(d)
                # Every proposed edge is used. Never discard an incompatible edge.
                if valid and used==set(deps):options.append((cid,bindings))
            if len(options)!=1:
                raise ConstraintError('CONTRACT_UNBINDABLE' if not options else 'CONTRACT_AMBIGUOUS',u,'dependencies',
                    {k:dict(type=v[0],inputs=v[1]) for k,v in registry.items() if v[0]==row['type']},
                    {d:registry[built[d].output_contract][2] for d in deps})
            cid,bindings=options[0]
            built[u]=Node(u,row['type'],row['subtask'],bindings,cid,list(deps))
            bindings_evidence[u]=cid
    finals=plan['final_outputs'];outputs=[]
    if not isinstance(finals,list):raise ConstraintError('FINAL_OUTPUT_FORMAT',field='final_outputs')
    for item in finals:
        if not isinstance(item,dict) or set(item)!={'name','node_id'} or item['node_id'] not in built:raise ConstraintError('FINAL_OUTPUT_REFERENCE',field='final_outputs',actual=item)
        ports=registry[built[item['node_id']].output_contract][2]
        if len(ports)!=1:raise ConstraintError('FINAL_OUTPUT_AMBIGUOUS',item['node_id'],'output')
        outputs.append(Output(item['name'],item['node_id'],next(iter(ports))))
    g=Graph('generated-'+digest(plan)[:16],'typed-dag.v1',1,task_id,[built[u] for u in ids],outputs,dict(origin='llm_semantic_plan_program_assembly',semantic_plan=plan,contract_bindings=bindings_evidence,semantic_guarantee=False))
    try:validate(g,required_outputs,limits)
    except ValidationError as exc:raise ConstraintError('GRAPH_VALIDATION',field='graph',actual=str(exc)) from exc
    return g

def plan_schema(types,max_nodes):
    variants=[]
    for typ in sorted(types):
        properties=dict(id={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'},type={'enum':[typ]},subtask={'type':'string'},dependencies={'type':'array','items':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'}})
        required=['id','type','subtask','dependencies']
        if typ=='extraction':
            properties['context_field']={'enum':['ctx_table','ctx_text']};required.append('context_field')
        variants.append(dict(type='object',required=required,additionalProperties=False,properties=properties))
    return dict(type='object',required=['nodes','final_outputs'],additionalProperties=False,properties=dict(
      nodes=dict(type='array',minItems=1,maxItems=max_nodes,items={'anyOf':variants}),
      final_outputs=dict(type='array',minItems=1,items=dict(type='object',required=['name','node_id'],additionalProperties=False,properties=dict(name={'type':'string'},node_id={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'})))))


def guard_repair(previous,repaired):
    """Conservative preservation: keep nodes and valid semantic edges.

    Dangling references may be replaced. Cycle edges may only be removed when
    their membership in a cycle is independently established. No edits applied.
    """
    if not isinstance(previous,dict) or not isinstance(previous.get('nodes'),list):return
    old={n.get('id'):n for n in previous['nodes'] if isinstance(n,dict) and isinstance(n.get('id'),str)}
    new={n.get('id'):n for n in repaired.get('nodes',[]) if isinstance(n,dict)}
    missing=set(old)-set(new)
    if missing:raise ConstraintError('REPAIR_REMOVED_NODE',field='nodes',expected=sorted(old),actual=sorted(new))
    def reaches(u,target,seen):
        if u==target:return True
        if u in seen or u not in old:return False
        seen.add(u)
        return any(reaches(d,target,seen) for d in old[u].get('dependencies',[]) if isinstance(d,str))
    for u,n in old.items():
        deps=n.get('dependencies',[])
        if not isinstance(deps,list):continue
        for d in deps:
            if isinstance(d,str) and d in old and d not in new[u].get('dependencies',[]):
                if not reaches(d,u,set()):raise ConstraintError('REPAIR_REMOVED_VALID_EDGE',u,'dependencies',deps,new[u].get('dependencies'))
