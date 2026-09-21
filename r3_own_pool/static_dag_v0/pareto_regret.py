"""Multi-objective Policy Selection and Pareto Regret — zero model calls.
Uses the 200-task cross-model subset where all 9 (E_i, R_j) combos are measured.
Computes exact Pareto frontier and preference sweep over (lambda, mu) utility."""
import json
import itertools
import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF
from .recovery_matrix_v2_audit import close

OUT = BASE / 'multi_objective_pareto'
POOL = ['medium', 'large', 'coder']
COMBOS = [(e, r) for e in POOL for r in POOL]
COMBO_NAMES = [f'E_{e}->R_{r}' for e, r in COMBOS]

def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def load_matrix():
    """Build Q[task, combo], C[task, combo], L[task, combo] from existing data."""
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    tasks = {t['uid']: t for t in pol['tasks']}
    dev_resp = {}
    for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); dev_resp[r['key']] = r
    xm_resp = {}
    xm_file = BASE / 'cross_model_matrix/RESPONSES.jsonl'
    if xm_file.exists():
        for l in xm_file.read_text().splitlines():
            r = json.loads(l); xm_resp[r['key']] = r
    def get(key):
        return dev_resp.get(key) or xm_resp.get(key)
    uids = sorted(tasks.keys())
    all_q = []; all_c = []; all_l = []; valid_uids = []
    for uid in uids:
        ext_ok = all(f'EXT:{m}:{uid}' in dev_resp for m in POOL)
        if not ext_ok: continue
        qi = []; ci = []; li = []
        for m in POOL:
            e = dev_resp.get(f'EXT:{m}:{uid}')
            if e is None:
                qi.append(0); ci.append(3000); li.append(5.0); continue
            try: facts = v.parse_facts(e['response']['answer'])
            except Exception: facts = {'facts': []}
            try:
                val = exec_calc(v.decode(e['response']['answer'])['expression'], facts)
            except Exception: val = None
            ci.append(float((e['response'].get('usage') or {}).get('total_tokens') or 0))
            li.append(float(e['response'].get('latency_s') or 0))
            qi.append(1.0 if val is not None and abs(val - tasks[uid]['answer']) <= max(1e-4, 1e-4 * abs(tasks[uid]['answer'])) else 0.0)
        all_q.append(qi); all_c.append(ci); all_l.append(li); valid_uids.append(uid)
    return (np.array(all_q), np.array(all_c), np.array(all_l), valid_uids, tasks)

def run():
    Q, C, L, uids, tasks = load_matrix()
    n = len(uids)
    mean_q = Q.mean(axis=0); mean_c = C.mean(axis=0); mean_l = L.mean(axis=0)
    print(f'n tasks: {n}')
    print(f'mean Q per combo: {dict(zip(COMBO_NAMES, np.round(mean_q, 4)))}')
    print(f'mean C per combo: {dict(zip(COMBO_NAMES, np.round(mean_c, 1)))}')
    print(f'mean L per combo: {dict(zip(COMBO_NAMES, np.round(mean_l, 2)))}')
    # Pareto frontier
    nd = []
    for i in range(9):
        dominated = False
        for j in range(9):
            if i == j: continue
            if (mean_q[j] >= mean_q[i] and mean_c[j] <= mean_c[i] and mean_l[j] <= mean_l[i]
                    and (mean_q[j] > mean_q[i] or mean_c[j] < mean_c[i] or mean_l[j] < mean_l[i])):
                dominated = True; break
        if not dominated: nd.append(i)
    print(f'\nPareto non-dominated combos: {[COMBO_NAMES[i] for i in nd]}')
    # preference sweep
    print('\n=== Preference sweep (lambda, mu) -> best combo ===')
    for lam in [0, 0.01, 0.05, 0.1, 0.5]:
        for mu in [0, 0.01, 0.05, 0.1, 0.5]:
            scores = mean_q - lam * mean_c / 1000 - mu * mean_l
            best = int(np.argmax(scores))
            print(f'  lam={lam:5.2f} mu={mu:5.2f} -> {COMBO_NAMES[best]} (Q={mean_q[best]:.4f}, C={mean_c[best]:.0f}, L={mean_l[best]:.2f})')
    # budget-constrained oracle
    print('\n=== Budget-constrained oracle ===')
    for bc in [1000, 2000, 3000, 4000, 5000]:
        for bl in [2, 5, None]:
            best_q = 0; best_c = 0; best_l = 0
            for i in range(n):
                for j in range(9):
                    if C[j, i] is not None and C[j, i] <= bc and L[j, i] <= (bl if bl else 1e9):
                        if Q[j, i] > best_q: best_q = Q[j, i]
            bl_s = f'{bl}' if bl else 'inf'
            print(f'  B_C<={bc}, B_L<={bl_s}: Q={best_q:.4f}')

if __name__ == '__main__':
    run()
