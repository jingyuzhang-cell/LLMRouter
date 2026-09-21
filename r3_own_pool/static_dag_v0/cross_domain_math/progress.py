#!/usr/bin/env python3
import json, time
from collections import Counter
from pathlib import Path
D = Path('/root/r3_own_pool/static_dag_v0/cross_domain_math')
req = [json.loads(l) for l in (D/'REQUESTS.jsonl').open()] if (D/'REQUESTS.jsonl').exists() else []
stage = Counter(r['key'].split(':')[0] for r in req)
models = Counter(r['model'] for r in req)
done = (D/'DONE.json').exists()
age = time.time() - (D/'RESPONSES.jsonl').stat().st_mtime if (D/'RESPONSES.jsonl').exists() else -1
print('='*60)
print('Math500 six-arm  |  %s' % time.strftime('%H:%M:%S'))
for s, tot, label in [('M', 600, 'mono(3 arms x200)'), ('X', 200, 'extract'),
                      ('S', 200, 'solve-init'), ('V', 200, 'verify-init')]:
    n = stage.get(s, 0)
    print('%-16s %4d/%-4d %s' % (label, n, tot, '#'*int(n*30/max(tot,1))))
adapt = sum(v for k, v in stage.items() if k in ('XS','SD','XD','VS','VD') or ':' in k and k.split(':')[1] in ('s','d'))
print('adaptation calls: %d (static+dynamic extras, budget ~800)' % adapt)
print('models so far: %s   last response %ds ago  %s' % (
    dict(models), max(0,int(age)), '*** DONE ***' if done else 'running...' if age < 180 else '!! idle >3min'))
