"""Derive Experiments 1/2/3/4/6 from NET-BENEFIT NB_ROWS.jsonl.

One complete six-strategy trajectory supports every downstream analysis —
this is the ONLY consumer of model-call results (no re-runs per figure).

Outputs (written only when the corresponding real cells exist; on stub data
they are structural dry-run proofs, clearly labeled):
  Experiment 1  RQ1_PAIRED_QCL_RESULTS.json    A vs B vs C (clean)
  Experiment 2  RECOVERY_ATTRIBUTION_RESULTS.json  C vs D (all states)
  Experiment 3  LOCAL_VS_FULL_RESULTS.json     D vs E (all states)
  Experiment 4  NET_BENEFIT_RESULTS.json + PAIRED_TASKS.csv + STATISTICS
  Experiment 6  PARETO_QCL_RESULTS.json        per-state fronts

Statistical machinery: exact one-sided McNemar (scipy binom), Holm
correction for exploratory families, task-cluster bootstrap CIs.

Run:  python3 -m collab_scheduler_v1.joint_search_v1.analyze_netbenefit [--stub]
"""
import argparse
import csv
import itertools
import json
import sys
from pathlib import Path

from scipy.stats import binom

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUTDIR = ROOT / 'collab_scheduler_v1/joint_search_v1'
RUNROOT = OUTDIR / 'netbenefit_runs'
BUDGETS = (600, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000)
PRIMARY = dict(protocol='mechanism', state='fault30', budget=3000,
               gate1=('D_dynamic_local', 'A_single'),
               gate2=('D_dynamic_local', 'A_single_cross_fallback'))


def load_rows():
    rows = {}
    for l in (RUNROOT / 'NB_ROWS.jsonl').read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get('status') == 'COMPLETE':
            rows[(r['protocol'], r['arm'], r['state'])] = r
    return rows


def task_map(rec):
    return {t['uid']: t for t in rec['tasks']}


def mcnemar_one_sided(h, m):
    d = h + m
    return 1.0 if d == 0 else float(binom.sf(h - 1, d, 0.5))


def holm(pvals):
    """Holm-Bonferroni: returns adjusted p-values in original order."""
    idx = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(idx):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


def help_harm(a_map, b_map, uids, budget=None, ckey='C_tokens'):
    """b vs a: Help = a wrong & b right (within budget); Harm = converse."""
    h = m = 0
    per = {}
    for u in uids:
        ta, tb = a_map[u], b_map[u]
        if budget is not None:
            ok_a = ta['Q'] == 1 and ta[ckey] <= budget
            ok_b = tb['Q'] == 1 and tb[ckey] <= budget
        else:
            ok_a, ok_b = ta['Q'] == 1, tb['Q'] == 1
        per[u] = (int(ok_a), int(ok_b))
        if not ok_a and ok_b:
            h += 1
        elif ok_a and not ok_b:
            m += 1
    return h, m, per


def bootstrap_ci_delta(per, n_boot=2000, seed=20261009):
    """Task-cluster bootstrap on paired 0/1 outcomes (delta = Qb - Qa)."""
    import random
    rng = random.Random(seed)
    uids = list(per)
    deltas = []
    for _ in range(n_boot):
        sample = [uids[rng.randrange(len(uids))] for _ in uids]
        qa = sum(per[u][0] for u in sample) / len(sample)
        qb = sum(per[u][1] for u in sample) / len(sample)
        deltas.append(qb - qa)
    deltas.sort()
    return dict(low=round(deltas[int(0.025 * n_boot)], 4),
                high=round(deltas[int(0.975 * n_boot) - 1], 4))


def q_b(rec_map, budget):
    return sum(1 for t in rec_map.values()
               if t['Q'] == 1 and t['C_tokens'] <= budget) / len(rec_map)


