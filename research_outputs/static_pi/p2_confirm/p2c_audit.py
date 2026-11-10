#!/usr/bin/env python3
"""P2-C independent zero-call audit (fresh implementation; does not import p2c_analysis).
1) Recompute task-level means/diffs from P2C_RESULTS.json.
2) EXACT sign-flip p-values by full 2^26 enumeration (meet-in-middle counting) for H1-H5 (one-sided)
   and the interaction (two-sided); compare against the Monte-Carlo p-values in P2C_ANALYSIS.json.
3) Independent bootstrap CIs (new RNG construction) + hand Holm.
4) H1 sensitivity bookkeeping (which blocks dropped, which tasks remain, why 24).
5) Cost: per-arm backend split (DS vs GLM calls/tokens) to explain accounting vs marginal.
6) Fact-level terminal diffs for RSK_603803 (negative) and top gainers HW_600360 / DY_002086 / FR_600781,
   reconstructed from LEDGER texts and scored by the frozen p2c_scorer against the v1.1 contracts.
Outputs: p2c_analysis/P2C_AUDIT_RECHECK.json (+ printed summary).
"""
import json, random, statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path('/root/research_outputs/static_pi/p2_confirm')
GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
ARMS = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6']
import sys
sys.path.insert(0, str(HERE))
import p2c_scorer as S

res = json.loads((HERE / 'p2c_runs/P2C_RESULTS.json').read_text())
an = json.loads((HERE / 'p2c_analysis/P2C_ANALYSIS.json').read_text())
out = {}

# ---- 1. independent task means ----
acc = defaultdict(lambda: defaultdict(list))
for k, v in res.items():
    t = k.rsplit('_r', 1)[0]
    for a in ARMS:
        acc[t][a].append(v['arms'][a]['Q'])
tm = {t: {a: st.mean(qs) for a, qs in d.items()} for t, d in acc.items()}
def diffs(a, b, ts=None):
    return [tm[t][a] - tm[t][b] for t in sorted(ts or tm)]
for h, (a, b) in {'H1': ('G2', 'G1'), 'H2': ('G6', 'G2'), 'H3': ('G6', 'G3'), 'H4': ('G6', 'G4'), 'H5': ('G6', 'G5')}.items():
    d = diffs(a, b)
    assert abs(st.mean(d) - an['primary'][h]['mean_diff']) < 1e-3, h

