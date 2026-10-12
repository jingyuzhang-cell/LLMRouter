"""Bounded coverage review; model opinions never establish task correctness."""
import json
from .protocol import ValidationError

class ReviewError(ValidationError):
    def __init__(self,code,message):
        super().__init__(message)
        self.feedback=dict(error_code=code,node_ref=None,field='semantic_review',repairable=True,actual_value=message)

def review_schema(graph,required):
    ids=[n.node_id for n in graph.nodes]
    return dict(type='object',additionalProperties=False,required=['status','error_code','node_refs','evidence','replan'],properties=dict(
        status=dict(type='string',enum=['PASS','FAIL']),
        error_code=dict(type='string',enum=['NONE','SOURCE_MISSING','SUBTASK_IRRELEVANT','OUTPUT_UNSUPPORTED','OTHER']),
        node_refs=dict(type='array',maxItems=len(ids),items=dict(type='string',enum=ids)),
        evidence=dict(type='string',maxLength=160),replan=dict(type='boolean')))

def parse_review(raw,graph,required,finish_reason=None):
    if finish_reason=='length':raise ReviewError('SEMANTIC_REVIEW_TRUNCATED','Provider finish_reason=length')
    try:r=json.loads(raw.strip().removeprefix('```json').removesuffix('```').strip())
    except (ValueError,TypeError) as e:raise ReviewError('SEMANTIC_REVIEW_FORMAT',str(e)) from e
    # Historical Stub responses remain diagnostic-compatible, never HTTP schema outputs.
    if isinstance(r,dict) and 'covered' in r:
        from .semantic_ids import resolve_review_references
        r=resolve_review_references(r,graph)
        ids={n.node_id for n in graph.nodes}
        if type(r.get('covered')) is not bool or not isinstance(r.get('reason'),str) or not isinstance(r.get('requirements'),dict) or set(r['requirements'])!=set(required) or any(not isinstance(v,list) or not v or any(x not in ids for x in v) for v in r['requirements'].values()):raise ReviewError('SEMANTIC_REVIEW_SCHEMA','Invalid legacy review')
        if not r['covered']:raise ReviewError('SEMANTIC_REVIEW_REJECTED',r['reason'])
        return dict(**r,protocol='legacy_review_diagnostic')
    ids={n.node_id for n in graph.nodes}
    if not isinstance(r,dict) or set(r)!={'status','error_code','node_refs','evidence','replan'} or r['status'] not in ('PASS','FAIL') or r['error_code'] not in ('NONE','SOURCE_MISSING','SUBTASK_IRRELEVANT','OUTPUT_UNSUPPORTED','OTHER') or type(r['replan']) is not bool or not isinstance(r['evidence'],str) or len(r['evidence'])>160 or not isinstance(r['node_refs'],list) or len(r['node_refs'])>len(ids) or any(x not in ids for x in r['node_refs']):raise ReviewError('SEMANTIC_REVIEW_SCHEMA','Compact review does not satisfy contract')
    if r['status']=='FAIL':raise ReviewError('SEMANTIC_REVIEW_REJECTED',r['error_code']+': '+r['evidence'])
    if r['error_code']!='NONE' or r['replan']:raise ReviewError('SEMANTIC_REVIEW_SCHEMA','PASS contradicts error or replan')
    return r
