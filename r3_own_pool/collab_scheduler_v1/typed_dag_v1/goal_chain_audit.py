"""Read-only declared-goal diagnostics. Never repairs a plan or certifies intent."""
import copy
from .protocol import Limits,CONTRACTS
from .goal_ir import compile_goal_ir,OPERATIONS,ROLES
from .goal_ir_roles import normalize_role_ir
from .producer_plan import compile_producer_plan
from .semantic_validation import inspect_semantic_plan,cycle_witnesses,issue
from .source_coverage import manifest,audit_plan_sources

def audit_goal_chain(candidate,mode,context,required_source_data=None,limits=Limits(max_nodes=5,max_depth=5,max_llm_calls=5)):
    result=dict(protocol='declared-goal-chain-audit.v1',mode=mode,errors=[],producer_definitions={},consumer_bindings=[],final_producers=[],reverse_chain={},
                static_status='NOT_ASSESSED',source_coverage='NOT_ASSESSED',operation_intent='REQUIRES_SEMANTIC_REVIEW',
                fact_truth='NOT_ASSESSED',expression_runtime_references='NOT_ASSESSED',invented_edges=0,modified_candidate=False)
    def error(exc):result['errors'].extend(getattr(exc,'feedback',{}).get('errors',[issue('AUDIT_INPUT_INVALID',actual=str(exc))]))
    plan=None
    if mode=='semantic':
        groups={}
        for n in candidate.get('nodes',[]):groups.setdefault(n.get('ref',n.get('id')),[]).append(n)
        result['producer_definitions']={str(k):[dict(node_ref=k,node_type=n.get('type')) for n in v] for k,v in groups.items()}
        for f in candidate.get('final_outputs',[]):
            ref=f.get('node_ref',f.get('node_id'));result['final_producers'].append(dict(name=f.get('name'),reference=ref,producer_refs=[ref] if len(groups.get(ref,[]))==1 else [],status='UNIQUE' if len(groups.get(ref,[]))==1 else 'MISSING_OR_AMBIGUOUS'))
        for n in candidate.get('nodes',[]):
            for role,refs in n.get('input_producers',{}).items():
                for ref in refs:result['consumer_bindings'].append(dict(consumer_ref=n.get('ref'),role=role,reference=ref,status='UNIQUE' if len(groups.get(ref,[]))==1 else 'MISSING_OR_AMBIGUOUS'))
        try:plan,_=compile_producer_plan(copy.deepcopy(candidate));result['errors'].extend(inspect_semantic_plan(plan,limits=limits))
        except (ValueError,TypeError,KeyError) as exc:error(exc)
    elif mode in ('goal_ir','goal_ir_roles'):
        flat=None
        try:
            flat=normalize_role_ir(candidate,limits.max_nodes)[0] if mode=='goal_ir_roles' else copy.deepcopy(candidate)
            plan,_=compile_goal_ir(flat,limits=limits)
            plan,_=compile_producer_plan(plan)
        except (ValueError,TypeError,KeyError) as exc:error(exc)
        # Inventory is evidence from raw declarations, independent of first-error compiler.
        definitions={};refs={}
        for step in candidate.get('steps',[]):
            refs.setdefault(step.get('ref'),[]).append(step)
            for out in step.get('outputs',[]):
                definitions.setdefault(out.get('symbol'),[]).append(dict(node_ref=step.get('ref'),operation=step.get('operation'),**out))
        result['producer_definitions']=definitions
        for key,defs in definitions.items():
            if len(defs)>1:result['errors'].append(issue('IR_AMBIGUOUS_PRODUCER',related=[str(x['node_ref']) for x in defs],field='outputs.symbol',actual=key,expected='one exact producer per symbol'))
        for step in candidate.get('steps',[]):
            inputs=step.get('inputs',[])
            if isinstance(inputs,dict):items=[(role,x) for role,xs in inputs.items() for x in xs]
            else:items=[(ROLES.get(x.get('type')),x) for x in inputs]
            for role,inp in items:
                defs=definitions.get(inp.get('symbol'),[]);status='UNIQUE' if len(defs)==1 else 'MISSING' if not defs else 'AMBIGUOUS'
                result['consumer_bindings'].append(dict(consumer_ref=step.get('ref'),role=role,reference=inp.get('symbol'),producer_refs=[d['node_ref'] for d in defs],status=status))
                if len(defs)!=1:result['errors'].append(issue('IR_MISSING_PRODUCER' if not defs else 'IR_AMBIGUOUS_PRODUCER',step.get('ref'),field='inputs.symbol',actual=inp.get('symbol'),expected='one exact typed producer'))
        for f in candidate.get('final_goal',{}).get('outputs',[]):
            defs=definitions.get(f.get('symbol'),[]);status='UNIQUE' if len(defs)==1 else 'MISSING' if not defs else 'AMBIGUOUS'
            result['final_producers'].append(dict(name=f.get('name'),reference=f.get('symbol'),producer_refs=[d['node_ref'] for d in defs],status=status))
            if len(defs)!=1:result['errors'].append(issue('IR_GOAL_UNCOVERED' if not defs else 'IR_AMBIGUOUS_PRODUCER',field='final_goal.outputs',actual=f.get('symbol'),expected='one exact final producer'))
    else:raise ValueError('Unsupported planning protocol')
    if plan is not None:
        nodes={n.get('ref',n.get('id')):n for n in plan['nodes']}
        edges={ref:n.get('dependencies',[]) for ref,n in nodes.items()}
        safe=len(nodes)==len(plan['nodes']) and all(d in nodes for ds in edges.values() for d in ds)
        if safe:
            result['cycle_paths']=cycle_witnesses(edges)
            for f in plan['final_outputs']:
                ref=f.get('node_ref',f.get('node_id'))
                if ref not in nodes:continue
                seen=set();todo=[ref]
                while todo:
                    u=todo.pop()
                    if u in seen:continue
                    seen.add(u);todo.extend(edges[u])
                result['reverse_chain'][f['name']]=sorted(seen)
            result['declared_edges_consumer_to_producer']=edges
            result['source_coverage']=audit_plan_sources(plan,manifest(context),required_source_data)
            result['errors'].extend(result['source_coverage']['errors'])
    result['errors']=list({str(e):e for e in result['errors']}.values())
    result['cycle_paths']=result.get('cycle_paths',[]) or [e['cycle_path'] for e in result['errors'] if e.get('cycle_path')]
    result['static_status']='FAIL' if result['errors'] else 'DECLARATIONS_CONSISTENT'
    result['llm_replanning_required']=bool(result['errors'])
    result['admission_status']='REJECT_STATIC' if result['errors'] else 'REQUIRES_SEMANTIC_REVIEW'
    return result
