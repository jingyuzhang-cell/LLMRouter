"""Source-only evidence identities for a future protocol, not retrospective repair."""
import hashlib,json,re

def digest(x):return hashlib.sha256(x.encode('utf-8')).hexdigest()
def identifier(doc,page,start,end,raw,text_hash):
    return 'ev_'+digest(json.dumps([doc,str(page),start,end,raw,text_hash],ensure_ascii=False,separators=(',',':')))

def build_registry(sources,max_chars=512):
    if type(max_chars) is not int or max_chars<1:raise ValueError('BAD_CHUNK_LIMIT')
    registry={}
    for did,doc in sorted(sources.items()):
        raw=doc.get('raw_sha256')
        if not isinstance(raw,str) or not re.fullmatch('[0-9a-f]{64}',raw):raise ValueError('RAW_HASH_MISSING')
        for page,rec in sorted(doc.get('pages',{}).items(),key=lambda x:int(x[0])):
            text=rec['text'];th=digest(text)
            if rec.get('page_sha256')!=th:raise ValueError('PAGE_HASH_MISMATCH')
            # Mechanical source segmentation, never around Gold answers. Break
            # on Chinese sentence endings; long sentences remain bounded chunks.
            bounds=[0]+[m.end() for m in re.finditer('[。！？；]',text)]+[len(text)]
            for left,right in zip(bounds,bounds[1:]):
                for start in range(left,right,max_chars):
                    end=min(start+max_chars,right);quote=text[start:end]
                    if not quote.strip():continue
                    eid=identifier(did,page,start,end,raw,th)
                    registry[eid]=dict(evidence_id=eid,doc_id=did,page=int(page),start=start,end=end,
                                       quote=quote,raw_sha256=raw,page_sha256=th)
    return registry

def resolve(eid,registry,sources):
    if eid not in registry:raise ValueError('UNKNOWN_EVIDENCE_ID')
    r=registry[eid];doc=sources.get(r['doc_id'],{});pages=doc.get('pages',{})
    page=pages.get(str(r['page']),pages.get(r['page']))
    if not page:raise ValueError('SOURCE_PAGE_MISSING')
    text=page['text']
    if doc.get('raw_sha256')!=r['raw_sha256'] or digest(text)!=r['page_sha256'] or page.get('page_sha256')!=r['page_sha256']:
        raise ValueError('SOURCE_VERSION_MISMATCH')
    if identifier(r['doc_id'],r['page'],r['start'],r['end'],r['raw_sha256'],r['page_sha256'])!=eid:
        raise ValueError('REGISTRY_ID_MISMATCH')
    if not 0<=r['start']<r['end']<=len(text) or text[r['start']:r['end']]!=r['quote']:
        raise ValueError('REGISTRY_SPAN_MISMATCH')
    return {k:v for k,v in r.items() if k!='evidence_id'}

def bind_claim_citations(payload,registry,sources):
    """New-protocol answers require evidence_ids. No inference from fact_id/value."""
    out=json.loads(json.dumps(payload,ensure_ascii=False));diagnostics=[]
    answers=out.get('answers')
    if not isinstance(answers,list):raise ValueError('ANSWERS_NOT_ARRAY')
    for i,answer in enumerate(answers):
        if not isinstance(answer,dict):raise ValueError('ANSWER_NOT_OBJECT')
        if any(k in answer for k in ('citations','quote','doc')):raise ValueError('MIXED_CITATION_PROTOCOL')
        ids=answer.pop('evidence_ids',None)
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) for x in ids):
            raise ValueError('EVIDENCE_IDS_REQUIRED')
        if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_EVIDENCE_IDS')
        answer['citations']=[resolve(eid,registry,sources) for eid in ids]
        diagnostics.append({'answer_index':i,'evidence_ids':ids,'location_valid':True,
                            'semantic_support':'NOT_DETERMINED_BY_REGISTRY'})
    return out,diagnostics

def adapt_registered(payload,slots,registry,sources):
    from adapter import adapt
    bound,locations=bind_claim_citations(payload,registry,sources)
    metadata=json.loads(json.dumps(bound,ensure_ascii=False))
    for a in metadata['answers']:a['citations']=[]
    terminal,issues=adapt(metadata,slots,sources)
    for c,a in zip(terminal['claims'],bound['answers']):c['citations']=a['citations']
    return terminal,{'locations':locations,'slot_issues':issues}
