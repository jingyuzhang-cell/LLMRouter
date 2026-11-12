#!/usr/bin/env python3
"""P2-C final analysis, strictly per the preregistered plan (P2_STATISTICAL_PLAN §3-6, P2_PROTOCOL_V1.1 §4-5).
Order: integrity audit -> execution reliability -> primary tests -> cost/latency -> heterogeneity -> sensitivity.
Primary: task = unit (k=2 reps averaged), one-sided exact sign-flip permutation (n=26>20 -> 1e5 MC flips, seed
20261108), H1-H5 Holm family alpha=0.05; interaction q=G6-G4-G5+G3 two-sided. Failed arms score Q=0 (plan §6.1).
Sensitivity: drop reps with shared-upstream failure or execution-failed arms (plan §4 sensitivity 1).
Outputs: p2c_analysis/P2C_ANALYSIS.json and p2c_analysis/tables in P2C_FINAL_REPORT.md (written separately).
"""
import json, math, random, statistics as st
from collections import defaultdict
from datetime import datetime as DT
from pathlib import Path

HERE = Path('/root/research_outputs/static_pi/p2_confirm')
SEED, B, BOOT = 20261108, 100_000, 10_000
ARMS = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6']

res = json.loads((HERE / 'p2c_runs/P2C_RESULTS.json').read_text())
led = [json.loads(l) for l in open(HERE / 'p2c_runs/LEDGER.jsonl')]
rand = json.loads((HERE / 'P2C_RANDOMIZATION_TABLE.json').read_text())
out = {}

# ---------------- 1. integrity audit ----------------
blocks = {f"{v['task']}_r{v['rep']}": v for v in rand['table']}
integ = dict(blocks_in_results=len(res), blocks_expected=len(blocks),
             key_set_match=set(res) == set(blocks),
             arm_orders_match=all(res[k]['arm_order'] == v['arm_order'] for k, v in blocks.items() if k in res),
             all_arms_present=all(sorted(v['arms']) == ARMS for v in res.values()),
             unique_task_rep=len({(v['task'], v['rep']) for v in rand['table']}),
             n_tasks=len({v['task'] for v in rand['table']}))
done = [r for r in led if r['phase'] == 'done']
sent_n = sum(r['phase'] == 'sent' for r in led)
integ.update(dict(ledger_sent=sent_n, ledger_done=len(done), sent_without_done=sent_n - len(done),
                  console_stop='BATCH STOP' in (HERE / 'P2C_RUN_CONSOLE.log').read_text()))
out['integrity'] = integ

# ---------------- 2. execution reliability ----------------
status = defaultdict(lambda: defaultdict(int))
for v in res.values():
    for a, r in v['arms'].items():
        s = r['status']
        key = ('EXECUTION_FAILED::shared' if s.startswith('EXECUTION_FAILED::shared') else
               'RECOVERY_FAILED_TRUNCATED' if s.startswith('RECOVERY_FAILED_TRUNCATED') else
               'RECOVERY_FAILED' if s.startswith('RECOVERY_FAILED') else
               'EXECUTION_FAILED' if s.startswith('EXECUTION_FAILED') else s)
        status[a][key] += 1
shared_fail_blocks = [k for k, v in res.items() if v.get('shared_fault')]
tasks = sorted({k.rsplit('_r', 1)[0] for k in res})
clean_reps = defaultdict(list)
for k, v in res.items():
    t = k.rsplit('_r', 1)[0]
    ok = (not v.get('shared_fault')) and not any(v['arms'][a]['execution_failed'] for a in ARMS)
    if ok:
        clean_reps[t].append(k)
j2r = [r for r in done if r['node'] == 'J2R']
j2 = [r for r in done if r['node'] == 'J2']
rel = dict(
    arm_status_counts={a: dict(status[a]) for a in ARMS},
    shared_upstream_failure=dict(blocks=len(shared_fail_blocks), of=len(res), rate=round(len(shared_fail_blocks) / len(res), 4),
                                 affected_tasks=sorted({k.rsplit('_r', 1)[0] for k in shared_fail_blocks}),
                                 tasks_losing_all_reps=sorted(t for t in tasks if not clean_reps[t])),
    j2r_truncation=dict(truncated=sum(r.get('fault') == 'truncated' for r in j2r), calls=len(j2r),
                        rate=round(sum(r.get('fault') == 'truncated' for r in j2r) / len(j2r), 4) if j2r else None),
    j2_truncation=dict(truncated=sum(r.get('fault') == 'truncated' for r in j2), calls=len(j2)),
    other_faults=[(r['task'], r['rep'], r['arm'], r['node'], r['fault']) for r in done
                  if r.get('fault') and r['node'] not in ('J2R',) and not (r['node'] == 'J2' and r['arm'] == 'shared')],
    blocks_with_recovery_attempt=sum(1 for v in res.values() if any(v['arms'][a]['status'].startswith(('OK', 'RECOVERY')) and v['arms'][a]['status'] != 'OK_NO_TARGET' for a in ('G3', 'G4', 'G5', 'G6'))),
    blocks_no_target=sum(1 for v in res.values() if v['arms']['G3']['status'] == 'OK_NO_TARGET'),
    clean_reps_per_task={t: len(v) for t, v in clean_reps.items()})
