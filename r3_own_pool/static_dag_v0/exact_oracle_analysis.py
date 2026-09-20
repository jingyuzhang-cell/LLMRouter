"""Exact Oracle / Optimality Gap / Exact Pareto Frontier for the 2-node DAG
(extraction -> reasoning) on the 200-task cross-model subset.

All 9 (E_i, R_j) combinations are already measured (diagonal from capability_profiling;
off-diagonal from cross_model_matrix). We enumerate all model assignments, compute
Q/C/L exactly, find the exact optimum, and compare with deployed policies.

This is the definitive answer to: "How far is your policy from the true optimum?"
"""
import json
from collections import Counter, defaultdict

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .recovery_matrix_v2_audit import close
from .cross_model_matrix import OUT as XM

OUT = BASE / 'exact_oracle'

def run():
    pol = json.loads((XM / 'CROSS_MODEL_POLICY.json').read_text())
    subset = set(pol['subset_uids'])
    tasks = {t['uid']: t for t in json.loads((CPROF / 'PROFILE_POLICY.json').read_text())['tasks']}
    # load all responses from both sources
    dev_resp = {}
    for l in (CPROF / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); dev_resp[r['key']] = r
    xm_resp = {}
    for l in (XM / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l); xm_resp[r['key']] = r
    def get(key):
        return dev_resp.get(key) or xm_resp.get(key)
    # for each task x each (ext_model, rsn_model): compute Q, C, L
    rows = []
    for uid in subset:
        t = tasks[uid]; gold = t['answer']
        for ei in POOL:
            ext_key = f'EXT:{ei}:{uid}'
            if ext_key not in dev_resp: continue
            ext_r = dev_resp[ext_key]
            try: facts = v.parse_facts(ext_r['response']['answer'])
            except Exception: facts = {'facts': []}
            c_ext = float((ext_r['response'].get('usage') or {}).get('total_tokens') or 0)
            l_ext = float(ext_r['response'].get('latency_s') or 0)
            ext_parse = int(len(facts['facts']) > 0)
            for rj in POOL:
                rsn_key = f'RSN:{rj}:{uid}' if ei == rj else f'X:{ei}:{rj}:{uid}'
                rsn_r = get(rsn_key)
                if rsn_r is None: continue
                c_rsn = float((rsn_r['response'].get('usage') or {}).get('total_tokens') or 0)
                l_rsn = float(rsn_r['response'].get('latency_s') or 0)
                try:
                    val = exec_calc(v.decode(rsn_r['response']['answer'])['expression'], facts)
                    q = int(close(val, gold))
                except Exception:
                    q = 0
                rows.append(dict(uid=uid, ext_m=ei, rsn_m=rj,
                                 Q=q, C=c_ext + c_rsn, L=l_ext + l_rsn))
    # convert to arrays grouped by task
    by_task = {}
    for r in rows: by_task.setdefault(r['uid'], []).append(r)
    # full enumeration
    combos = [(e, r) for e in POOL for r in POOL]  # 9 combos
    n = len(by_task)
    # per-task per-combo Q/C/L
    Qm = np.zeros((n, 9)); Cm = np.zeros((n, 9)); Lm = np.zeros((n, 9))
    task_ids = sorted(by_task.keys())
    task_idx = {u: i for i, u in enumerate(task_ids)}
    combo_names = [f'E_{e}->R_{r}' for e, r in combos]
    for ui, uid in enumerate(task_ids):
        for ci, (e, r) in enumerate(combos):
            for row in by_task[uid]:
                if row['ext_m'] == e and row['rsn_m'] == r:
                    Qm[ui, ci] = row['Q']; Cm[ui, ci] = row['C']; Lm[ui, ci] = row['L']
                    break
            else:
                Qm[ui, ci] = 0; Cm[ui, ci] = 3000; Lm[ui, ci] = 5.0  # default penalty
    # exact optimal per task (max Q, min C tiebreak, min L tiebreak)
    opt_ci = np.argmin(np.where(
        (Qm == Qm.max(axis=1, keepdims=True)),
        Cm * 1000 + Lm, np.inf), axis=1)
    opt_q = Qm[np.arange(n), opt_ci]
    opt_c = Cm[np.arange(n), opt_ci]
    opt_l = Lm[np.arange(n), opt_ci]
    # policy baselines
    # Always Large (same model): E_large -> R_large
    li = POOL.index('large')
    q_always_large = Qm[:, li]
    c_always_large = Cm[:, li]; l_always_large = Lm[:, li]
    # Type Prior: ext=large, rsn=medium (from fresh benchmark)
    ti_e = POOL.index('large'); ti_r = POOL.index('medium')
    q_tp = Qm[:, ti_r]  # task Q determined by reasoning output quality on ext_large facts
    c_tp = Cm[:, ti_e] + Cm[:, ti_r]; l_tp = Lm[:, ti_e] + Lm[:, ti_r]
    # Best Single (large for both, but reasoning on large's own extraction)
    q_bs = Qm[:, li]
    # per-policy exact Q/C/L
    def stats(q, c, l):
        return dict(Q=round(float(np.mean(q)), 4), C=round(float(np.mean(c)), 1),
                    L=round(float(np.mean(l)), 2))
    # Oracle (exact)
    q_oracle = Qm.max(axis=1)
    oracle_gap_exact = float(q_oracle.mean() - q_always_large.mean())
    # Exact Pareto frontier
    def is_dominated(i, all_q, all_c, all_l):
        for j in range(all_q.shape[1]):
            if j == i: continue
            if (all_q[:, j] >= all_q[:, i]).all() and (all_c[:, j] <= all_c[:, i]).all() \
               and (all_l[:, j] <= all_l[:, i]).all() and \
               (all_q[:, j] > all_q[:, i] or all_c[:, j] < all_c[:, i] or all_l[:, j] < all_l[:, i]):
                return True
        return False
    # simple aggregate Pareto: non-dominated across mean Q/C/L
    mean_q = Qm.mean(axis=0); mean_c = Cm.mean(axis=0); mean_l = Lm.mean(axis=0)
    nd = []
    for i in range(9):
        dominated = False
        for j in range(9):
            if i == j: continue
            if mean_q[j] >= mean_q[i] and mean_c[j] <= mean_c[i] and mean_l[j] <= mean_l[i]:
                if mean_q[j] > mean_q[i] or mean_c[j] < mean_c[i] or mean_l[j] < mean_l[i]:
                    dominated = True; break
        if not dominated: nd.append(i)
    # Exact Pareto for mean assignment
    per_combo = []
    for ci, name in enumerate(combo_names):
        per_combo.append(dict(
            combo=name, Q=round(float(Qm[:, ci].mean()), 4),
            C=round(float(Cm[:, ci].mean()), 1), L=round(float(Lm[:, ci].mean()), 2)))
    # GAP Recovery for each (ext, rsn) policy
    gap_recovery = {}
    baseline_q = q_always_large.mean()
    gap_total = q_oracle.mean() - baseline_q
    for ci, name in enumerate(combo_names):
        q = Qm[:, ci].mean()
        gap_recovery[name] = round((q - baseline_q) / gap_total, 4) if gap_total > 0 else None
    rep = dict(
        n=n, combos=combo_names,
        exact_oracle=dict(
            Q=round(float(q_oracle.mean()), 4), C=round(float(opt_c.mean()), 1),
            L=round(float(opt_l.mean()), 2)),
        always_large=dict(Q=round(float(q_always_large.mean()), 4),
                          C=round(float(c_always_large.mean()), 1),
                          L=round(float(l_always_large.mean()), 2)),
        optimality_gap_pp=round(float(q_oracle.mean() - q_always_large.mean()), 4),
        optimality_recovery=round(float(q_always_large.mean() / max(1e-9, q_oracle.mean())), 4),
        exact_pareto_nd=[combo_names[i] for i in nd if (mean_q[i], mean_c[i], mean_l[i]) != (mean_q.max(), mean_c.min(), mean_l.min())],
        per_combo=per_combo,
        per_combo_optimality_gap={combo_names[ci]: round(float(q_oracle.mean() - Qm[:, ci].mean()), 4)
                                  for ci in range(9)},
        gap_recovery_per_combo=gap_recovery,
    )
    out = BASE / 'exact_oracle'
    out.mkdir(exist_ok=True)
    (out / 'EXACT_ORACLE.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(dict(
        n=n, oracle_Q=rep['exact_oracle']['Q'], always_large_Q=rep['always_large']['Q'],
        optimality_gap_pp=rep['optimality_gap_pp'],
        exact_pareto_nd=rep['exact_pareto_nd'],
        per_combo=per_combo,
        per_combo_gap=gap_recovery,
    ), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run()
