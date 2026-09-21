"""Pre-registered analysis for the 120-task multinode DAG experiment.

Outputs CONFIRM_ANALYSIS.json with: main table (Q/C/L), paired delta-Q
bootstrap CI, McNemar exact, Help/Harm, per-node fallback/escalation counts,
selective-update audit (every adaptation event must have executed exactly the
failed node + its descendant closure), propagation length, budget violations.
Zero model calls.
"""
import json
import math
import random
import time
from collections import Counter

from . import core
from .multidag_dynamic import OUT, HEADROOM, CLOSURE

SEED = 20260918
B = 10000


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n * 2)


def run():
    raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    lat = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        if r['response'].get('latency_s') is not None:
            lat[r['key']] = r['response']['latency_s']
    S, D = [], []
    for t in tasks:
        uid = t['uid']
        for arm, rows in (('static', S), ('dynamic', D)):
            st = raw[arm][uid]
            rows.append(dict(uid=uid, success=int(st['ok']), r_ok=int(st['r_ok']),
                             keys=st['keys'], events=st['events'],
                             lat=sum(lat.get(k, 0) for k in st['keys'])))
    # recompute tokens from RESPONSES usage
    usage = {}
    for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        usage[r['key']] = float((r['response'].get('usage') or {}).get('total_tokens') or 0)
    for rows in (S, D):
        for r in rows:
            r['used'] = sum(usage.get(k, 0) for k in r['keys'])
    n = len(tasks)
    qS = sum(r['success'] for r in S) / n
    qD = sum(r['success'] for r in D) / n
    rng = random.Random(SEED)

    def ci(vals_a, vals_b):
        diffs = [a - b for a, b in zip(vals_a, vals_b)]
        boot = []
        for _ in range(B):
            s = [diffs[rng.randrange(n)] for _ in range(n)]
            boot.append(sum(s) / n)
        boot.sort()
        return [round(boot[int(0.025 * B)], 4), round(boot[int(0.975 * B) - 1], 4)]

    sa = [r['success'] for r in S]; da = [r['success'] for r in D]
    help_ids = [r['uid'] for r, s in zip(D, S) if s['success'] == 0 and r['success'] == 1]
    harm_ids = [r['uid'] for r, s in zip(D, S) if s['success'] == 1 and r['success'] == 0]
    b = len(help_ids); c = len(harm_ids)
    # --- selective-update audit ---
    audit = dict(events=0, closure_ok=0, closure_violations=[], attempted_skips=0,
                 skipped_escalations=0, by_node=Counter(), by_kind=Counter())
    prop_len = Counter()
    for arm in ('static', 'dynamic'):
        for t in tasks:
            uid = t['uid']
            for ev in raw[arm][uid]['events']:
                audit['events'] += 1
                audit['by_node'][ev['node']] += 1
                audit['by_kind'][ev['kind'] if ev.get('attempted') else 'skipped'] += 1
                if not ev.get('attempted'):
                    audit['skipped_escalations'] += 1
                    continue
                expected = [ev['node']] + ev['closure']
                got = [k.split(':')[0] for k in ev.get('executed', [])]
                if got == expected:
                    audit['closure_ok'] += 1
                else:
                    audit['closure_violations'].append(dict(arm=arm, uid=uid, expected=expected, got=got))
    # propagation length: tasks with any initial extraction failure
    for arm in ('static', 'dynamic'):
        for t in tasks:
            uid = t['uid']
            evs = raw[arm][uid]['events']
            if not evs:
                continue
            first = evs[0]
            if first.get('attempted'):
                prop_len[f'{first["node"]}->' + ','.join(first['closure'])] += 1
            else:
                prop_len['skipped'] += 1
    dC = sum(r['used'] - s['used'] for r, s in zip(D, S)) / n
    dL = sum(r['lat'] - s['lat'] for r, s in zip(D, S)) / n
    dQ = round(qD - qS, 4)
    ci_lo, ci_hi = ci(da, sa)
    case = 1 if ci_lo > 0 else (2 if dQ > 0 else 3)
    rep = dict(generated_unix=time.time(), n=n, headroom_rule=HEADROOM,
               A_main=dict(static_Q=round(qS, 4), dynamic_Q=round(qD, 4),
                           paired_dQ=dQ, paired_dQ_ci=[ci_lo, ci_hi],
                           static_C=round(sum(r['used'] for r in S) / n, 1),
                           dynamic_C=round(sum(r['used'] for r in D) / n, 1), dC=round(dC, 1),
                           static_L=round(sum(r['lat'] for r in S) / n, 2),
                           dynamic_L=round(sum(r['lat'] for r in D) / n, 2), dL=round(dL, 2)),
               B_help_harm=dict(help=b, harm=c, mcnemar=dict(b=b, c=c, p_exact=round(mcnemar_exact(b, c), 4))),
               C_adaptation=dict(by_node=dict(audit['by_node']), by_kind=dict(audit['by_kind'])),
               D_selective_update_audit=dict(events=audit['events'], closure_ok=audit['closure_ok'],
                                             violations=audit['closure_violations'][:10],
                                             n_violations=len(audit['closure_violations']),
                                             skipped_escalations=audit['skipped_escalations']),
               E_propagation=dict(initial_failure_paths=dict(prop_len)),
               preregistered_case=case,
               verdict={1: 'confirmed', 2: 'directionally positive, not confirmed', 3: 'no benefit'}[case])
    (OUT / 'CONFIRM_ANALYSIS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(rep, ensure_ascii=False, indent=1)[:2000])


if __name__ == '__main__':
    run()