out['reliability'] = rel

# budget / wall time
t0, t1 = DT.fromisoformat(done[0]['ts']), DT.fromisoformat(done[-1]['ts'])
tok = sum((r.get('in') or 0) + (r.get('out') or 0) for r in done)
out['budget'] = dict(calls=len(done), tokens=tok,
                     yuan_accounting=round(sum(r.get('yuan_accounting') or 0 for r in done), 4),
                     yuan_marginal=round(sum(r.get('yuan_marginal') or 0 for r in done), 4),
                     caps=json.load(open(HERE / 'FREEZE_P2C.json'))['caps'],
                     wall=str(t1 - t0), first_call=done[0]['ts'], last_call=done[-1]['ts'])

# per-arm cost/latency (arm-tagged rows; shared shown separately)
per = defaultdict(lambda: dict(calls=0, yuan=0.0, yuan_marg=0.0, tokens=0, secs=0.0))
prev = {}
for r in led:
    t = DT.fromisoformat(r['ts'])
    key = r['arm']
    if r['phase'] == 'sent':
        prev[key] = t
    elif r['phase'] == 'done' and key in prev:
        d = per[key]
        d['calls'] += 1; d['yuan'] += r.get('yuan_accounting') or 0; d['yuan_marg'] += r.get('yuan_marginal') or 0
        d['tokens'] += (r.get('in') or 0) + (r.get('out') or 0); d['secs'] += (t - prev.pop(key)).total_seconds()
out['per_arm_cost'] = {k: dict(calls=v['calls'], yuan=round(v['yuan'], 4), yuan_marginal=round(v['yuan_marg'], 4),
                               tokens=v['tokens'], arm_secs=round(v['secs'], 1)) for k, v in per.items()}

# ---------------- 3. task-level Q (rep-averaged) and primary tests ----------------
def task_means(reps_filter=None):
    """rep-averaged Q per (task, arm); reps_filter(k,v)->bool selects reps; tasks with none are absent."""
    acc = defaultdict(lambda: defaultdict(list))
    for k, v in res.items():
        if reps_filter is not None and not reps_filter(k, v):
            continue
        t = k.rsplit('_r', 1)[0]
        for a in ARMS:
            acc[t][a].append(v['arms'][a]['Q'])
    return {t: {a: st.mean(qs) for a, qs in d.items()} for t, d in acc.items() if len(d) == 6}

def perm_p(diff, greater=True, seed_off=0):
    rng = random.Random(SEED + seed_off)
    obs = st.mean(diff)
    c = 0
    for _ in range(B):
        s = [d if rng.random() < 0.5 else -d for d in diff]
        m = st.mean(s)
        if (m >= obs) if greater else (abs(m) >= abs(obs)):
            c += 1
    return (1 + c) / (B + 1), obs

def boot_ci(diff):
    rng = random.Random(SEED + 999)
    n = len(diff)
    ms = sorted(st.mean([diff[rng.randrange(n)] for _ in range(n)]) for _ in range(BOOT))
    return round(ms[int(0.025 * BOOT)], 4), round(ms[int(0.975 * BOOT)], 4)

def d_paired(diff):
    return round(st.mean(diff) / st.stdev(diff), 3) if st.stdev(diff) > 0 else None

