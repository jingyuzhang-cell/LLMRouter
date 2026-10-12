"""Deterministic semantic-reference preflight, BEFORE contract assembly.

Edges are written consumer -> required producer. Cycle witnesses use this
orientation. This validates declared dependencies, never task semantics.
"""
from collections import Counter
from .assembly import ConstraintError
from .protocol import CONTRACTS,Limits,canonical,digest


def issue(code,ref=None,related=(),cycle=(),missing=None,expected=None,actual=None,field='dependencies'):
    return dict(error_code=code,node_ref=ref,related_refs=sorted(set(related)),
                cycle_path=list(cycle),missing_dependency=missing,
                expected_constraint=expected,actual_value=actual,field=field)


def error_signature(errors):
    # No raw JSON/text, row indices, cosmetic names, or exception prose.
    normalized=[]
    for error in errors:
        e=dict(error)
        if e.get('error_code')=='FINAL_OUTPUT_CONNECTIVITY':
            # Moving final_output between isolated nodes does not connect them.
            # Component structure is the actionable unchanged defect.
            e={k:e[k] for k in ('error_code','disconnected_components','declared_dependencies')}
        normalized.append(canonical(e))
    return digest(sorted(set(normalized)))


class SemanticErrors(ConstraintError):
    def __init__(self,errors):
        first=errors[0]
        super().__init__(first['error_code'],first['node_ref'],first['field'],first['expected_constraint'],first['actual_value'])
        self.feedback.update(first,errors=errors,error_signature=error_signature(errors))


def cycle_witnesses(edges):
    """DFS back-edge witnesses, deterministic O(V+E), not all simple cycles."""
    color={};stack=[];position={};cycles=set()
    def visit(u):
        color[u]=1;position[u]=len(stack);stack.append(u)
        for v in sorted(edges[u]):
            if color.get(v,0)==0:visit(v)
            elif color[v]==1:
                body=stack[position[v]:]
                rotations=[tuple(body[i:]+body[:i]) for i in range(len(body))]
                best=min(rotations);cycles.add(best+(best[0],))
        stack.pop();position.pop(u);color[u]=2
    for u in sorted(edges):
        if not color.get(u):visit(u)
    return [list(c) for c in sorted(cycles)]


def connectivity_errors(plan,groups,edges):
    """All declared nodes must contribute to at least one declared final output.

    This is structural coverage, not proof that all task requirements were named.
    Never infer a missing edge, drop a node, or reinterpret a final port.
    """
    finals=plan.get('final_outputs')
    if not isinstance(finals,list) or not finals:return []
    final_refs=[]
    for item in finals:
        if not isinstance(item,dict):return []
        ref=item.get('node_ref',item.get('node_id'))
        if not isinstance(ref,str) or ref not in edges:return []
        final_refs.append(ref)
    live=set()
    def visit(ref):
        if ref in live:return
        live.add(ref)
        for dep in edges[ref]:visit(dep)
    for ref in final_refs:visit(ref)
    dead=sorted(set(edges)-live)
    if not dead:return []
    adjacency={ref:set(deps) for ref,deps in edges.items()}
    consumers={ref:set() for ref in edges}
    for ref,deps in edges.items():
        for dep in deps:
            adjacency[dep].add(ref);consumers[dep].add(ref)
    components=[];remaining=set(edges)
    while remaining:
        todo=[min(remaining)];component=set()
        while todo:
            ref=todo.pop()
            if ref in component:continue
            component.add(ref);todo.extend(adjacency[ref]-component)
        remaining-=component;components.append(sorted(component))
    error=issue('FINAL_OUTPUT_CONNECTIVITY',related=dead,
                expected='every declared necessary node contributes along explicit dependencies to a final output',
                actual=dead,field='final_outputs')
    error.update(final_output_ref=sorted(set(final_refs)),unreachable_required_nodes=dead,
                 missing_consumer_or_aggregation=sorted(ref for ref in dead if not consumers[ref]),
                 disconnected_components=sorted(components),
                 declared_dependencies={ref:edges[ref] for ref in sorted(edges)})
    return [error]


