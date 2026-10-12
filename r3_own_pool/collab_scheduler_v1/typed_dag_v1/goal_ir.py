"""Optional symbol-based semantic IR -> existing explicit producer plan -> Graph.

Symbols are typed whole contract outputs, not per-fact IDs or numeric answers.
No producer inference beyond exact symbol identity, coercion or graph template.
"""
import copy
from .protocol import Limits
from .semantic_validation import SemanticErrors,issue,validate_semantic_plan
from .producer_plan import compile_producer_plan

OPERATIONS={
 'extract':('extraction',(), 'source_facts'),
 'form_expression':('reasoning',('facts',),'expression'),
 'calculate':('transformation',('facts','expression'),'calculated_value'),
 'verify_value':('verification',('value',),'verified_value'),
 'verify_expression':('verification',('facts','expression'),'verified_value'),
}
ROLES={'source_facts':'facts','expression':'expression','calculated_value':'value','verified_value':'value'}

def reject(code,ref=None,field=None,expected=None,actual=None):
    raise SemanticErrors([issue(code,ref,field=field,expected=expected,actual=actual)])

def symbol(record,ref,field):
    if not isinstance(record,dict) or set(record)!={'symbol','type','unit'}:
        reject('IR_SYMBOL_FORMAT',ref,field,'{symbol,type,unit}',record)
    if any(not isinstance(record[k],str) or not record[k].strip() or record[k]!=record[k].strip() for k in record):
        reject('IR_SYMBOL_FORMAT',ref,field,'exact nonempty strings',record)
    if record['type'] not in ROLES:reject('IR_SYMBOL_TYPE',ref,field,sorted(ROLES),record['type'])
    return record

def compile_goal_ir(ir,registry=None,limits=Limits()):
    if not isinstance(ir,dict) or set(ir)!={'final_goal','steps'}:reject('IR_FORMAT',field='root',expected=['final_goal','steps'],actual=ir)
    steps=ir['steps'];goal=ir['final_goal']
    if not isinstance(steps,list) or not 1<=len(steps)<=limits.max_nodes:reject('IR_STEP_COUNT',field='steps',expected=f'1..{limits.max_nodes}',actual=steps)
    if not isinstance(goal,dict) or set(goal)!={'description','outputs'} or not isinstance(goal['description'],str) or not goal['description'].strip() or not isinstance(goal['outputs'],list) or not goal['outputs']:
        reject('IR_FINAL_GOAL',field='final_goal',actual=goal)
    refs={};symbols={}
    for step in steps:
        if not isinstance(step,dict) or set(step)-{'ref','operation','description','inputs','outputs','context_field'} or not {'ref','operation','description','inputs','outputs'}<=set(step):reject('IR_STEP_FORMAT',field='steps',actual=step)
        ref=step['ref']
        if not isinstance(ref,str) or not ref.strip() or ref!=ref.strip():reject('IR_REF',field='ref',actual=ref)
        if ref in refs:reject('IR_AMBIGUOUS_REF',ref,'ref',actual=ref)
        refs[ref]=step
        if not isinstance(step['operation'],str) or step['operation'] not in OPERATIONS:reject('IR_OPERATION',ref,'operation',sorted(OPERATIONS),step['operation'])
        if not isinstance(step['description'],str) or not step['description'].strip():reject('IR_DESCRIPTION',ref,'description',actual=step['description'])
        if not isinstance(step['inputs'],list) or not isinstance(step['outputs'],list) or len(step['outputs'])!=1:reject('IR_IO_FORMAT',ref,'inputs/outputs','inputs list and one whole-contract output',step)
        output=symbol(step['outputs'][0],ref,'outputs');expected=OPERATIONS[step['operation']][2]
        if output['type']!=expected:reject('IR_OPERATION_OUTPUT_TYPE',ref,'outputs',expected,output['type'])
        key=output['symbol']
        if key in symbols:reject('IR_AMBIGUOUS_PRODUCER',ref,'outputs.symbol','one producer per exact symbol',key)
        symbols[key]=dict(producer=ref,**output)
    nodes=[];relations=[]
    for ref,step in refs.items():
        typ,required,_=OPERATIONS[step['operation']];inputs={};seen=set()
        for inp in step['inputs']:
            inp=symbol(inp,ref,'inputs');key=inp['symbol']
            if key in seen:reject('IR_DUPLICATE_INPUT',ref,'inputs.symbol',actual=key)
            seen.add(key)
            if key not in symbols:reject('IR_MISSING_PRODUCER',ref,'inputs.symbol',sorted(symbols),key)
            producer=symbols[key]
            if producer['type']!=inp['type']:reject('IR_TYPE_MISMATCH',ref,'inputs.type',producer['type'],inp['type'])
            if producer['unit']!=inp['unit']:reject('IR_UNIT_MISMATCH',ref,'inputs.unit',producer['unit'],inp['unit'])
            inputs.setdefault(ROLES[inp['type']],[]).append(producer['producer'])
            relations.append(dict(consumer=ref,producer=producer['producer'],symbol=key,type=inp['type'],unit=inp['unit']))
        if set(inputs)!=set(required):reject('IR_OPERATION_INPUTS',ref,'inputs',list(required),list(inputs))
        if step['operation'] in ('calculate','verify_value','verify_expression'):
            expected_type='expression' if step['operation']!='verify_value' else None
            anchor=[x for x in step['inputs'] if (x['type']==expected_type if expected_type else x['type'] in ('calculated_value','verified_value'))]
            if len(anchor)==1 and step['outputs'][0]['unit']!=anchor[0]['unit']:
                reject('IR_IMPLICIT_UNIT_CONVERSION',ref,'outputs.unit',anchor[0]['unit'],step['outputs'][0]['unit'])
        row=dict(ref=ref,name=step['description'],type=typ,subtask=step['description'],input_producers=inputs)
        if typ=='extraction':
            if step.get('context_field') not in ('ctx_table','ctx_text'):reject('IR_SOURCE_FIELD',ref,'context_field',['ctx_table','ctx_text'],step.get('context_field'))
            row['context_field']=step['context_field']
        elif 'context_field' in step:reject('IR_SOURCE_FIELD',ref,'context_field','only extraction may select context',step['context_field'])
        nodes.append(row)
    finals=[];names=set()
    for final in goal['outputs']:
        if not isinstance(final,dict) or set(final)!={'name','symbol','type','unit'}:reject('IR_FINAL_OUTPUT_FORMAT',field='final_goal.outputs',actual=final)
        name=final['name']
        if not isinstance(name,str) or not name.strip() or name in names:reject('IR_FINAL_OUTPUT_NAME',field='final_goal.outputs.name',actual=name)
        names.add(name);record=symbol({k:final[k] for k in ('symbol','type','unit')},None,'final_goal.outputs')
        producer=symbols.get(record['symbol'])
        if producer is None:reject('IR_GOAL_UNCOVERED',field='final_goal.outputs.symbol',actual=record['symbol'])
        if any(producer[k]!=record[k] for k in ('type','unit')):reject('IR_GOAL_TYPE_UNIT',field='final_goal.outputs',expected=producer,actual=record)
        finals.append(dict(name=name,node_ref=producer['producer']))
    raw=dict(nodes=nodes,final_outputs=finals)
    plan,_=compile_producer_plan(raw,registry);validate_semantic_plan(plan,registry,limits)
    return raw,dict(protocol='goal-symbol-ir.v1',symbol_table=symbols,relations=relations,final_goal=copy.deepcopy(goal),invented_edges=0,semantic_guarantee=False)

