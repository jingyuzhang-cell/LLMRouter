#!/usr/bin/env python3
"""Real-time progress for the paired decomposition benchmark.

Usage:  watch -n 15 -c 'python3 /root/r3_own_pool/static_dag_v0/decomposition_benchmark/progress.py'
Or run once for a snapshot.
"""
import json
import time
from collections import Counter
from pathlib import Path

D = Path('/root/r3_own_pool/static_dag_v0/decomposition_benchmark/paired_run')
STAGES = ['mono', 'ext', 'rsnL', 'rsnM']
TOTAL = 300  # tasks; full call plan: mono 300 + ext 300 + rsnL 300 + rsnM 300 (ext fail => rsn skipped)


def snapshot():
    req = [json.loads(l) for l in (D / 'REQUESTS.jsonl').open()] if (D / 'REQUESTS.jsonl').exists() else []
    rsp = sum(1 for _ in (D / 'RESPONSES.jsonl').open()) if (D / 'RESPONSES.jsonl').exists() else 0
    stage = Counter()
    dom = Counter()
    models = Counter()
    for r in req:
        parts = r['key'].split(':')
        stage[parts[2] if len(parts) > 2 else parts[-1]] += 1
        dom[parts[0]] += 1
        models[r['model']] += 1
    plan = 300 + 300 + 300  # mono+ext+rsnL on large; rsnM extra up to 300
    done = (D / 'DONE.json').exists() or (D / 'PAIR_RUN_DONE.json').exists() or any(p.name.endswith('DONE.json') for p in D.glob('*.json') if 'DONE' in p.name)
    status = {}
    f = D / 'STATUS.json'
    if f.exists():
        try:
            status = json.loads(f.read_text())
        except Exception:
            pass
    now = time.time()
    age = now - (D / 'RESPONSES.jsonl').stat().st_mtime if (D / 'RESPONSES.jsonl').exists() else -1
    print('=' * 62)
    print('paired decomposition benchmark  |  %s' % time.strftime('%H:%M:%S'))
    print('=' * 62)
    for s in STAGES:
        bar = '#' * int(stage.get(s, 0) / 3) + '.' * (100 - int(stage.get(s, 0) / 3))
        print('%-5s %3d/300 [%s]' % (s, stage.get(s, 0), bar))
    print('-' * 62)
    print('requests: %d   responses: %d   (plan ~= 1200, fewer if extraction fails)' % (len(req), rsp))
    print('by domain: %s   models so far: %s' % (dict(dom), dict(models)))
    if status:
        print('runner STATUS.json: %s' % json.dumps({k: status[k] for k in list(status)[:5]}, ensure_ascii=False))
    print('last response %ds ago   %s' % (max(0, int(age)), '*** RUN COMPLETE ***' if done else 'running...' if age < 120 else '!! idle >2min — possibly switching models or stalled'))


if __name__ == '__main__':
    snapshot()
