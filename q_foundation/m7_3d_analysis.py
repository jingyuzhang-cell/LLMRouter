"""M7-3D Frozen Analysis Script (PRE-REGISTERED, zero-call).

D4 EXCLUSION RULE and all endpoint definitions are FROZEN before execution.
This script MUST NOT be modified after M7-3D GO is issued.
"""
import json
from pathlib import Path

RESULTS_DIR = Path('/root/cap_eval_bench_v1/m7_3d_runs')
REFERENCE_FACTS = json.load(open(
    Path(__file__).parent / 'M7_3D_REFERENCE_FACTS.json'))

def exclude_d4(state):
    faulted = [n for n in state.get('nodes', [])
               if n.get('status') == 'failed']
    return len(faulted) > 1

def ep1(runs):
    f = [r for r in runs if r['arm'] == 'F']
    c = sum(1 for r in f if r.get('mechanism_correct'))
    return {'ep': 'EP1', 'correct': c, 'total': len(f), 'level': 'MECHANISM'}

def ep2a(runs):
    pairs = []
    for cell in set(r['cell'] for r in runs):
        f = next((r for r in runs if r['arm']=='F' and r['cell']==cell), None)
        b = next((r for r in runs if r['arm']=='B' and r['cell']==cell), None)
        if f and b and 'C1' in cell:
            pairs.append({'cell': cell, 'f_waste': f.get('wasted_tokens',0),
                         'b_waste': b.get('wasted_tokens',0),
                         'f_ok': f['status']=='COMPLETE',
                         'b_ok': b['status']=='COMPLETE'})
    return {'ep': 'EP2a', 'pairs': pairs, 'level': 'EXPLORATORY'}

def ep3(runs):
    fa, fe = [], []
    for cell in set(r['cell'] for r in runs):
        f = next((r for r in runs if r['arm']=='F' and r['cell']==cell), None)
        a = next((r for r in runs if r['arm']=='A' and r['cell']==cell), None)
        e = next((r for r in runs if r['arm']=='E' and r['cell']==cell), None)
        if f and a:
            fa.append({'cell': cell, 'f_ok': f['status']=='COMPLETE',
                      'a_ok': a['status']=='COMPLETE',
                      'f_q': f.get('Q_terminal'), 'a_q': a.get('Q_terminal')})
        if f and e:
            fe.append({'cell': cell, 'f_ok': f['status']=='COMPLETE',
                      'e_ok': e['status']=='COMPLETE',
                      'f_q': f.get('Q_terminal'), 'e_q': e.get('Q_terminal')})
    return {'ep': 'EP3', 'f_vs_a': fa, 'f_vs_e': fe, 'level': 'EXPLORATORY'}

def ep4(runs, d4_excluded):
    eligible = [r for r in runs if r['arm'] in ('F','F_prime')
                and r['state'] not in d4_excluded]
    return {'ep': 'EP4a+EP4b', 'eligible': len(eligible),
            'd4_excluded': len(d4_excluded), 'level': 'EXPLORATORY',
            'note': 'D1/D2 (EP4a) and D3 (EP4b) reported separately'}

def ep5(runs):
    pairs = []
    for task in ('E04', 'E06'):
        auto = next((r for r in runs if r['arm']=='A' and r.get('dag_type')=='auto'
                     and task in r['cell']), None)
        ref = next((r for r in runs if r['arm']=='A' and r.get('dag_type')=='ref'
                     and task in r['cell']), None)
        if auto and ref:
            pairs.append({'task': task, 'auto_q': auto.get('Q_terminal'),
                         'ref_q': ref.get('Q_terminal')})
    return {'ep': 'EP5', 'pairs': pairs, 'level': 'EXPLORATORY'}

def ep6(runs):
    v = [r['cell'] for r in runs if r.get('constraint_violation')]
    return {'ep': 'EP6', 'violations': len(v), 'detail': v, 'level': 'HARD_GATE'}

def main():
    runs = json.load(open(RESULTS_DIR / 'RESULTS.json'))
    d4 = [r['state'] for r in runs if exclude_d4(r.get('state', {}))]
    out = {'ep1': ep1(runs), 'ep2a': ep2a(runs), 'ep3': ep3(runs),
           'ep4': ep4(runs, d4), 'ep5': ep5(runs), 'ep6': ep6(runs)}
    (RESULTS_DIR / 'ANALYSIS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))

if __name__ == '__main__':
    main()
