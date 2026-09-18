"""Dynamic v2 dev analysis: Static vs Dyn v1 vs Dyn v2 on the dev set (offline)."""
import json
from collections import defaultdict

from .recovery_matrix_v2_devset import BASE
from .tatqa_benchmark_build import literals
from .dynamic_v2_dev import OUT, POOL, close

def run():
    raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    pol = json.loads((OUT / 'DEV2_POLICY.json').read_text())
    tasks = pol['tasks']
    lat = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        if r['response'].get('latency_s') is not None: lat[r['key']] = r['response']['latency_s']
    arms = {}
    for a in pol['arms']:
        rows = []
        for t in tasks:
            uid = t['uid']; st = raw['arms'][a][uid]
            rows.append(dict(uid=uid, success=int(st['ok']), used=st['used'],
                             lat=sum(lat.get(k, 0) for k, _ in st['keys']),
                             resched=any(k.startswith(('C:', 'D:', 'E:')) for k, _ in st['keys']),
                             escalation=any(k.startswith('E:') for k, _ in st['keys']),
                             over_budget=st['used'] > raw['budgets'][uid] + 1e-9))
        arms[a] = rows
    n = len(tasks)
    def summ(rows):
        return dict(Q=round(sum(r['success'] for r in rows) / n, 4),
                    C=round(sum(r['used'] for r in rows) / n, 1),
                    L=round(sum(r['lat'] for r in rows) / n, 2),
                    budget_violation=round(sum(r['over_budget'] for r in rows) / n, 4),
                    resched_rate=round(sum(r['resched'] for r in rows) / n, 4),
                    escalations=sum(r['escalation'] for r in rows))
    S = arms['static']; V1 = arms['dynv1']; V2 = arms['dynv2']
    def pair(X, Y, base):
        help_ = [r['uid'] for r, b in zip(X, base) if b['success'] == 0 and r['success'] == 1]
        harm_ = [r['uid'] for r, b in zip(X, base) if b['success'] == 1 and r['success'] == 0]
        return dict(help=len(help_), harm=len(harm_), help_tasks=help_, harm_tasks=harm_)
    rep = dict(n=n, arms={a: summ(rows) for a, rows in arms.items()},
               vs_static=dict(dynv1=pair(V1, V1, S), dynv2=pair(V2, V2, S)),
               v2_vs_v1=dict(help=sum(1 for r, v in zip(V2, V1) if v['success'] == 0 and r['success'] == 1),
                             harm=sum(1 for r, v in zip(V2, V1) if v['success'] == 1 and r['success'] == 0)),
               detail=raw['arms'])
    (OUT / 'DEV2_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
