"""Merge transport-rescue rows into the reasoning slot after collection ends.

Runs only when the main reasoning collector is terminal (not COLLECTING) and
its job lock is free. Replaces each quality=null row whose key has a rescued
row with quality!=null; positions whose rescue also failed stay missing
(never zero). Recomputes the slot status and writes a merge audit. Analysis
and validation must then be run manually.
"""
import argparse
import fcntl
import json
import time

from .collect_label_repair import read
from .data import sha
from .label_repair_plan import OUT

FILE = OUT / 'raw/reasoning.jsonl'
RESCUE = OUT / 'raw/reasoning_RESCUE.jsonl'
STATUS = OUT / 'raw/reasoning_STATUS.json'


def run():
    status = json.loads(STATUS.read_text())
    if status.get('phase') == 'COLLECTING':
        raise RuntimeError('Main reasoning collector still running')
    with (OUT / 'raw/reasoning.lock').open('a+') as job:
        try:
            fcntl.flock(job, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('reasoning.lock is held; collector may still be draining')
        rows = read(FILE)
        rescued = read(RESCUE)
        by_key = {(r['query_id'], r['repeat_index']): r for r in rescued}
        if len(by_key) != len(rescued):
            raise ValueError('Duplicate rescue key')
        merged, replaced, still_missing = [], [], []
        for row in rows:
            key = (row['query_id'], row['repeat_index'])
            if row.get('quality') is None and key in by_key:
                if by_key[key].get('quality') is None:
                    still_missing.append(key)
                    merged.append(row)
                else:
                    merged.append(by_key[key])
                    replaced.append(dict(query_id=key[0], repeat_index=key[1],
                                         rescued_quality=by_key[key]['quality'],
                                         attempt_status=by_key[key]['status'],
                                         amendment=by_key[key].get('amendment')))
            else:
                merged.append(row)
        keys = [(r['query_id'], r['repeat_index']) for r in merged]
        if len(keys) != len(set(keys)):
            raise ValueError('Duplicate final generation key after merge')
        tmp = FILE.with_suffix('.tmp')
        tmp.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in merged))
        tmp.replace(FILE)
        failures = sum(r.get('quality') is None for r in merged)
        n_target = len(read(OUT / 'PANEL.jsonl')) * 10
        STATUS.write_text(json.dumps(dict(slot='reasoning',
                                          phase='COMPLETE' if not failures and len(merged) == n_target else 'FAILED',
                                          unix_time=time.time(), completed=len(merged), target=n_target,
                                          failures=failures,
                                          merged_from='AMENDMENT_001_TRANSPORT_RESCUE'), indent=2) + '\n')
        audit = dict(replaced=replaced, still_missing=[list(k) for k in still_missing],
                     attempts_total=len(read(OUT / 'raw/reasoning_ATTEMPTS.jsonl')) + len(read(OUT / 'raw/reasoning_ATTEMPTS_RESCUE.jsonl')),
                     merged_file_sha256=sha(FILE), merge_unix_time=time.time())
        (OUT / 'raw/reasoning_MERGE_AUDIT.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(audit, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['run'])
    ap.parse_args()
    run()


if __name__ == '__main__':
    main()