# ------------------------------------------------------------- Experiment 1
def exp1(rows, source_label):
    need = [('mechanism', a, 'clean') for a in
            ('A_single', 'B_same_model_dag', 'C_static_hetero')]
    if not all(k in rows for k in need):
        return None
    A = task_map(rows[need[0]]); B = task_map(rows[need[1]]); C = task_map(rows[need[2]])
    uids = sorted(A)
    out = dict(role='RQ1: decomposition loss and heterogeneous recovery (clean)',
               source=source_label, n=len(uids))
    for name, M in (('A_single', A), ('B_same_model_dag', B), ('C_static_hetero', C)):
        out[name] = dict(
            Q=sum(t['Q'] for t in M.values()) / len(M),
            C=sum(t['C_tokens'] for t in M.values()) / len(M),
            L=sum(t['L_serial_service_reconstructed_s'] for t in M.values()) / len(M))
    for name, base, X in (('delta_structure B-A', 'A', 'B'),
                          ('delta_hetero C-B', 'B', 'C')):
        base_map = {'A': A, 'B': B}[base]
        x_map = {'B': B, 'C': C}[X]
        h, m, per = help_harm(base_map, x_map, uids)  # X vs base
        out[name] = dict(
            help=h, harm=m,
            p_one_sided=round(mcnemar_one_sided(h, m), 5),
            delta_Q=round(sum(t['Q'] for t in x_map.values()) / len(x_map)
                          - sum(t['Q'] for t in base_map.values()) / len(base_map), 4),
            ci95=bootstrap_ci_delta(per))
    out['frozen200_aggregate_diagnostic'] = dict(
        source='FROZEN200_CORRECTED_SUMMARY.json (v1 scoring, 200 tasks)',
        clean_single=dict(Q=0.55, C=612.8, L=0.46),
        clean_static_hetero=dict(Q=0.335, C=1485.7, L=4.56),
        cube_same_model_aggregate=dict(source='cube_clean CUBE_CLEAN.json',
                                       note='same-model DAG aggregate exists '
                                            'but without task-level rows; '
                                            'task-level pairing uses this run'))
    return out


# ------------------------------------------------------------- Experiment 2
def exp2(rows, source_label):
    out = dict(role='RQ2: recovery attribution C vs D', source=source_label, states={})
    for state in ('clean', 'fault10', 'fault20', 'fault30'):
        kc, kd = ('mechanism', 'C_static_hetero', state), ('mechanism', 'D_dynamic_local', state)
        if kc not in rows or kd not in rows:
            continue
        C, D = task_map(rows[kc]), task_map(rows[kd])
        uids = sorted(C)
        h, m, per = help_harm(C, D, uids)
        faulted = [u for u in uids if C[u].get('faulted')]
        rec_calls = sum(D[u]['logical_calls'] - C[u]['logical_calls'] for u in uids)
        out['states'][state] = dict(
            Q_static=sum(t['Q'] for t in C.values()) / len(C),
            Q_dynamic=sum(t['Q'] for t in D.values()) / len(D),
            help=h, harm=m,
            p_one_sided=round(mcnemar_one_sided(h, m), 5),
            ci95=bootstrap_ci_delta(per),
            recovery_trigger_tasks=sum(1 for u in uids if D[u]['logical_calls'] > C[u]['logical_calls']),
            recovery_logical_calls=int(rec_calls),
            recovery_token_overhead=round(sum(D[u]['C_tokens'] - C[u]['C_tokens'] for u in uids) / len(uids), 1),
            faulted_tasks=len(faulted),
            detected_replaced=sum(1 for u in uids if D[u].get('replaced_calls', 0) > 0),
            note='detected / repaired / final-correct are distinct events; '
                 'see per-task rows for the full funnel')
    return out if out['states'] else None


# ------------------------------------------------------------- Experiment 3
def exp3(rows, source_label):
    out = dict(role='RQ2: local recovery (D) vs full replay (E)', source=source_label, states={})
    for state in ('clean', 'fault10', 'fault20', 'fault30'):
        kd, ke = ('mechanism', 'D_dynamic_local', state), ('mechanism', 'E_dynamic_full', state)
        if kd not in rows or ke not in rows:
            continue
        D, E = task_map(rows[kd]), task_map(rows[ke])
        uids = sorted(D)
        h, m, per = help_harm(D, E, uids)
        out['states'][state] = dict(
            Q_D=sum(t['Q'] for t in D.values()) / len(D),
            Q_E=sum(t['Q'] for t in E.values()) / len(E),
            C_D=sum(t['C_tokens'] for t in D.values()) / len(D),
            C_E=sum(t['C_tokens'] for t in E.values()) / len(E),
            L_D=sum(t['L_serial_service_reconstructed_s'] for t in D.values()) / len(D),
            L_E=sum(t['L_serial_service_reconstructed_s'] for t in E.values()) / len(E),
            calls_D=sum(t['logical_calls'] for t in D.values()),
            calls_E=sum(t['logical_calls'] for t in E.values()),
            help=h, harm=m, p_one_sided=round(mcnemar_one_sided(h, m), 5),
            ci95=bootstrap_ci_delta(per),
            replay_reuse_note='E re-executes the full graph; D reuses '
                              'unaffected branches (cache reuse is inside C/L)')
    return out if out['states'] else None