def contrasts(tm, label):
    H = {'H1': ('G2', 'G1'), 'H2': ('G6', 'G2'), 'H3': ('G6', 'G3'), 'H4': ('G6', 'G4'), 'H5': ('G6', 'G5')}
    rows = {}
    for i, (h, (a, b)) in enumerate(H.items()):
        d = [tm[t][a] - tm[t][b] for t in sorted(tm)]
        p, m = perm_p(d, greater=True, seed_off=i)
        rows[h] = dict(contrast=f'Q({a})-Q({b})', n=len(d), mean_diff=round(m, 4), sd_diff=round(st.stdev(d), 4),
                       p_one_sided_perm=p, ci95_boot=boot_ci(d), cohens_d_paired=d_paired(d),
                       positives=sum(x > 0 for x in d), negatives=sum(x < 0 for x in d), zeros=sum(x == 0 for x in d))
    q = [tm[t]['G6'] - tm[t]['G4'] - tm[t]['G5'] + tm[t]['G3'] for t in sorted(tm)]
    p, m = perm_p(q, greater=False, seed_off=7)
    rows['interaction'] = dict(contrast='G6-G4-G5+G3', n=len(q), mean=round(m, 4), sd=round(st.stdev(q), 4),
                               p_two_sided_perm=p, ci95_boot=boot_ci(q), cohens_d=d_paired(q),
                               positives=sum(x > 0 for x in q), negatives=sum(x < 0 for x in q))
    # Holm on H1-H5
    order = sorted(H, key=lambda h: rows[h]['p_one_sided_perm'])
    rejected, m_ = [], len(H)
    for i, h in enumerate(order):
        thr = 0.05 / (m_ - i)
        if rows[h]['p_one_sided_perm'] <= thr:
            rejected.append(h)
        else:
            break
    rows['_holm'] = dict(order=order, rejected=rejected, family_alpha=0.05,
                         thresholds=[round(0.05 / (m_ - i), 4) for i in range(m_)])
    rows['_arm_means'] = {a: round(st.mean([tm[t][a] for t in tm]), 4) for a in ARMS}
    rows['_n_tasks'] = len(tm)
    rows['_label'] = label
    return rows

tm_primary = task_means()                       # all 52 reps, failed arms Q=0 (plan 6.1)
out['primary'] = contrasts(tm_primary, 'preregistered primary: all reps, failed arms Q=0')
tm_clean = task_means(lambda k, v: not v.get('shared_fault') and not any(v['arms'][a]['execution_failed'] for a in ARMS))
out['sensitivity_clean'] = contrasts(tm_clean, 'clean reps only (no shared-failure / no execution-failed arm)')

# safety: mean error_rate per arm (primary reps)
er = defaultdict(list)
for v in res.values():
    for a in ARMS:
        e = v['arms'][a]['safety'].get('error_rate')
        if e is not None:
            er[a].append(e)
out['safety_error_rate'] = {a: round(st.mean(v), 4) for a, v in er.items()}

# ---------------- 5. heterogeneity & descriptive subsets ----------------
het = {}
for label, sel in [('all_reps', lambda k, v: True),
                   ('natural_anomaly_blocks', lambda k, v: bool(v['targets'])),
                   ('no_target_blocks', lambda k, v: not v['targets'])]:
    sub = [v for k, v in res.items() if sel(k, v)]
    if sub:
        het[label] = dict(blocks=len(sub), arm_mean_Q={a: round(st.mean(v['arms'][a]['Q'] for v in sub), 4) for a in ARMS})
het['per_task_H2_diff'] = {t: round(tm_primary[t]['G6'] - tm_primary[t]['G2'], 4) for t in sorted(tm_primary)}
het['per_task_H3_diff'] = {t: round(tm_primary[t]['G3'] - tm_primary[t]['G2'], 4) for t in sorted(tm_primary)}
het['per_task_clean_H2'] = {t: round(tm_clean[t]['G6'] - tm_clean[t]['G2'], 4) for t in sorted(tm_clean)}
out['heterogeneity'] = het
out['per_task_Q_primary'] = tm_primary

d = HERE / 'p2c_analysis'; d.mkdir(exist_ok=True)
(d / 'P2C_ANALYSIS.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out['integrity'], ensure_ascii=False))
print(json.dumps(out['reliability']['shared_upstream_failure'], ensure_ascii=False))
print('j2r', out['reliability']['j2r_truncation'], '| no_target blocks', out['reliability']['blocks_no_target'])
print('budget', out['budget'])
print('PRIMARY arm means', out['primary']['_arm_means'])
for h in ['H1', 'H2', 'H3', 'H4', 'H5', 'interaction']:
    print(h, {k: v for k, v in out['primary'][h].items() if k != 'contrast'})
print('HOLM', out['primary']['_holm'])
print('CLEAN arm means (n=%d)' % out['sensitivity_clean']['_n_tasks'], out['sensitivity_clean']['_arm_means'])
for h in ['H2', 'interaction']:
    print('clean', h, {k: v for k, v in out['sensitivity_clean'][h].items() if k != 'contrast'})
print('clean HOLM', out['sensitivity_clean']['_holm'])
print('safety error_rate', out['safety_error_rate'])
print('het subsets', {k: v for k, v in het.items() if isinstance(v, dict) and 'blocks' in v})
