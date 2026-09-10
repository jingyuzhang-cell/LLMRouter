"""Continue explicitly authorized train-only qwen-max scoring; never evaluate test."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import time
from .judge_full import ROOT, run
from .embed_queries import write_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True)
    ap.add_argument('--primary',action='store_true',help='Use hash-bound primary-score amendment and inherited attempt budget')
    ap.add_argument('--partition',default='train',choices=['train','validation','test'],help='train uses the amendment path; validation/test start a fresh primary-score journal (test only for the operator-authorized sealed run)')
    ap.add_argument('--deadline-hours',type=float,default=24.)
    ap.add_argument('--interval',type=float,default=300.)
    args=ap.parse_args()
    run_fn=run
    if args.primary:
        from .judge_primary import run_with_history
        run_fn=run_with_history
    elif args.partition!='train':
        from .judge_primary import run as run_primary
        def run_fn(c,r,o,cl,max_new_calls): return run_primary(c,r,o,cl,max_new_calls,partition=args.partition)
    if args.deadline_hours<=0 or args.interval<1:raise ValueError('Invalid polling limits')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    with (out/'WATCHER.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from dotenv import dotenv_values
        from openai import OpenAI
        key=os.environ.get('QWEN_API_KEY') or dotenv_values('/root/.env').get('QWEN_API_KEY')
        if not key:raise RuntimeError('Configured judge credential unavailable')
        client=OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',api_key=key,timeout=120,max_retries=0)
        deadline=time.monotonic()+args.deadline_hours*3600
        while time.monotonic()<deadline:
            try:
                result=run_fn(ROOT/'data/cohort_full_v2',ROOT/'data/raw',out,client,max_new_calls=4200)
                phase=result['phase']
                if phase=='CIRCUIT_OPEN':
                    write_json(out/'WATCHER_STATUS.json',dict(phase='BLOCKED_CONSECUTIVE_JUDGE_ERRORS',updated_at=time.time(),summary=result))
                    return
                if phase=='LABEL_COVERAGE_COMPLETE':
                    write_json(out/'WATCHER_STATUS.json',dict(phase='TRAIN_JUDGE_COVERAGE_COMPLETE',updated_at=time.time(),summary=result))
                    return
                if not result['missing_raw'] and result['exhausted_unscored']:
                    write_json(out/'WATCHER_STATUS.json',dict(phase='BLOCKED_EXHAUSTED_ATTEMPTS',updated_at=time.time(),summary=result))
                    return
                write_json(out/'WATCHER_STATUS.json',dict(phase='WAITING_FOR_MORE_TRAIN_RESPONSES',updated_at=time.time(),summary=result))
            except BlockingIOError:
                pass
            except Exception as exc:
                write_json(out/'WATCHER_STATUS.json',dict(phase='BLOCKED',error_type=type(exc).__name__,updated_at=time.time()))
                raise
            time.sleep(args.interval)
        write_json(out/'WATCHER_STATUS.json',dict(phase='DEADLINE_REACHED',updated_at=time.time()))

if __name__=='__main__':main()
