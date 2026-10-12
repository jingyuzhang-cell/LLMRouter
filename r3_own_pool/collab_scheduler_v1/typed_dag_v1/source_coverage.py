"""Exact public-source tracing; declared coverage is not semantic completeness."""
import hashlib
from .protocol import digest,CONTRACTS
from .semantic_validation import SemanticErrors,issue

def manifest(context):
    rows=[]
    for field,text in sorted(context.items()):
        if field=='question':continue
        if field not in ('ctx_table','ctx_text') or not isinstance(text,str):
            raise ValueError('Only registered public context sources')
        # Whole-field record plus exact line spans (multiple table/text fragments).
        rows.append(dict(source_id=field,field=field,start=0,end=len(text),text=text,sha256=hashlib.sha256(text.encode()).hexdigest()))
        offset=0
        for index,line in enumerate(text.splitlines(keepends=True)):
            rows.append(dict(source_id=f'{field}:line:{index}',field=field,start=offset,end=offset+len(line),text=line,sha256=hashlib.sha256(line.encode()).hexdigest()));offset+=len(line)
    return dict(protocol='public-source-manifest.v1',sources=rows,content_sha=digest(rows),semantic_completeness='NOT_ESTABLISHED')

def validate_requirements(required,source_manifest):
    if required is None:return None
    if not isinstance(required,list) or not required:raise ValueError('Nonempty declared required-data list or None')
    sources={s['source_id']:s for s in source_manifest['sources']};seen=set()
    for r in required:
        if not isinstance(r,dict) or set(r)!={'data_id','source_id','evidence'} or any(not isinstance(v,str) or not v for v in r.values()):
            raise ValueError('Required data needs exact data_id/source_id/evidence, never values or gold')
        if r['data_id'] in seen:raise ValueError('Duplicate required-data ID')
        seen.add(r['data_id']);s=sources.get(r['source_id'])
        if s is None or r['evidence'] not in s['text']:
            raise SemanticErrors([issue('SOURCE_EVIDENCE_INVALID',field='required_source_data',expected='exact evidence in declared public source',actual=r)])
    return required

def audit_graph_sources(graph,source_manifest,required=None):
    required=validate_requirements(required,source_manifest);sources={s['source_id']:s for s in source_manifest['sources']}
    nodes={n.node_id:n for n in graph.nodes};active=set();pending=[f.node_id for f in graph.final_outputs]
    while pending:
        uid=pending.pop()
        if uid in active:continue
        active.add(uid);pending.extend(nodes[uid].dependencies)
    bound=[]
    for n in graph.nodes:
        if n.node_type!='extraction':continue
        for b in n.inputs:
            if b.source=='task' and b.port=='context':
                if b.field not in sources:raise SemanticErrors([issue('SOURCE_BINDING_MISSING',n.node_id,field='context',actual=b.field)])
                bound.append(dict(node_id=n.node_id,source_id=b.field,contributes_to_final=n.node_id in active))
    lineage={f.name:sorted({r['source_id'] for r in bound if r['node_id'] in ancestors(f.node_id,nodes)}) for f in graph.final_outputs}
    evidence=[]
    for r in required or []:
        source=sources[r['source_id']];producers=[b['node_id'] for b in bound if b['source_id']==source['field'] and b['contributes_to_final']]
        evidence.append(dict(data_id=r['data_id'],source_id=r['source_id'],producer_nodes=producers,status='SOURCE_PATH_PRESENT' if producers else 'REQUIRED_SOURCE_MISSING'))
    missing=[r for r in evidence if not r['producer_nodes']]
    return dict(protocol='declared-source-coverage.v1',bindings=bound,final_source_lineage=lineage,required_data=evidence,
                source_complete='DECLARED_SOURCE_PATHS_PRESENT' if required and not missing else 'FAIL' if missing else 'PENDING_SEMANTIC_REVIEW',
                semantic_review='REQUIRED_NOT_PROOF',fact_correctness='NOT_ESTABLISHED',errors=[issue('REQUIRED_SOURCE_MISSING',field='required_source_data',actual=r) for r in missing])

def ancestors(uid,nodes):
    seen=set();pending=[uid]
    while pending:
        u=pending.pop()
        if u in seen:continue
        seen.add(u);pending.extend(nodes[u].dependencies)
    return seen

def audit_plan_sources(plan,source_manifest,required=None):
    """Same source-path rule before final ID allocation/contract assembly."""
    from types import SimpleNamespace as S
    nodes=[S(node_id=n.get('ref',n.get('id')),node_type=n['type'],dependencies=n.get('dependencies',[]),inputs=[S(source='task',port='context',field=n.get('context_field'))] if n['type']=='extraction' else []) for n in plan['nodes']]
    finals=[S(name=f['name'],node_id=f.get('node_ref',f.get('node_id'))) for f in plan['final_outputs']]
    return audit_graph_sources(S(nodes=nodes,final_outputs=finals),source_manifest,required)
