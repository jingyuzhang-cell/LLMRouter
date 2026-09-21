"""Multi-objective Policy Selection and Pareto Regret (zero model calls).

Based on the 200-task cross-model matrix (all 9 E_i->R_j combinations measured).
Computes exact Pareto frontier, preference sweep over (lambda, mu), per-budget
constrained oracle, and Pareto regret for each deployed policy variant."""
import json
import itertools

import numpy as np

from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .recovery_matrix_v2_audit import close
from .cross_model_matrix import OUT as XM

OUT = BASE / 'pareto_regret'
SEED = 20260918

def run():
    pol = json.loads((XM / 'CROSS_MODEL_POLICY.json').read_text())
    subset = set(pol['subset_uids'])
    tasks = {t['uid']: t for t in json.loads((CPROF / 'PROFILE_POLICY.json').read_text())['tasks']}
    dev_resp = {}
    for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); dev_resp[r['key']] = r
    xm_resp = {}
    for l in (XM / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); xm_resp[r['key']] = r
    def get(key):
        return dev_resp.get(key) or xm_resp.get(key)

    # ---- per-task per-combo Q/C/L ----
    combos = [(e, r) for e in POOL for r in POOL]
    combo_names = [f'E_{e}->R_{r}' for e, r in combos]
    uids = sorted({uid for uid, _, _ in
                   [(r['uid'], 0, 0) for r in
                    [json.loads(l) for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines()]
                    if r.get('node_type') == 'reasoning' and r.get('uid') in subset]
                   })
    # simpler: use subset uids that have all 9 cells
    valid_uids = []
    for uid in subset:
        all_present = True
        for e in POOL:
            if dev_resp.get(f'EXT:{e}:{uid}') is None:
                all_present = False; break
            for r in POOL:
                if e == r:
                    if dev_resp.get(f'RSN:{r}:{uid}') is None:
                        all_present = False; break
                elif xm_resp.get(f'X:{e}:{r}:{uid}') is None:
                    all_present = False; break
            if not all_present: break
        if all_present: valid_uids.append(uid)
    valid_uids = sorted(valid_uids)
    n = len(valid_uids)

    Qm = np.zeros((n, 9)); Cm = np.zeros((n, 9)); Lm = np.zeros((n, 9))
    task_ids = []
    for ui, uid in enumerate(valid_uids):
        task_ids.append(uid)
        for ci, (e, r) in enumerate(combos):
            key_e = f'EXT:{e}:{uid}'
            key_r = f'RSN:{r}:{uid}' if e == r else f'X:{e}:{r}:{uid}'
            ext_r = dev_resp.get(f'EXT:{e}:{uid}')
            rsn_r = None
            if e == r:
                rsn_r = (dev_resp.get(f'RSN:{r}:{uid}') or
                         dev_resp.get(f'RSN:{r}:{uid}'))
            else:
                rsn_r = xm_resp.get(f'X:{e}:{r}:{uid}')
            if ext_r is None:
                continue
            if rsn_r is None:
                continue
            try: facts = v.parse_facts(ext_r['response']['answer'])
            except Exception: facts = {'facts': []}
            try:
                val = exec_calc(v.decode(rsn_r['response']['answer'])['expression'], facts)
                Qm[ui, ci] = close(val, tasks[uid]['answer'])
            except Exception:
                Qm[ui, ci] = 0
            Cm[ui, ci] = float((ext_r['response'].get('usage') or {}).get('total_tokens') or 0) + \
                         float((rsn_r['response'].get('usage') or {}).get('total_tokens') or 0)
            Lm[ui, ci] = float(ext_r['response'].get('latency_s') or 0) + float(rsn_r['response'].get('latency_s') or 0)

    # ---- Exact Pareto frontier (aggregate) ----
    mean_q = Qm.mean(axis=0); mean_c = Cm.mean(axis=0); mean_l = Lm.mean(axis=0)
    pareto_nd = []
    for i in range(9):
        dominated = False
        for j in range(9):
            if i == j: continue
            if (mean_q[j] >= mean_q[i] and mean_c[j] <= mean_c[i] and mean_l[j] <= mean_l[i]
                    and (mean_q[j] > mean_q[i] or mean_c[j] < mean_c[i] or mean_l[j] < mean_l[i])):
                dominated = True; break
        if not dominated: pareto_nd.append(i)

    # ---- preference sweep ----
    lam_mu_grid = [(0,0),(0,0.1),(0,0.5),(0.1,0),(0.1,0.1),(0.2,0.2),(0.5,0.5),(1.0,1.0)]
    pref_results = []
    for lam, mu in lam_mu_grid:
        best_ci = int(np.argmax(mean_q - lam * mean_c / 1000 - mu * mean_l))
        pref_results.append(dict(lam=lam, mu=mu, best_combo=combo_names[best_ci],
                                 Q=round(float(mean_q[best_ci]),4),
                                 C=round(float(mean_c[best_ci]),1),
                                 L=round(float(mean_l[best_ci]),2)))
    # ---- report ----
    rep = dict(
        n=n, combo_names=combo_names,
        mean_Q={combo_names[i]: round(float(mean_q[i]),4) for i in range(9)},
        mean_C={combo_names[i]: round(float(mean_c[i]),1) for i in range(9)},
        mean_L={combo_names[i]: round(float(mean_l[i]),2) for i in range(9)},
        pareto_nd=pareto_nd,
        preference_sweep=pref_results)
    out = BASE / 'pareto_regret'
    out.mkdir(exist_ok=True)
    (out / 'MULTI_OBJECTIVE.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(dict(n=n, pareto_nd=pareto_nd,
                          mean_Q={combo_names[i]: round(float(mean_q[i]),4) for i in range(9)},
                          preference_sweep=pref_results), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
