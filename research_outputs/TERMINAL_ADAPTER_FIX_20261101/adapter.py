"""Value-blind adapter: public slot schema + source text only; no Gold inputs."""
import hashlib
SLOT_KEYS={'fact_id','subject','predicate','unit','date_type','value_kind'}
def project_slots(facts):
    return [{k:f[k] for k in SLOT_KEYS if k in f} for f in facts]
def compact(text):
    positions=[i for i,c in enumerate(text) if not c.isspace()]
    return ''.join(text[i] for i in positions),positions

def locate(quote,sources,doc_hint=None,page_hint=None):
    if not isinstance(quote,str) or not quote.strip():return None,'EMPTY_QUOTE'
    needle,_=compact(quote);hits=[]
    # A valid ID restricts the search. Unknown node-like hints are never guessed.
    docs=[(doc_hint,sources[doc_hint])] if doc_hint in sources else list(sources.items())
    for did,doc in docs:
        for page,rec in doc.get('pages',{}).items():
            if page_hint is not None and str(page)!=str(page_hint):continue
            text=rec.get('text')
            if not isinstance(text,str):return None,'INVALID_SOURCE_TEXT'
            if not doc.get('raw_sha256') or rec.get('page_sha256')!=hashlib.sha256(text.encode()).hexdigest():
                return None,'INVALID_SOURCE_HASH'
            hay,pos=compact(text);start=0
            while (index:=hay.find(needle,start))>=0:
                end=index+len(needle)
                hits.append(dict(doc_id=did,page=int(page),quote=quote,start=pos[index],end=pos[end-1]+1,
                                 raw_sha256=doc['raw_sha256'],page_sha256=rec['page_sha256']))
                start=index+1
    if len(hits)!=1:return None,'AMBIGUOUS_QUOTE' if hits else 'QUOTE_NOT_FOUND'
    return hits[0], 'UNIQUE_FULL_QUOTE'

def adapt(payload,slots,sources):
    if any(set(s)-SLOT_KEYS for s in slots):raise ValueError('PRIVATE_OR_UNDECLARED_SLOT_FIELDS')
    ids=[s.get('fact_id') for s in slots]
    if len(ids)!=len(set(ids)) or None in ids:raise ValueError('INVALID_PUBLIC_SLOT_IDS')
    byid={s['fact_id']:s for s in slots};issues=[];claims=[]
    if not isinstance(payload,dict):raise ValueError('PAYLOAD_NOT_OBJECT')
    items=payload.get('answers',payload.get('claims'))
    if not isinstance(items,list):raise ValueError('CLAIMS_NOT_ARRAY')
    for i,a in enumerate(items):
        if not isinstance(a,dict):raise ValueError('CLAIM_NOT_OBJECT')
        fid=a.get('fact_id');slot=byid.get(fid)
        c={'claim_id':f'claim_{i}','fact_id':fid,'material':True,'value':a.get('value'),'citations':[]}
        if slot is None:issues.append({'index':i,'reason':'UNKNOWN_FACT_ID'})
        else:
            for field in ('subject','predicate','unit','date_type'):
                if field in a and field in slot and a[field]!=slot[field]:
                    issues.append({'index':i,'reason':'EXPLICIT_SLOT_CONFLICT','field':field})
                # Explicit contradictory output must never be silently corrected.
                if field in a:c[field]=a[field]
                elif field in slot:c[field]=slot[field]
        citations=a.get('citations')
        if citations is None:citations=[{'doc_id':a.get('doc'),'quote':a.get('quote')}]
        if not isinstance(citations,list):raise ValueError('CITATIONS_NOT_ARRAY')
        for cit in citations:
            if not isinstance(cit,dict):raise ValueError('CITATION_NOT_OBJECT')
            # Old adapter defaulted page=1 even when no source was resolved. Only
            # trust page as a restriction when the source ID actually exists.
            did=cit.get('doc_id',cit.get('doc'))
            match,reason=locate(cit.get('quote'),sources,did,cit.get('page') if did in sources else None)
            issues.append({'index':i,'citation_result':reason,'original_doc_hint':did})
            if match:c['citations'].append(match)
        claims.append(c)
    return {'delivery_valid':payload.get('delivery_valid',True) is True,
            'claims_complete':payload.get('claims_complete',payload.get('complete',False)) is True,
            'claims':claims,'abstentions':payload.get('abstentions',[]),
            'abstentions_complete':payload.get('abstentions_complete',False) is True,
            'conflict_acknowledgements':payload.get('conflict_acknowledgements',[])},issues