# ------------------------------------------------------------- Experiment 4
def exp4(rows, source_label):
    p = PRIMARY
    cells = {k: v for k, v in rows.items() if k[0] in ('mechanism', 'competitive')}
    if not cells:
        return None
    out = dict(role='RQ end-to-end net benefit', source=source_label,
               primary=dict(protocol=p['protocol'], state=p['state'],
                            budget=p['budget'], metric='Q_B'),
               families={}, budget_curves={}, gates={})
    for family in ('mechanism', 'competitive'):
        fam = {}
        for (prot, arm, state), rec in cells.items():
            if prot != family:
                continue
            M = task_map(rec)
            fam.setdefault(state, {})[arm] = dict(
                Q=sum(t['Q'] for t in M.values()) / len(M),
                Q_B={b: q_b(M, b) for b in BUDGETS},
                C=sum(t['C_tokens'] for t in M.values()) / len(M),
                L=sum(t['L_serial_service_reconstructed_s'] for t in M.values()) / len(M))
        out['families'][family] = fam

    # confirmatory gates (mechanism primary; competitive deployment family)
    for family in ('mechanism', 'competitive'):
        key1 = (family, p['gate1'][1], p['state'])
        keyD = (family, p['gate1'][0], p['state'])
        key2 = (family, p['gate2'][1], p['state'])
        if not all(k in cells for k in (key1, keyD, key2)):
            continue
        A = task_map(cells[key1]); D = task_map(cells[keyD]); A2 = task_map(cells[key2])
        uids = sorted(A)
        qD = q_b(D, p['budget']); qA = q_b(A, p['budget']); qA2 = q_b(A2, p['budget'])
        h1, m1, per1 = help_harm(A, D, uids, budget=p['budget'])
        gate1 = dict(delta_Q_B=round(qD - qA, 4), Q_B_D=round(qD, 4), Q_B_A=round(qA, 4),
                     help=h1, harm=m1, p_one_sided=round(mcnemar_one_sided(h1, m1), 6),
                     ci95=bootstrap_ci_delta(per1),
                     passed=bool(qD > qA and mcnemar_one_sided(h1, m1) <= 0.05))
        gate2 = None
        if gate1['passed']:
            h2, m2, per2 = help_harm(A2, D, uids, budget=p['budget'])
            gate2 = dict(delta_Q_B=round(qD - qA2, 4), Q_B_A2=round(qA2, 4),
                         help=h2, harm=m2,
                         p_one_sided=round(mcnemar_one_sided(h2, m2), 6),
                         ci95=bootstrap_ci_delta(per2),
                         passed=bool(qD > qA2 and mcnemar_one_sided(h2, m2) <= 0.05))
        out['gates'][family] = dict(gate1_D_vs_A=gate1,
                                    gate2_D_vs_A_prime=gate2,
                                    gate2_note='evaluated only if gate1 passed')

    # exploratory: all (state, budget) D vs A with Holm over the family
    expl = []
    for family in ('mechanism', 'competitive'):
        for state in ('clean', 'fault10', 'fault20', 'fault30'):
            kA, kD = (family, 'A_single', state), (family, 'D_dynamic_local', state)
            if kA not in cells or kD not in cells:
                continue
            A, D = task_map(cells[kA]), task_map(cells[kD])
            for b in BUDGETS:
                h, m, _ = help_harm(A, D, sorted(A), budget=b)
                expl.append(dict(family=family, state=state, budget=b,
                                 delta_Q_B=round(q_b(D, b) - q_b(A, b), 4),
                                 p=round(mcnemar_one_sided(h, m), 6)))
    if expl:
        adj = holm([e['p'] for e in expl])
        for e, a in zip(expl, adj):
            e['p_holm'] = round(a, 6)
        out['exploratory_holm'] = expl
    return out


