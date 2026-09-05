"""Strict, score-preserving normalization of observed judge transport formatting."""
import json
import re

def parse_scores(raw, labels):
    text=raw.strip()
    # Only repair literal newlines outside JSON strings, and JSON-invalid escaped apostrophes.
    out=[]; quoted=False; i=0
    while i<len(text):
        c=text[i]
        if c=='\\' and i+1<len(text):
            n=text[i+1]
            if not quoted and n in 'nrt': out.append({'n':'\n','r':'\r','t':'\t'}[n]);i+=2;continue
            if quoted and n=="'": out.append("'");i+=2;continue
            if quoted: out.extend((c,n));i+=2;continue
        if c=='"': quoted=not quoted
        out.append(c);i+=1
    text=''.join(out).strip()
    match=re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```',text,re.I)
    if match: text=match.group(1)
    obj=json.loads(text)
    rows=obj.get('scores') if isinstance(obj,dict) else obj
    if not isinstance(rows,list): raise ValueError('scores must be a list')
    if any(not isinstance(row,dict) for row in rows): raise ValueError('invalid row')
    got=[row.get('label') for row in rows]
    if len(got)!=len(labels) or set(got)!=set(labels): raise ValueError('missing/duplicate/unexpected labels')
    if any(type(row.get('score')) is not int or not 0<=row['score']<=4 or not isinstance(row.get('reason'),str) or not row['reason'].strip() for row in rows): raise ValueError('invalid score/reason')
    return {row['label']:row['score'] for row in rows}
