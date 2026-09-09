"""Continue authorized train-only deterministic scoring as raw collection arrives."""
import argparse
import fcntl
import json
from pathlib import Path
import time
from .score_available import run
from .embed_queries import write_json


def main():
    root=Path(__file__).resolve().parents[1]
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',default=str(root/'data/scored_train_v2'))
    ap.add_argument('--interval',type=float,default=300.)
    ap.add_argument('--deadline-hours',type=float,default=24.)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    if args.interval<1 or args.deadline_hours<=0:raise ValueError('Invalid polling bounds')
    with (out/'WATCHER.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        end=time.monotonic()+args.deadline_hours*3600
        while time.monotonic()<end:
            try:
                result=run(root/'data/cohort_full_v2',root/'data/raw',out)
                finished=result['counts'].get('missing_response',0)==0
                report=dict(updated_at=time.time(),phase='AUTO_LABEL_COVERAGE_COMPLETE' if finished else 'WAITING_FOR_MORE_RESPONSES',
                    scored_cache_records=result['cache_total_records'],missing=result['counts'].get('missing_response',0),
                    partition='train',formal_training_ready=False)
                write_json(out/'WATCHER_STATUS.json',report)
                print(json.dumps(report),flush=True)
                if finished:return
            except BlockingIOError:
                pass  # one-off scorer owns the lock; try next interval
            except Exception as exc:
                write_json(out/'WATCHER_STATUS.json',dict(phase='BLOCKED',reason=str(exc),updated_at=time.time()))
                raise
            time.sleep(args.interval)
        write_json(out/'WATCHER_STATUS.json',dict(phase='DEADLINE_REACHED',updated_at=time.time()))

if __name__=='__main__':main()
