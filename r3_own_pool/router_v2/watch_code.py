"""Resume train-only isolated code scoring as collection appends new responses."""
import argparse
import fcntl
import json
from pathlib import Path
import time
from .score_code import ROOT,run
from .embed_queries import write_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True)
    ap.add_argument('--interval',type=float,default=300.)
    ap.add_argument('--deadline-hours',type=float,default=24.)
    a=ap.parse_args()
    if a.interval<1 or a.deadline_hours<=0:raise ValueError('Invalid polling bounds')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    with (out/'WATCHER.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        deadline=time.monotonic()+a.deadline_hours*3600
        while time.monotonic()<deadline:
            try:
                result=run(ROOT/'data/cohort_full_v2',ROOT/'data/raw',out,ROOT/'router_v2/CODE_SANDBOX_PROBE_V3.json')
                done=result['missing_raw']==0
                write_json(out/'WATCHER_STATUS.json',dict(phase='RAW_COVERAGE_PROCESSED' if done else 'WAITING_FOR_MORE_TRAIN_RESPONSES',
                    updated_at=time.time(),summary=result,note='Deferred dependencies still require supplemental evaluation; this is not a formal gate.'))
                if done:return
            except BlockingIOError:pass
            except Exception as exc:
                write_json(out/'WATCHER_STATUS.json',dict(phase='BLOCKED',error_type=type(exc).__name__,updated_at=time.time()))
                raise
            time.sleep(a.interval)
        write_json(out/'WATCHER_STATUS.json',dict(phase='DEADLINE_REACHED',updated_at=time.time()))

if __name__=='__main__':main()