# ---- 2. exact sign-flip enumeration (meet in the middle, 13+13) ----
def exact_p(diff, two_sided=False):
    d = np.array(diff, dtype=np.float64); n, obs = len(d), st.mean(diff)
    L = np.array([0.0])
    for x in d[:n // 2]: L = np.concatenate([L + x, L - x])
    R = np.array([0.0])
    for x in d[n // 2:]: R = np.concatenate([R + x, R - x])
    R.sort(); T = n * (abs(obs) if two_sided else obs); eps = 1e-9
    if two_sided:
        hi = np.searchsorted(R, T - L - eps, 'left'); lo = np.searchsorted(R, -(T - L) + eps, 'right')
        c = int((len(R) - hi).sum() + lo.sum())
    else:
        idx = np.searchsorted(R, T - L - eps, 'left'); c = int((len(R) - idx).sum())
    return c / 2 ** n, c, 2 ** n

checks = {}
for h, (a, b) in {'H1': ('G2', 'G1'), 'H2': ('G6', 'G2'), 'H3': ('G6', 'G3'), 'H4': ('G6', 'G4'), 'H5': ('G6', 'G5')}.items():
    d = diffs(a, b)
    p_ex, c, m = exact_p(d)
    p_mc = an['primary'][h]['p_one_sided_perm']
    checks[h] = dict(mean=round(st.mean(d), 6), p_exact=p_ex, count=c, of=m, p_mc_reported=p_mc,
                     mc_abs_err=round(abs(p_ex - p_mc), 6), agree=abs(p_ex - p_mc) < 3e-4)
q = [tm[t]['G6'] - tm[t]['G4'] - tm[t]['G5'] + tm[t]['G3'] for t in sorted(tm)]
p_ex, c, m = exact_p(q, two_sided=True)
checks['interaction'] = dict(mean=round(st.mean(q), 6), p_exact=p_ex, count=c, of=m,
                             p_mc_reported=an['primary']['interaction']['p_two_sided_perm'],
                             mc_abs_err=round(abs(p_ex - an['primary']['interaction']['p_two_sided_perm']), 6))
out['exact_recheck'] = checks

# ---- 3. independent bootstrap CIs + Holm ----
rng = random.Random(0xC0FFEE)
def boot(d):
    n = len(d)
    ms = sorted(st.mean(rng.choices(d, k=n)) for _ in range(10000))
    return round(ms[249], 4), round(ms[9749], 4)
cis = {}
for h, (a, b) in {'H2': ('G6', 'G2'), 'H4': ('G6', 'G4')}.items():
    cis[h] = boot(diffs(a, b))
cis['interaction'] = boot(q)
out['independent_bootstrap_ci'] = cis
ps = sorted((an['primary'][h]['p_one_sided_perm'], h) for h in ('H1', 'H2', 'H3', 'H4', 'H5'))
rej = []
for i, (p, h) in enumerate(ps):
    if p <= 0.05 / (5 - i):
        rej.append(h)
    else:
        break
out['holm_recheck'] = dict(order=[h for _, h in ps], rejected=rej)

# ---- 4. H1 sensitivity bookkeeping ----
drop = sorted(k for k, v in res.items() if v.get('shared_fault') or any(v['arms'][a]['execution_failed'] for a in ARMS))
by_task = defaultdict(list)
for k in res:
    by_task[k.rsplit('_r', 1)[0]].append(k)
kept = {t: [k for k in ks if k not in drop] for t, ks in by_task.items()}
out['h1_sensitivity'] = dict(
    dropped_blocks=drop, n_dropped=len(drop),
    per_task_remaining={t: [k for k in kept[t]] for t in sorted(kept) if len(kept[t]) < 2},
    tasks_excluded=sorted(t for t in kept if not kept[t]),
    n_tasks_clean=sum(1 for t in kept if kept[t]),
    h1_clean_mean=round(st.mean([st.mean([res[k]['arms']['G2']['Q'] - res[k]['arms']['G1']['Q'] for k in kept[t]]) for t in kept if kept[t]]), 4),
    h1_primary_mean=an['primary']['H1']['mean_diff'])

# ---- 5. per-arm backend split ----
led = [json.loads(l) for l in open(HERE / 'p2c_runs/LEDGER.jsonl')]
led = [r for r in led if r['phase'] == 'done']
split = defaultdict(lambda: defaultdict(lambda: [0, 0]))
for r in led:
    s = split[r['arm']][r['backend']]
    s[0] += 1; s[1] += (r.get('in') or 0) + (r.get('out') or 0)
out['per_arm_backend'] = {a: {b: dict(calls=v[0], tokens=v[1]) for b, v in d.items()} for a, d in split.items()}

# ---- 6. fact-level terminal diffs ----
def terminal(task, rep, arm):
    rows = [r for r in led if r['task'] == task and r['rep'] == rep and r['arm'] == arm
            and r['node'] in ('SINK', 'G1') and not r.get('fault')]
    if not rows:
        return None
    return json.loads(rows[-1]['text'])

def fact_diff(task):
    ct = json.loads((GOLD / f'TASK_CONTRACT_{task}_v1.1.json').read_text())
    rep_out = {}
    for rep in (1, 2):
        t2, t6 = terminal(task, rep, 'G2'), terminal(task, rep, 'G6')
        if t2 is None or t6 is None:
            rep_out[rep] = dict(skipped='terminal missing')
            continue
        r2 = {x['fact_id']: x['status'] for x in S.score(t2, ct)['rows']}
        r6 = {x['fact_id']: x['status'] for x in S.score(t6, ct)['rows']}
        gain = [f for f in r6 if r6[f] == 'TP' and r2[f] != 'TP']
        loss = [f for f in r6 if r6[f] != 'TP' and r2[f] == 'TP']
        detail = []
        fidx = {x['fact_id']: x for x in ct['required_facts']}
        for f in gain + loss:
            a6 = next((a for a in t6['answers'] if a.get('fact_id') == f), {})
            a2 = next((a for a in t2['answers'] if a.get('fact_id') == f), {})
            detail.append(dict(fact=f, pred=fidx[f]['predicate'][:16], dir='+' if f in gain else '-',
                               v2=str(a2.get('value'))[:24], v6=str(a6.get('value'))[:24]))
        rep_out[rep] = dict(gain=sorted(gain), loss=sorted(loss), detail=detail,
                            Q2=res[f'{task}_r{rep}']['arms']['G2']['Q'], Q6=res[f'{task}_r{rep}']['arms']['G6']['Q'],
                            status6=res[f'{task}_r{rep}']['arms']['G6']['status'][:40],
                            targets=res[f'{task}_r{rep}']['targets'][:8])
    return rep_out

out['fact_diffs'] = {t: fact_diff(t) for t in ['RSK_603803', 'HW_600360', 'DY_002086', 'FR_600781']}
# RSK execution trace
out['rsk_trace'] = [dict(rep=r['rep'], arm=r['arm'], node=r['node'], backend=r['backend'],
                         fault=r.get('fault'), out_tok=r.get('out')) for r in led if r['task'] == 'RSK_603803']

(HERE / 'p2c_analysis/P2C_AUDIT_RECHECK.json').write_text(json.dumps(json.loads(json.dumps(out, default=int)), ensure_ascii=False, indent=1))
print('=== exact vs MC p-values ===')
for h, v in checks.items():
    print(f"{h:12} mean={v['mean']:+.4f} p_exact={v['p_exact']:.6f} ({v['count']}/{v['of']})  p_mc={v.get('p_mc_reported')}  err={v.get('mc_abs_err')}")
print('independent CIs', cis, '| holm', out['holm_recheck'])
print('H1 sensitivity:', {k: v for k, v in out['h1_sensitivity'].items() if k != 'dropped_blocks'})
print('dropped blocks:', out['h1_sensitivity']['dropped_blocks'])
print('per-arm backend:', json.dumps(out['per_arm_backend'], ensure_ascii=False))
for t, d in out['fact_diffs'].items():
    print('---', t)
    for rep, v in d.items():
        if 'skipped' in v:
            print(' rep', rep, v); continue
        print(f" rep{rep}: Q2={v['Q2']:.3f} Q6={v['Q6']:.3f} st6={v['status6']} gains={v['gain']} losses={v['loss']}")
        for x in v['detail']:
            print('   ', x['dir'], x['fact'], x['pred'], '| G2:', x['v2'], '-> G6:', x['v6'])
