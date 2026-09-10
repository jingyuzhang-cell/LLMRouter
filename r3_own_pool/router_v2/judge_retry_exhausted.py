"""One-shot operator-approved retry for judge cells exhausted by transient API errors.

Only cells whose entire attempt history is transient judge_error events (HTTP
400/429/5xx or connection/timeout classes) with no grade and no generation
failure are eligible. Each receives exactly one extra attempt, preceded by an
explicit budget_amendment journal event; nothing is rewritten or deleted.
Basis for treating HTTP 400 as transient here: operator replayed byte-identical
requests successfully after cluster outages (see RETRY_AUDIT.json).
"""
import fcntl
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from dotenv import dotenv_values
from openai import OpenAI
from .judge_primary import append, messages, parse_grade, replay, digest, stable_key
from .embed_queries import write_json

ROOT=Path(__file__).resolve().parents[1]
TRANSIENT_HTTP={400,408,429,500,502,503,504}
TRANSIENT_TYPES={'APIConnectionError','APITimeoutError','InternalServerError','RateLimitError'}


def eligible(journal):
    counts,terminal=replay(journal)
    errs=defaultdict(list)
    for line in journal.read_text().split('\n'):
        if not line.strip():continue
        e=json.loads(line)
        if e['event']=='judge_error':errs[e['key']].append(e)
    picked={}
    for key,n in counts.items():
        if key in terminal or n<2 or key not in errs:continue
        events=errs[key]
        if len(events)!=n:continue  # mixed history: not purely error-exhausted
        if all(e.get('http_status') in TRANSIENT_HTTP or e.get('error_type') in TRANSIENT_TYPES for e in events):
            picked[key]=events
    return picked,counts,terminal


def main():
    if len(sys.argv)!=2:raise SystemExit('usage: python -m router_v2.judge_retry_exhausted <judge-output-dir>')
    out=Path(sys.argv[1]);journal=out/'ATTEMPTS.jsonl'
    key=os.environ.get('QWEN_API_KEY') or dotenv_values('/root/.env').get('QWEN_API_KEY')
    if not key:raise RuntimeError('Configured judge credential unavailable')
    client=OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',api_key=key,timeout=120,max_retries=0)
    with (out/'JUDGE.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        picked,counts,terminal=eligible(journal)
        # Task metadata (query text, answer) is rebuilt from the same bound inputs.
        from .data import load_cohort
        from .core import SLOTS
        sys.path.insert(0,str(ROOT/'collect'))
        import storage
        cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
        raw={s:storage.canonical_rows(ROOT/'data/raw'/f'{s}.jsonl') for s in SLOTS}
        meta={}
        for qid in sorted(split['train']):
            source=cohort[qid]
            if source['dataset']!='arenahard':continue
            for slot in SLOTS:
                if qid not in raw[slot]:continue
                response=raw[slot][qid]
                key_=stable_key(dict(source_sha256=digest(source),response_sha256=digest(response),slot=slot))
                meta[key_]=(source['query'],response,qid,slot,digest(source),digest(response))
        results=[];granted=0
        with journal.open('a') as stream:
            for key,events in sorted(picked.items()):
                if key not in meta:continue
                query,response,qid,slot,src_sha,resp_sha=meta[key]
                common=dict(key=key,query_id=qid,slot=slot,response_sha256=resp_sha,source_sha256=src_sha,
                    generation_status=response.get('status'))
                append(stream,dict(**common,event='budget_amendment',prior_attempts=counts[key],
                    reason='exhausted by transient API errors; operator-authorized single retry 2026-09-09',
                    prior_errors=[dict(error_type=e.get('error_type'),http_status=e.get('http_status')) for e in events],
                    time=time.time()))
                granted+=1
                counts[key]+=1
                request_messages=messages(query,response['answer'])
                append(stream,dict(**common,event='intent',attempt=counts[key],time=time.time(),
                    request_sha256=digest(request_messages),question_chars=len(query),answer_chars=len(response['answer'])))
                try:
                    result=client.chat.completions.create(model='qwen-max',temperature=0,
                        messages=request_messages,response_format={'type':'json_object'},max_tokens=256)
                    content=result.choices[0].message.content or ''
                    if result.choices[0].finish_reason!='stop':raise ValueError('Incomplete judge response')
                    grade=parse_grade(content)
                    event=dict(**common,event='grade',quality=grade['score']/10,rubric=grade,
                        attempt=counts[key],time=time.time(),usage=result.usage.model_dump() if result.usage else None)
                    append(stream,event);terminal[key]=event
                    results.append(dict(query_id=qid,slot=slot,outcome='graded',quality=event['quality']))
                except Exception as exc:
                    append(stream,dict(**common,event='judge_error',attempt=counts[key],time=time.time(),
                        error_type=type(exc).__name__,http_status=getattr(exc,'status_code',None)))
                    results.append(dict(query_id=qid,slot=slot,outcome='judge_error',
                        error_type=type(exc).__name__,http_status=getattr(exc,'status_code',None)))
        write_json(out/'RETRY_AUDIT.json',dict(granted=granted,results=results,
            policy='one extra attempt per cell; only purely transient-error-exhausted cells; append-only',
            basis='byte-identical replay succeeded after 400 clusters; all four cells 0462/0464/0466 in same outage windows',
            time=time.time()))
        print(json.dumps(dict(granted=granted,results=results),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
