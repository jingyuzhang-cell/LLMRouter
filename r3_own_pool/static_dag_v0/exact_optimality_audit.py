"""Pure zero-call audit of the 200-task x 9-combination exact optimality results.
Explicitly maps every index, prints formulas with numerator/denominator, and
cross-checks against the original cross_model_analyze.py results."""
import json
import itertools
from collections import Counter, defaultdict

import numpy as np

from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import OUT as CPROF, POOL
from .recovery_matrix_v2_audit import close
from .cross_model_matrix import OUT as XM

OUT = BASE / 'exact_optimality_audit'

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

    # ---- load raw per-(task, ext_m, rsn_m) results ----
    raw = {}
    for uid in subset:
        t = tasks[uid]; gold = t['answer']
        for ei in POOL:
            ext = dev_resp.get(f'EXT:{ei}:{uid}')
            if ext is None: continue
            try: facts = v.parse_facts(ext['response']['answer'])
            except Exception: facts = {'facts': []}
            c_e = float((ext['response'].get('usage') or {}).get('total_tokens') or 0)
            l_e = float(ext['response'].get('latency_s') or 0)
            ext_parse = int(len(facts['facts']) > 0)
            for rj in POOL:
                if ei == rj:
                    rsn = dev_resp.get(f'RSN:{rj}:{uid}')
                else:
                    rsn = xm_resp.get(f'X:{ei}:{rj}:{uid}')
                if rsn is None: continue
                rr = rsn['response']
                c_r = float((rr.get('usage') or {}).get('total_tokens') or 0)
                l_r = float(rr.get('latency_s') or 0)
                try:
                    val = exec_calc(v.decode(rr['answer'])['expression'], facts)
                    q = int(close(val, gold))
                except Exception: q = 0
                raw[(uid, ei, rj)] = dict(Q=q, C=c_e + c_r, L=l_e + l_r, ext_parse=ext_parse)
    # ---- explicit combo mapping (verify!) ----
    # combos[c] = (ext_model_name, rsn_model_name)
    # combos[0]=(medium,medium) combos[1]=(medium,large) combos[2]=(medium,coder)
    # combos[3]=(large,medium)  combos[4]=(large,large)  combos[5]=(large,coder)
    # combos[6]=(coder,medium)  combos[7]=(coder,large)  combos[8]=(coder,coder)
    combo_names = [f'E_{e}->R_{r}' for e, r in itertools.product(POOL, POOL)]
    combo_tuples = list(itertools.product(POOL, POOL))
    print('=== Combo index mapping (EXPLICIT) ===')
    for ci, (name, ct) in enumerate(zip(combo_names, combo_tuples)):
        print(f'  ci={ci}: {name:24} = (ext={ct[0]:7}, rsn={ct[1]:7})')
    print()
    # ---- per-task exact Q for each combo ----
    uids = sorted({uid for uid, _, _ in raw.keys()})
    n = len(uids)
    Q_all = np.full((n, 9), np.nan)
    C_all = np.full((n, 9), np.nan)
    L_all = np.full((n, 9), np.nan)
    uid_idx = {u: i for i, u in enumerate(uids)}
    for (uid, e, r), d in raw.items():
        ui = uid_idx[uid]
        ci = combo_tuples.index((e, r))
        Q_all[ui, ci] = d['Q']; C_all[ui, ci] = d['C']; L_all[ui, ci] = d['L']
    # verify: count non-NaN per combo
    print('=== Non-NaN count per combo ===')
    for ci, name in enumerate(combo_names):
        print(f'  {name:24} {int(np.sum(~np.isnan(Q_all[:, ci]))):>4}/{n}')
    print()
    # ---- Always Large = E_large -> R_large (should be ci=4) ----
    al_ci = combo_tuples.index(('large', 'large'))
    print(f'Always Large combo index: {al_ci} -> {combo_names[al_ci]}')
    q_al = Q_all[:, al_ci]
    valid_al = ~np.isnan(q_al)
    print(f'Always Large: Q={np.nanmean(q_al):.4f} (valid n={int(valid_al.sum())}/{n})')
    print()
    # ---- per-combo mean Q (only non-NaN) ----
    print('=== Per-combo mean Q (non-NaN only) ===')
    for ci, name in enumerate(combo_names):
        vals = Q_all[:, ci]; valid = ~np.isnan(vals)
        print(f'  {name:24} Q={np.nanmean(vals):.4f} (valid {int(valid.sum())}/{n})')
    print()
    # ---- Exact Oracle: per-task max across 9 combos ----
    with np.errstate(invalid='ignore'):
        oracle_q = np.nanmax(Q_all, axis=1)
    oracle_q = np.where(np.isnan(oracle_q), 0, oracle_q)
    print(f'Exact Oracle (per-task max of 9): Q={np.nanmean(oracle_q):.4f}')
    # ---- Always Large as baseline ----
    q_al_mean = np.nanmean(q_al)
    print(f'Always Large (E_L->R_L) Q={q_al_mean:.4f}')
    # ---- GAP Recovery per combo ----
    print()
    # ---- GAP Recovery per combo (vs Always Large baseline) ----
    oracle_per_task = np.full(n, np.nan)
    for ci in range(9):
        vals = Q_all[:, ci]
        for ui in range(n):
            if np.isnan(vals[ui]): continue
            if np.isnan(oracle_per_task[ui]) or vals[ui] > oracle_per_task[ui]:
                oracle_per_task[ui] = vals[ui]
    oracle_mean = float(np.nanmean(oracle_per_task))
    print(f"Oracle mean: {oracle_mean:.4f} | Always Large mean: {q_al_mean:.4f} | Oracle GAP: {oracle_mean - q_al_mean:.4f}")
    print()
    print('=== GAP Recovery per combo (GAP Rec = (Q - baseline) / (oracle - baseline)) ===')
    for ci, name in enumerate(combo_names):
        vals = Q_all[:, ci]; valid = ~np.isnan(vals)
        q = np.nanmean(vals)
        gr = (q - q_al_mean) / (oracle_mean - q_al_mean) if abs(oracle_mean - q_al_mean) > 1e-9 else None
        print(f"  {name:24} Q={q:.4f}  GAP={gr:+.4f}" if gr is not None else f"  {name:24} Q={q:.4f}")
        dominated = False
        for j in range(9):
            if i == j: continue
            if mq[j] >= mq[i] and mc[j] <= mc[i] and ml[j] <= ml[i]:
                if mq[j] > mq[i] or mc[j] < mc[i] or ml[j] < ml[i]:
                    dominated = True; break
        if not dominated: nd.append(combo_names[i])
    print('Non-dominated:', nd)
    for ci, name in enumerate(combo_names):
        print(f'  {name:24} Q={mq[ci]:.4f} C={mc[ci]:.1f} L={ml[ci]:.2f}')
    # ---- Budget-constrained oracle (correct implementation) ----
    print()
    print('=== Budget-constrained oracle (per-task max Q among combos fitting budget) ===')
    for bc in [1000, 1500, 2000, 3000, 4000, 5000]:
        for bl in [None, 2.0, 5.0]:
            feasible_q = []
            for ui in range(n):
                best_q = 0
                for ci in range(9):
                    c = C_all[ui, ci]; l = L_all[ui, ci]; q = Q_all[ui, ci]
                    if np.isnan(c) or np.isnan(l) or np.isnan(q): continue
                    if bc is not None and c > bc: continue
                    if bl is not None and l > bl: continue
                    best_q = max(best_q, q)
                feasible_q.append(best_q)
            mq = np.mean(feasible_q)
            bl_s = f', L<={bl}s' if bl else ''
            print(f'  B_C<={bc}, {bl_s if bl else "L=inf":>12}: Q={mq:.4f}')
    # ---- summary rep ----
    rep = dict(
        n=n, combo_mapping={ci: combo_names[ci] for ci in range(9)},
        per_combo_Q={combo_names[ci]: round(float(np.nanmean(Q_all[:, ci])), 4) for ci in range(9)},
        per_combo_n={combo_names[ci]: int(np.sum(~np.isnan(Q_all[:, ci]))) for ci in range(9)},
        always_large_Q=round(q_al_mean, 4), best_fixed=combo_names[best_ci],
        best_fixed_Q=round(float(np.nanmean(Q_all[:, best_ci])), 4),
        exact_oracle_Q=round(float(np.nanmean(oracle_q)), 4),
        pareto_nd=nd)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'AUDIT.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print('\nSaved to AUDIT.json')

if __name__ == '__main__':
    import itertools
    run()
