"""Append-only train/validation math+knowledge scoring, never run candidate code.

Each cache key binds source query/ground-truth, exact raw response, and scorer code.
Missing, failed and unparseable answers remain explicit, never silently dropped.
"""
import argparse
from collections import Counter
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from .data import load_cohort, sha
from .core import SLOTS

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'collect'))
import storage
spec=importlib.util.spec_from_file_location('r3_frozen_metrics',ROOT/'collect/metrics.py')
metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def score(source, raw):
    dataset=source['dataset']
    if dataset not in ('gsm8k','mmlupro'):
        return None
    # Failure quality policy is fixed before this new development scoring run.
    if raw.get('status')=='failed' or not raw.get('answer'):
        return dict(quality=0.,evaluation_status='generation_failure',parse_succeeded=False)
    if raw.get('status') not in ('ok','truncated','parse_failed'):
        raise ValueError('Unrecognized generation status')
    if dataset=='gsm8k':
        value=metrics.exact_match_math(raw['answer'],source['ground_truth'])
    else:
        value=metrics.option_match(raw['answer'],source['ground_truth'])
    return dict(quality=float(value) if value is not None else 0.,
                evaluation_status='scored' if value is not None else 'answer_parse_failed',
                parse_succeeded=value is not None)


def run(cohort_dir, raw_dir, output, partition='train'):
    if partition not in ('train','validation','test'):
        raise ValueError('Unknown partition; test requires the operator-authorized sealed run')
    cohort,split=load_cohort(cohort_dir)
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    lock=(out/'scoring.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    protocol=dict(partition=partition,cohort_sha256=sha(Path(cohort_dir)/'queries.jsonl'),
        split_sha256=sha(Path(cohort_dir)/'split.json'),scorer_sha256=sha(Path(__file__)),
        metrics_sha256=sha(ROOT/'collect/metrics.py'),datasets=['gsm8k','mmlupro'],
        failure_policy='No-answer/failed generation and unparseable final answer score zero; flags retained.',
        truncation_policy='Score delivered answer as-is; retain raw truncated status; no correctness-based retries.',
        skipped=['mbpp/humaneval: audited OS sandbox required','arenahard: full-answer resumable judge required'],
        role='development labels only; incomplete matrix; not formal training gate')
    protocol_path=out/'PROTOCOL.json'
    if protocol_path.exists():
        if json.loads(protocol_path.read_text())!=protocol:
            raise ValueError('Scoring protocol changed; use a new output directory')
    else:
        with protocol_path.open('x') as f:json.dump(protocol,f,indent=2)
    cache=out/'SCORES.jsonl'
    seen=set()
    if cache.exists():
        with cache.open() as f:
            for line in f:
                if line.strip():seen.add(json.loads(line)['key'])
    count=Counter();sources=Counter();new=0
    expected=set(split[partition])
    protocol_hash=digest(protocol)
    with cache.open('a') as stream:
        for slot in SLOTS:
            current=storage.canonical_rows(Path(raw_dir)/f'{slot}.jsonl')
            for qid in split[partition]:
                source=cohort[qid]
                if source['dataset'] not in ('gsm8k','mmlupro'):
                    continue
                if qid not in current:
                    count['missing_response']+=1;continue
                raw=current[qid]
                key=digest(dict(source=source,raw=raw,slot=slot,protocol_hash=protocol_hash))
                if key in seen:
                    count['cached']+=1;continue
                result=score(source,raw)
                record=dict(key=key,query_id=qid,slot=slot,dataset=source['dataset'],
                    partition=partition,response_sha256=digest(raw),source_sha256=digest(source),
                    protocol_hash=protocol_hash,generation_status=raw.get('status'),**result)
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
                stream.flush()
                new+=1;count[result['evaluation_status']]+=1;sources[source['dataset']]+=1
    report=dict(updated_at=time.time(),partition=partition,new_records=new,
                counts=dict(count),new_by_source=dict(sources),cache_total_records=len(seen)+new,
                non_scored_datasets=['mbpp','humaneval','arenahard'],
                training_ready=False,note='Coverage only: no quality aggregates or test outcomes reported.')
    tmp=out/'STATUS.tmp';tmp.write_text(json.dumps(report,indent=2));tmp.replace(out/'STATUS.json')
    lock.close()
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--cohort',default=str(ROOT/'data/cohort_full_v2'))
    ap.add_argument('--raw',default=str(ROOT/'data/raw'))
    ap.add_argument('--output',required=True)
    ap.add_argument('--partition',choices=('train','validation'),default='train')
    a=ap.parse_args()
    print(json.dumps(run(a.cohort,a.raw,a.output,a.partition),indent=2))

if __name__=='__main__':main()