def guard_goal_repair(previous,repaired):
    """Preserve declared steps/outputs and existing explicitly typed inputs.

    Conservative prototype: correcting a cyclic known-symbol dependency can be
    rejected; never silently remove a necessary dependency to pass a test.
    """
    if not isinstance(previous,dict) or not isinstance(previous.get('steps'),list):return
    if previous.get('final_goal')!=repaired.get('final_goal'):
        reject('IR_REPAIR_CHANGED_GOAL',field='final_goal')
    old={s.get('ref'):s for s in previous['steps'] if isinstance(s,dict) and isinstance(s.get('ref'),str)}
    new={s.get('ref'):s for s in repaired.get('steps',[]) if isinstance(s,dict)}
    if len(old)!=len(previous['steps']):reject('IR_REPAIR_AMBIGUOUS_IDENTITY',field='steps')
    known={o.get('symbol') for s in old.values() for o in s.get('outputs',[]) if isinstance(o,dict)}
    for ref,s in old.items():
        if ref not in new:reject('IR_REPAIR_REMOVED_STEP',ref,'steps')
        if s.get('description')!=new[ref].get('description') or s.get('outputs')!=new[ref].get('outputs'):reject('IR_REPAIR_CHANGED_REQUIRED_OUTPUT',ref,'outputs/description')
        old_inputs={x.get('symbol') for x in s.get('inputs',[]) if isinstance(x,dict)} & known
        new_inputs={x.get('symbol') for x in new[ref].get('inputs',[]) if isinstance(x,dict)}
        if not old_inputs<=new_inputs:reject('IR_REPAIR_REMOVED_INPUT',ref,'inputs',sorted(old_inputs),sorted(new_inputs))

def goal_ir_schema(max_nodes=5):
    atom=dict(type='object',required=['symbol','type','unit'],additionalProperties=False,properties=dict(symbol={'type':'string','minLength':1},type={'enum':sorted(ROLES)},unit={'type':'string','minLength':1}))
    variants=[]
    for op,(typ,roles,outkind) in OPERATIONS.items():
        props=dict(ref={'type':'string','minLength':1},operation={'enum':[op]},description={'type':'string','minLength':1},inputs=dict(type='array',maxItems=max_nodes,items=copy.deepcopy(atom)),outputs=dict(type='array',minItems=1,maxItems=1,items=copy.deepcopy(atom)))
        # Transport-compatible necessary constraints; compiler still checks exact roles.
        allowed={'extract':[], 'form_expression':['source_facts'],
                 'calculate':['source_facts','expression'],
                 'verify_value':['calculated_value','verified_value'],
                 'verify_expression':['source_facts','expression']}[op]
        if allowed:props['inputs']['items']['properties']['type']={'enum':allowed}
        props['inputs']['minItems']=len(roles)
        if op=='verify_value':props['inputs']['maxItems']=1
        props['outputs']['items']['properties']['type']={'enum':[outkind]}
        required=list(props)
        if typ=='extraction':props['context_field']={'enum':['ctx_table','ctx_text']};required.append('context_field');props['inputs']['maxItems']=0
        variants.append(dict(type='object',required=required,additionalProperties=False,properties=props))
    final=copy.deepcopy(atom);final['required'].append('name');final['properties']['name']={'type':'string','minLength':1}
    return dict(type='object',required=['final_goal','steps'],additionalProperties=False,properties=dict(final_goal=dict(type='object',required=['description','outputs'],additionalProperties=False,properties=dict(description={'type':'string','minLength':1},outputs=dict(type='array',minItems=1,items=final))),steps=dict(type='array',minItems=1,maxItems=max_nodes,items={'anyOf':variants})))
