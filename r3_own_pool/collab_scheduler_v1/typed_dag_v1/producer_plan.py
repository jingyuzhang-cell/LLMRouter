"""One source of edges: explicit semantic input producer selections.

No producer discovery, fuzzy matching, added nodes or invented edges. Existing
legacy dependency plans remain diagnostic-compatible, explicitly labelled.
"""
import copy
from .protocol import CONTRACTS
from .semantic_validation import SemanticErrors,issue

# Wire types remain the executable v1 protocol. Semantic output kinds distinguish
# facts, unevaluated expressions, calculated numbers and verified numbers.
OUTPUT_KINDS={'extraction':'source_fact','reasoning':'calculation_expression',
              'transformation':'calculated_result','verification':'verification_result'}
ROLE_TYPES={'facts':'facts','expression':'expression','value':'number'}
ROLE_KINDS={'facts':('source_fact',),'expression':('calculation_expression',),
            'value':('calculated_result','verification_result')}

def producer_type_issue(consumer,producer,role,outputs,producer_type):
    error=issue('PRODUCER_TYPE_MISMATCH',consumer,[producer],missing=role,
                expected=ROLE_TYPES[role],actual=sorted(outputs),field='input_producers.'+role)
    error.update(producer_ref=producer,producer_output_type=sorted(outputs),
                 producer_output_kind=OUTPUT_KINDS.get(producer_type,'unregistered'),
                 consumer_ref=consumer,expected_input_type=ROLE_TYPES[role],
                 accepted_input_kinds=list(ROLE_KINDS[role]),offending_port=role)
    return error
ROLE_SETS={'extraction':(set(),),'reasoning':({'facts'},),'transformation':({'facts','expression'},),'verification':({'value'},{'facts','expression'})}


def compile_producer_plan(plan,registry=None):
    registry=CONTRACTS if registry is None else registry
    if not isinstance(plan,dict) or not isinstance(plan.get('nodes'),list):return copy.deepcopy(plan),dict(protocol='legacy_dependencies_diagnostic',invented_edges=0)
    if not any(isinstance(n,dict) and 'input_producers' in n for n in plan['nodes']):
        return copy.deepcopy(plan),dict(protocol='legacy_dependencies_diagnostic',invented_edges=0)
    normalized=copy.deepcopy(plan);errors=[];selections={}
    groups={}
    for n in plan['nodes']:
        if isinstance(n,dict):groups.setdefault(n.get('ref',n.get('id')),[]).append(n)
    for n in normalized['nodes']:
        if not isinstance(n,dict):continue
        ref=n.get('ref',n.get('id'));inputs=n.pop('input_producers',None)
        if 'dependencies' in n:
            errors.append(issue('DUPLICATE_DEPENDENCY_REPRESENTATION',ref,expected='input_producers only; dependencies are program-derived',actual=n['dependencies'],field='dependencies'))
        if not isinstance(inputs,dict) or set(inputs) not in ROLE_SETS.get(n.get('type'),()):
            errors.append(issue('INPUT_PRODUCER_FORMAT',ref,expected=[sorted(s) for s in ROLE_SETS.get(n.get('type'),())],actual=inputs,field='input_producers'));continue
        selected=[]
        for role,refs in inputs.items():
            if not isinstance(refs,list) or not refs or any(not isinstance(r,str) for r in refs) or len(set(refs))!=len(refs) or (role!='facts' and len(refs)!=1):
                errors.append(issue('INPUT_PRODUCER_FORMAT',ref,expected='facts: nonempty unique refs; expression/value: one exact ref',actual=refs,field='input_producers.'+role));continue
            selected.extend(refs)
            for producer in refs:
                entries=groups.get(producer,[])
                # Missing/ambiguous references are caught by the full preflight.
                if len(entries)!=1:continue
                outputs={kind for _,(typ,_,ports) in registry.items() if typ==entries[0].get('type') for kind in ports.values()}
                if ROLE_TYPES[role] not in outputs or OUTPUT_KINDS.get(entries[0].get('type')) not in ROLE_KINDS[role]:
                    errors.append(producer_type_issue(ref,producer,role,outputs,entries[0].get('type')))
        # Union is a derived graph edge set, not deletion of declared relations:
        # each per-role relation is retained separately below and verified.
        n['dependencies']=sorted(set(selected));selections[ref]=copy.deepcopy(inputs)
    if errors:raise SemanticErrors(errors)
    return normalized,dict(protocol='explicit_input_producers.v1',input_producers=selections,invented_edges=0,declared_relations=sum(len(v) for inputs in selections.values() for v in inputs.values()))


def verify_producer_bindings(graph,evidence):
    if evidence['protocol']!='explicit_input_producers.v1':return
    mapping=graph.provenance['semantic_ref_map']
    for ref,inputs in evidence['input_producers'].items():
        node=next(n for n in graph.nodes if n.node_id==mapping[ref])
        actual={}
        for b in node.inputs:
            if b.source=='node':actual.setdefault(b.port,[]).append(b.node_id)
        expected={role:sorted(mapping[r] for r in refs) for role,refs in inputs.items()}
        if {k:sorted(v) for k,v in actual.items()}!=expected:
            raise SemanticErrors([issue('PRODUCER_BINDING_MISMATCH',ref,expected=expected,actual=actual,field='inputs')])


def producer_schema(types,max_nodes):
    from .semantic_ids import semantic_schema
    schema=semantic_schema(types,max_nodes)
    variants=[]
    for v in schema['properties']['nodes']['items']['anyOf']:
        typ=v['properties']['type']['enum'][0]
        v['properties'].pop('dependencies');v['required'].remove('dependencies');v['required'].append('input_producers')
        for roles in ROLE_SETS[typ]:
            item=copy.deepcopy(v)
            item['description']='Output semantic kind: '+OUTPUT_KINDS[typ]+'. All declared nodes must reach a final output via explicit producer selections.'
            item['properties']['input_producers']=dict(type='object',required=sorted(roles),additionalProperties=False,properties={r:dict(type='array',minItems=1,maxItems=max_nodes-1 if r=='facts' else 1,uniqueItems=True,items={'type':'string','minLength':1},description='Exact locally defined producer refs; expected wire type '+ROLE_TYPES[r]+'; accepted semantic kinds '+','.join(ROLE_KINDS[r])) for r in roles})
            variants.append(item)
    schema['properties']['nodes']['items']['anyOf']=variants
    return schema


def guard_raw_repair(previous,repaired,task_id,limits):
    """Protect identities and explicitly stated relations even after compile error."""
    from .semantic_ids import guard_semantic_repair
    def view(p):
        q=copy.deepcopy(p)
        if not isinstance(q,dict) or not isinstance(q.get('nodes'),list):return q
        for n in q['nodes']:
            if not isinstance(n,dict):continue
            inputs=n.pop('input_producers',None)
            if isinstance(inputs,dict):
                refs=[r for values in inputs.values() if isinstance(values,list) for r in values if isinstance(r,str)]
                n['dependencies']=sorted(set(refs))
        return q
    guard_semantic_repair(view(previous),view(repaired),task_id,limits)