def inspect_semantic_plan(plan,registry=None,limits=Limits()):
    registry=CONTRACTS if registry is None else registry
    errors=[]
    def add(*args,**kw):errors.append(issue(*args,**kw))
    if not isinstance(plan,dict) or set(plan)!={'nodes','final_outputs'}:
        return [issue('PLAN_FORMAT',expected=['nodes','final_outputs'],actual=sorted(plan) if isinstance(plan,dict) else type(plan).__name__,field='root')]
    rows=plan['nodes']
    if not isinstance(rows,list) or not 1<=len(rows)<=limits.max_nodes:
        return [issue('NODE_COUNT',expected=f'1..{limits.max_nodes}',actual=len(rows) if isinstance(rows,list) else type(rows).__name__,field='nodes')]
    groups={}
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'ref','id','name','type','subtask','dependencies','context_field'}:
            add('PLAN_NODE_FORMAT',expected='registered semantic plan fields',actual=sorted(row) if isinstance(row,dict) else type(row).__name__,field='node');continue
        ref=row.get('ref',row.get('id'))
        if not isinstance(ref,str) or not ref or ref!=ref.strip():
            add('SEMANTIC_REFERENCE_FORMAT',expected='nonempty exact local reference',actual=ref,field='ref');continue
        groups.setdefault(ref,[]).append(row)
    for ref,items in sorted(groups.items()):
        if len(items)>1:add('AMBIGUOUS_SEMANTIC_REFERENCE',ref,[ref],expected='one definition per ref; explicitly disambiguate all occurrences',actual=dict(ref=ref,definitions=len(items)),field='ref')
    for ref,items in sorted(groups.items()):
        for row in items:
            typ=row.get('type')
            if not isinstance(typ,str) or typ not in {v[0] for v in registry.values()}:
                add('NODE_TYPE',ref,expected=sorted({v[0] for v in registry.values()}),actual=typ,field='type')
            if not isinstance(row.get('subtask'),str) or not row['subtask'].strip():add('SUBTASK',ref,expected='nonempty subtask',actual=row.get('subtask'),field='subtask')
            deps=row.get('dependencies')
            if not isinstance(deps,list) or any(not isinstance(d,str) or not d for d in deps):
                add('DEPENDENCY_FORMAT',ref,expected='array of exact nonempty refs',actual=deps);continue
            duplicates=sorted(d for d,n in Counter(deps).items() if n>1)
            if duplicates:add('DEPENDENCY_FORMAT',ref,duplicates,expected='each dependency declared once',actual=dict(duplicate_dependencies=duplicates))
            for d in sorted(set(deps)):
                if d not in groups:add('DEPENDENCY_REFERENCE',ref,[d],missing=d,expected='dependency must name a defined unique ref',actual=d)
                elif len(groups[d])>1:add('AMBIGUOUS_DEPENDENCY',ref,[d],missing=d,expected='dependency resolves to exactly one definition',actual=dict(ref=d,definitions=len(groups[d])))
                if d==ref:add('CYCLE',ref,[ref],cycle=[ref,ref],expected='no self-dependency',actual=[ref,ref])
    edges={r:sorted(set(row[0]['dependencies'])) for r,row in groups.items() if len(row)==1 and isinstance(row[0].get('dependencies'),list) and all(isinstance(d,str) for d in row[0]['dependencies'])}
    # Exclude unresolved/ambiguous edges only for cycle DIAGNOSTICS. Never
    # normalize, remove, or admit these edges into the executable candidate.
    edges={u:[v for v in ds if v in edges and v!=u] for u,ds in edges.items()}
    for cycle in cycle_witnesses(edges):add('CYCLE',cycle[0],cycle[:-1],cycle=cycle,expected='acyclic dependency graph',actual=cycle)
    finals=plan['final_outputs']
    if not isinstance(finals,list) or not finals:
        add('FINAL_OUTPUT_FORMAT',expected='nonempty named final_outputs',actual=finals,field='final_outputs')
    else:
        for final in finals:
            if not isinstance(final,dict) or set(final) not in ({'name','node_ref'},{'name','node_id'}):
                add('FINAL_OUTPUT_FORMAT',expected='{name,node_ref}; ports assigned by registry',actual=final,field='final_outputs');continue
            ref=final.get('node_ref',final.get('node_id'))
            if not isinstance(ref,str) or ref not in groups or len(groups[ref])!=1:
                add('FINAL_OUTPUT_REFERENCE',related=[ref] if isinstance(ref,str) else [],missing=ref,expected='final output names one defined unique ref',actual=ref,field='final_outputs')
    if not any(e['error_code'] in ('PLAN_NODE_FORMAT','SEMANTIC_REFERENCE_FORMAT','AMBIGUOUS_SEMANTIC_REFERENCE','DEPENDENCY_FORMAT','DEPENDENCY_REFERENCE','AMBIGUOUS_DEPENDENCY','CYCLE','FINAL_OUTPUT_FORMAT','FINAL_OUTPUT_REFERENCE') for e in errors):
        errors.extend(connectivity_errors(plan,groups,edges))
    # Type-level necessary producers. No contracts are selected/bound here.
    # A contract remains possible only if every non-task input has producers
    # and every proposed edge can supply a required port.
    for ref,items in sorted(groups.items()):
        if len(items)!=1:continue
        row=items[0];deps=row.get('dependencies');typ=row.get('type')
        if not isinstance(deps,list) or any(not isinstance(d,str) or d not in groups or len(groups[d])!=1 for d in deps):continue
        candidates={cid:v for cid,v in registry.items() if v[0]==typ}
        if not candidates:continue
        possible=[];requirements={}
        for cid,(_,inputs,_) in candidates.items():
            consumed=set();deficits={}
            for port,dtype in inputs.items():
                if port in ('question','context'):continue
                matches=[d for d in deps if any(v[0]==groups[d][0].get('type') and dtype in v[2].values() for v in registry.values())]
                if not matches or (dtype!='facts' and len(matches)!=1):deficits[port]=dict(dtype=dtype,producers=sorted(matches),expected_count='>=1' if dtype=='facts' else 1)
                consumed.update(matches)
            extra=sorted(set(deps)-consumed)
            if 'context' in inputs and deps:extra=sorted(set(deps))
            if not deficits and not extra:possible.append(cid)
            requirements[cid]=dict(missing_or_ambiguous_producers=deficits,unexpected_dependencies=extra,inputs=inputs)
        if not possible:
            add('CONTRACT_UNBINDABLE',ref,deps,missing=requirements,expected='at least one registered contract has all required producers and consumes every edge',actual=dict(node_type=typ,dependencies=sorted(deps)),field='dependencies')
    # Keep structural references/cycles ahead of producer diagnostics.
    return list({canonical(e):e for e in errors}.values())


def validate_semantic_plan(plan,registry=None,limits=Limits()):
    errors=inspect_semantic_plan(plan,registry,limits)
    if errors:raise SemanticErrors(errors)
    return dict(valid=True,error_signature=error_signature([]))


def compare_errors(previous,current):
    old={canonical(e) for e in previous};new={canonical(e) for e in current}
    return dict(previous_signature=error_signature(previous),current_signature=error_signature(current),
                no_progress=bool(previous) and error_signature(previous)==error_signature(current),removed_errors=[__import__('json').loads(e) for e in sorted(old-new)],
                introduced_errors=[__import__('json').loads(e) for e in sorted(new-old)],
                interpretation='Structural error-set comparison, not semantic repair proof')
