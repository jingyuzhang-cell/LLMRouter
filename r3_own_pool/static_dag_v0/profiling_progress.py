"""Live progress view for the capability profiling collection. Run anytime:
   python3 -m r3_own_pool.static_dag_v0.profiling_progress"""
import json
import time
from collections import Counter

from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT, N_TASKS, POOL

def run():
    req = OUT / 'REQUESTS.jsonl'
    n = N_TASKS
    per = Counter()
    fails = 0
    first_ts = last_ts = None
    if req.exists():
        for l in req.read_text().splitlines():
            r = json.loads(l)
            key = r['key']; stage, rest = key.split(':', 1)
            m = r['model']
            per[(stage, m)] += 1
            ts = None
            first_ts = first_ts or ts
            last_ts = key
        last_line = json.loads(req.read_text().splitlines()[-1])
        last_ts = last_line.get('unix_time') or last_line.get('response', {}).get('start_unix')
    total = sum(per.values())
    expected = n * 2 * len(POOL)  # extraction + reasoning per model
    print('=' * 56)
    print(f'Capability Profiling 采集进度   {time.strftime("%H:%M:%S")}')
    print('=' * 56)
    done = (OUT / 'COLLECT_DONE.json').exists()
    print(f'总调用: {total} / {expected}  ({total / expected * 100:.1f}%)' + ('  [完成]' if done else ''))
    print('-' * 56)
    for m in POOL:
        e = per.get(('EXT', m), 0); r = per.get(('RSN', m), 0)
        print(f'  {m:8} extraction {e:>4}/{n}   reasoning {r:>4}/{n}')
    print('-' * 56)
    fails_f = OUT / 'INFRA_FAILURES.jsonl'
    nf = sum(1 for _ in fails_f.open()) if fails_f.exists() else 0
    print(f'基础设施失败(已跳过): {nf}')
    if last_ts:
        age = time.time() - last_ts
        print(f'最近调用: {age:.0f} 秒前')
        rate = total / max(1, (time.time() - start_time_of_run()))
        remain = (expected - total) / max(rate, 0.1)
        print(f'速率: {rate:.1f} calls/min   预计剩余: {remain / 60:.0f} 分钟')
    print('=' * 56)

_CACHE = {}
def start_time_of_run():
    from .recovery_matrix_v2_devset import BASE
    req = BASE / 'capability_profiling/REQUESTS.jsonl'
    if 't' not in _CACHE:
        import os
        _CACHE['t'] = os.path.getmtime(req) if req.exists() else time.time()
    return _CACHE['t']

if __name__ == '__main__':
    run()
