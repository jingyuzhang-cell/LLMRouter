"""Offline statistical analysis for the full recovery matrix. Reads FULL_RESULTS.json (audit output).
Cluster bootstrap by task_uid within failure-type stratum; fixed seed. No method code is touched."""
import csv
import json
import random
from collections import defaultdict
from .recovery_matrix_v2_pilot import ACTIONS
from .recovery_matrix_v2_full_prep import OUT

SEED = 20260918
B = 10000
LABELS = ['evidence', 'reasoning', 'structural']
RECOVERY = [a for a in ACTIONS if a != 'no_recovery']
PAIRS = {'evidence': [('evidence_retrieval', 'switch_model'), ('evidence_retrieval', 'local_decompose')],
         'reasoning': [('switch_model', 'retry_same')],
         'structural': [('local_decompose', 'switch_model')]}
KEY_PAIRS = {(l, a1, a2) for l, ps in PAIRS.items() for a1, a2 in ps}

def mean(xs):
    return sum(xs) / len(xs) if xs else None

def median(xs):
    if not xs: return None
    s = sorted(xs); n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

def pct(ci):
    return [round(ci[0], 4), round(ci[1], 4)]

def analyze():
    full = json.loads((OUT / 'FULL_RESULTS.json').read_text())
    results = full['results']
    rng = random.Random(SEED)
    strata = defaultdict(list)
    for r in results: strata[r['label']].append(r)
    for r in results:
        for a in ACTIONS:
            act = r['actions'][a]
            act.setdefault('success', False)
            act['exception'] = act.get('executed') is False and a != 'no_recovery'
    clusters = {l: defaultdict(list) for l in LABELS}
    for r in results: clusters[r['label']][r['task_uid']].append(r)

    def boot(lab, node_stat):
        uids = list(clusters[lab].keys())
        stats = []
        for _ in range(B):
            sample = [r for u in [uids[rng.randrange(len(uids))] for _ in uids] for r in clusters[lab][u]]
            stats.append(node_stat(sample))
        return stats

    # B/C/E: cell rates with cluster-bootstrap CIs
    matrix = {}
    for lab in LABELS:
        nodes = strata[lab]
        matrix[lab] = {}
        for a in ACTIONS:
            point = mean([r['actions'][a]['success'] for r in nodes])
            dist = boot(lab, lambda s, a=a: mean([r['actions'][a]['success'] for r in s]))
            dist.sort()
            matrix[lab][a] = dict(n=len(nodes), rate=round(point, 4),
                                  ci95=pct([dist[int(0.025 * B)], dist[int(0.975 * B) - 1]]),
                                  exceptions=sum(r['actions'][a]['exception'] for r in nodes))
    # D/E: paired differences
    paired = {}
    for lab in LABELS:
        for a1, a2 in PAIRS[lab]:
            diffs = [r['actions'][a1]['success'] - r['actions'][a2]['success'] for r in strata[lab]]
            point = mean(diffs)
            dist = sorted(boot(lab, lambda s, a1=a1, a2=a2: mean([r['actions'][a1]['success'] - r['actions'][a2]['success'] for r in s])))
            nonzero = sum(d != 0 for d in diffs)
            paired[f'{lab}:{a1}-{a2}'] = dict(n=len(diffs), mean_delta=round(point, 4),
                ci95=pct([dist[int(0.025 * B)], dist[int(0.975 * B) - 1]]),
                discordant_pairs=nonzero, key_pair=(lab, a1, a2) in KEY_PAIRS)
    # F: incremental cost (tokens) and extra service latency (dt_s); no_recovery is the zero baseline
    cells = {}
    for lab in LABELS:
        cells[lab] = {}
        for a in ACTIONS:
            ts = [r['actions'][a]['tokens'] for r in strata[lab] if r['actions'][a]['tokens'] is not None]
            ds = [r['actions'][a]['dt_s'] for r in strata[lab] if r['actions'][a]['dt_s'] is not None]
            cells[lab][a] = dict(delta_C=dict(mean=round(mean(ts), 1) if ts else None, median=median(ts)),
                                 delta_T=dict(mean=round(mean(ds), 3) if ds else None, median=round(median(ds), 3) if ds else None),
                                 missing_tokens=sum(r['actions'][a]['tokens'] is None for r in strata[lab]),
                                 missing_dt=sum(r['actions'][a]['dt_s'] is None for r in strata[lab]))
    # G: evidence mechanism — does retrieval gain come from evidence coverage recovery?
    ev = [r for r in results if r['label'] == 'evidence']
    er_rows = []
    for r in ev:
        a = r['actions']['evidence_retrieval']
        er_rows.append(dict(node_id=r['node_id'], task_uid=r['task_uid'], delta_ER=a['delta_ER'],
                            ER_before=a['ER_before'], ER_after=a['ER_after'], recover=a['success']))
    pos = [x for x in er_rows if x['delta_ER'] > 0]
    nonpos = [x for x in er_rows if x['delta_ER'] <= 0]
    mechanism_evidence = dict(
        n_retrieval=len(er_rows),
        P_recover_given_deltaER_gt0=round(mean([x['recover'] for x in pos]), 4) if pos else None,
        n_deltaER_gt0=len(pos),
        P_recover_given_deltaER_le0=round(mean([x['recover'] for x in nonpos]), 4) if nonpos else None,
        n_deltaER_le0=len(nonpos),
        delta_ER_distribution=dict(gt0=len(pos), eq0=sum(x['delta_ER'] == 0 for x in er_rows), lt0=sum(x['delta_ER'] < 0 for x in er_rows)),
        per_node=er_rows)
    # H: structural mechanism
    st = [r for r in results if r['label'] == 'structural']
    d_rows = [dict(node_id=r['node_id'], task_uid=r['task_uid'], delta_D=r['actions']['local_decompose']['delta_D'],
                   D_before=r['actions']['local_decompose']['D_before'], D_after=r['actions']['local_decompose']['D_after'],
                   recover=r['actions']['local_decompose']['success']) for r in st]
    dpos = [x for x in d_rows if x['delta_D'] > 0]
    dnon = [x for x in d_rows if x['delta_D'] <= 0]
    mechanism_structural = dict(
        n_decompose=len(d_rows),
        P_recover_given_deltaD_gt0=round(mean([x['recover'] for x in dpos]), 4) if dpos else None,
        n_deltaD_gt0=len(dpos),
        P_recover_given_deltaD_le0=round(mean([x['recover'] for x in dnon]), 4) if dnon else None,
        n_deltaD_le0=len(dnon),
        per_node=d_rows)
    # I: best action per failure type with overlap-avoidance note
    best = {}
    for lab in LABELS:
        ranked = sorted(RECOVERY, key=lambda a: -matrix[lab][a]['rate'])
        top = ranked[0]
        overlap = [a for a in ranked[1:] if matrix[lab][a]['ci95'][1] >= matrix[lab][top]['ci95'][0]]
        best[lab] = dict(top_action=top, ci_overlaps_with=overlap,
                         claim='no significant best: CIs overlap' if overlap else 'top action CI does not overlap others')
    # A: completeness
    completeness = dict(n_nodes=len(results), n_actions=sum(len(r['actions']) for r in results),
                        valid_nodes=len(results) if full['checks']['all_actions_have_results'] else 0,
                        label_counts={l: len(strata[l]) for l in LABELS},
                        exceptions_by_action={a: sum(r['actions'][a]['exception'] for r in results) for a in ACTIONS},
                        missing_tokens=sum(r['actions'][a]['tokens'] is None for r in results for a in ACTIONS),
                        missing_dt=sum(r['actions'][a]['dt_s'] is None for r in results for a in ACTIONS),
                        snapshot_invalid=full['snapshot_invalid'])
    analysis = dict(seed=SEED, bootstrap_B=B, cluster='task_uid', completeness=completeness,
                    matrix=matrix, paired=paired, cells=cells, mechanism_evidence=mechanism_evidence,
                    mechanism_structural=mechanism_structural, best_per_type=best)
    (OUT / 'FULL_ANALYSIS.json').write_text(json.dumps(analysis, ensure_ascii=False, indent=2))
    # J: CSVs
    with (OUT / 'FULL_MATRIX.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['failure_type', 'action', 'n', 'rate', 'ci95_low', 'ci95_high', 'exceptions'])
        for lab in LABELS:
            for a in ACTIONS:
                m = matrix[lab][a]; w.writerow([lab, a, m['n'], m['rate'], m['ci95'][0], m['ci95'][1], m['exceptions']])
    with (OUT / 'FULL_PAIRED.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['failure_type', 'action1', 'action2', 'n', 'mean_delta_R', 'ci95_low', 'ci95_high', 'discordant_pairs', 'key_pair'])
        for k, v in paired.items():
            lab, pair = k.split(':', 1); a1, a2 = pair.split('-', 1)
            w.writerow([lab, a1, a2, v['n'], v['mean_delta'], v['ci95'][0], v['ci95'][1], v['discordant_pairs'], v['key_pair']])
    with (OUT / 'FULL_CELLS.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['failure_type', 'action', 'deltaC_mean_tokens', 'deltaC_median_tokens', 'deltaT_mean_s', 'deltaT_median_s', 'missing_tokens', 'missing_dt'])
        for lab in LABELS:
            for a in ACTIONS:
                c = cells[lab][a]; w.writerow([lab, a, c['delta_C']['mean'], c['delta_C']['median'], c['delta_T']['mean'], c['delta_T']['median'], c['missing_tokens'], c['missing_dt']])
    return analysis

def report(analysis):
    m, p, c = analysis['matrix'], analysis['paired'], analysis['cells']
    L = ['# Recovery Matrix v2 — Full (148 nodes) 统计报告', '',
         '统计单位：failure node；cluster bootstrap 按 task_uid，B=%d，seed=%d。' % (analysis['bootstrap_B'], analysis['seed']), '',
         '## 主表：R(φ, a) 恢复率 [95% CI]', '',
         '| Failure Type | ' + ' | '.join(RECOVERY) + ' | no_recovery |',
         '|' + '---|' * (len(RECOVERY) + 2)]
    for lab in LABELS:
        row = [f"**{lab}** (n={m[lab]['no_recovery']['n']})"]
        for a in RECOVERY:
            x = m[lab][a]; row.append(f"{x['rate']:.3f} [{x['ci95'][0]:.3f},{x['ci95'][1]:.3f}]")
        row.append('0.000 (基线)')
        L.append('| ' + ' | '.join(row) + ' |')
    L += ['', '## 同节点配对差 ΔR(a1,a2)', '', '| Failure Type | 配对 | ΔR [95% CI] | 不一致对数 |', '|---|---|---|---|']
    for k, v in p.items():
        lab, pair = k.split(':', 1)
        star = ' ★' if v['key_pair'] else ''
        sig = '' if v['ci95'][0] <= 0 <= v['ci95'][1] else '（显著）'
        L.append(f"| {lab} | {pair.replace('-', ' vs ')}{star} | {v['mean_delta']:+.3f} [{v['ci95'][0]:+.3f},{v['ci95'][1]:+.3f}]{sig} | {v['discordant_pairs']}/{v['n']} |")
    L += ['', '## 成本与延迟（ΔC=增量 tokens，ΔT=额外服务时延 s）', '', '| Failure Type | 动作 | ΔC mean/median | ΔT mean/median |', '|---|---|---|---|']
    for lab in LABELS:
        for a in RECOVERY:
            cc, tt = c[lab][a]['delta_C'], c[lab][a]['delta_T']
            L.append(f"| {lab} | {a} | {cc['mean']}/{cc['median']} | {tt['mean']}/{tt['median']} |")
    me, ms = analysis['mechanism_evidence'], analysis['mechanism_structural']
    L += ['', '## 机制分析', '',
          f"- Evidence (retrieval, n={me['n_retrieval']}): P(recover|ΔER>0)={me['P_recover_given_deltaER_gt0']} (n={me['n_deltaER_gt0']}) vs P(recover|ΔER≤0)={me['P_recover_given_deltaER_le0']} (n={me['n_deltaER_le0']})；ΔER>0/{me['delta_ER_distribution']['gt0']}，=0/{me['delta_ER_distribution']['eq0']}，<0/{me['delta_ER_distribution']['lt0']}。",
          f"- Structural (decompose, n={ms['n_decompose']}): P(recover|ΔD>0)={ms['P_recover_given_deltaD_gt0']} (n={ms['n_deltaD_gt0']}) vs P(recover|ΔD≤0)={ms['P_recover_given_deltaD_le0']} (n={ms['n_deltaD_le0']})。", '',
          '## 每类最高动作（不作显著性声明）', '']
    for lab, b in analysis['best_per_type'].items():
        L.append(f"- {lab}: {b['top_action']}（{b['claim']}）")
    L.append('')
    (OUT / 'FULL_REPORT.md').write_text('\n'.join(L))
    return '\n'.join(L)

if __name__ == '__main__':
    a = analyze()
    (OUT / 'FULL_REPORT.md').write_text(report(a))
    print(json.dumps(dict(completeness=a['completeness'], matrix={l: {x: v['rate'] for x, v in a['matrix'][l].items()} for l in LABELS},
                          paired=a['paired'], mechanism_evidence={k: v for k, v in a['mechanism_evidence'].items() if k != 'per_node'},
                          mechanism_structural={k: v for k, v in a['mechanism_structural'].items() if k != 'per_node'}), ensure_ascii=False, indent=2))