# ------------------------------------------------------------- Experiment 6
def exp6(rows, source_label):
    out = dict(role='RQ3: Q/C and Q/C/L Pareto analysis per state',
               source=source_label,
               normalization=dict(Q=(0, 1), C=(0, 2500), L=(0, 12)), states={})
    for state in ('clean', 'fault10', 'fault20', 'fault30'):
        pts = []
        for arm in ('A_single', 'A_single_cross_fallback', 'B_same_model_dag',
                    'C_static_hetero', 'D_dynamic_local', 'E_dynamic_full',
                    'V2_static', 'V2_dynamic'):
            k = ('mechanism', arm, state)
            if k not in rows:
                continue
            M = task_map(rows[k])
            pts.append(dict(arm=arm,
                            Q=sum(t['Q'] for t in M.values()) / len(M),
                            C=sum(t['C_tokens'] for t in M.values()) / len(M),
                            L=sum(t['L_serial_service_reconstructed_s'] for t in M.values()) / len(M)))
        if not pts:
            continue
        def dominates(x, y):
            return (x['Q'] >= y['Q'] and x['C'] <= y['C'] and x['L'] <= y['L']
                    and (x['Q'], x['C'], x['L']) != (y['Q'], y['C'], y['L']))
        nd = [p for p in pts if not any(dominates(q, p) for q in pts if q is not p)]
        dominated = [p['arm'] for p in pts if p not in nd]
        out['states'][state] = dict(
            points=[{**p, 'Q': round(p['Q'], 4), 'C': round(p['C'], 1),
                     'L': round(p['L'], 3)} for p in pts],
            non_dominated=[p['arm'] for p in nd],
            dominated=dominated,
            note='L is serial service-demand reconstruction, NOT wall latency; '
                 'no online 3-objective claim')
    return out if out['states'] else None


def write_paired_csv(rows, path):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['protocol', 'state', 'arm', 'uid', 'Q', 'Q_v1',
                    'final_value', 'v21_gold', 'C_tokens', 'L_s',
                    'logical_calls', 'faulted', 'replaced_calls'])
        for (prot, arm, state), rec in sorted(rows.items()):
            for t in rec['tasks']:
                w.writerow([prot, state, arm, t['uid'], t['Q'],
                            t.get('Q_v1', ''), t.get('final_value', ''),
                            t.get('v21_gold', ''), t['C_tokens'],
                            round(t['L_serial_service_reconstructed_s'], 4),
                            t['logical_calls'], int(t.get('faulted', False)),
                            t.get('replaced_calls', 0)])


def run(stub=False):
    rows = load_rows()
    source = ('STUB dry-run (structural proof only — NOT scientific results)'
              if stub else 'NET-BENEFIT real execution')
    outputs = {}
    for name, fn, fname in (
            ('exp1', exp1, 'RQ1_PAIRED_QCL_RESULTS.json'),
            ('exp2', exp2, 'RECOVERY_ATTRIBUTION_RESULTS.json'),
            ('exp3', exp3, 'LOCAL_VS_FULL_RESULTS.json'),
            ('exp4', exp4, 'NET_BENEFIT_RESULTS.json'),
            ('exp6', exp6, 'PARETO_QCL_RESULTS.json')):
        try:
            res = fn(rows, source)
        except Exception as e:
            res = dict(error=repr(e))
        if res is not None:
            res['evidence_class'] = ('STRUCTURAL_DRY_RUN' if stub else 'REAL')
            (OUTDIR / fname).write_text(json.dumps(res, indent=1, default=str))
            outputs[name] = fname
    suffix = '_STUB' if stub else ''
    write_paired_csv(rows, OUTDIR / f'NET_BENEFIT_PAIRED_TASKS{suffix}.csv')
    print('derived:', outputs)
    if stub:
        g = (outputs.get('exp4') and
             json.loads((OUTDIR / 'NET_BENEFIT_RESULTS.json').read_text()).get('gates'))
        if g:
            print('stub gates (numbers meaningless, structure proof):',
                  {k: {kk: vv for kk, vv in v.items()
                       if kk in ('passed', 'delta_Q_B')} for k, v in g.items()})


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stub', action='store_true')
    run(stub=ap.parse_args().stub)
