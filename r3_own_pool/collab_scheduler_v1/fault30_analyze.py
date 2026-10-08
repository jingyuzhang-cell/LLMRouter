"""fault30 analyzer — frozen evaluation order (evidence-governance pass):

  1 provenance        every fault seed's injected tasks/nodes fully traceable
  2 paired effect     clean->fault deltas really attributable to faults
                     (Help/Harm/McNemar; faulted-task-only vs unfaulted control)
  3 Z value           D_Z Q / D_Z C / D_Z L per (DynamicDAG, X); flag
                     recovery-induced Pareto trade-offs (D_Z Q > 0 with cost)
  4 Y/X rank shift    clean vs fault rankings, flip detection
  5 Pareto            P*_fault vs P*_clean, front expansion, HV both states

Framing (paper wording rule): fault30 is a STATE INTERVENTION under the frozen
fault model — conclusions are about the value of recovery strategies under
that intervention, not claims about model capability change in general.

Reads clean per-task rows via cube_analyze.evaluate() (zero-call) and
fault30_prep/FAULT30_RESULTS.json (fault30_run output). Writes
FAULT30_ANALYSIS.json. Run: python3 -m collab_scheduler_v1.fault30_analyze
"""
import json
import math
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1'
F30 = OUT / 'fault30_prep/FAULT30_RESULTS.json'


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def order_flips(m_clean, m_fault, tol=0.01):
    """Pairs whose order differs beyond tol between the two rankings."""
    flips = []
    for a, b in combinations(set(m_clean) & set(m_fault), 2):
        d1, d2 = m_clean[a] - m_clean[b], m_fault[a] - m_fault[b]
        if (d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol):
            flips.append((a, b))
    return flips


def run():
    sys.path.insert(0, str(ROOT))
    from collab_scheduler_v1 import cube_analyze, fault30_protocol
    from sa_pgfs_v1.pareto import hypervolume

    fault = None
    if F30.exists():
        fault = json.loads(F30.read_text())
    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
                       .read_text())['tasks']
    uids = [t['uid'] for t in tasks]
    task_by_uid = {t['uid']: t for t in tasks}
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json').read_text())
    clean_eval = cube_analyze.evaluate(tasks)
    clean_rows = {cid: {r['uid']: r for r in v['per_task']}
                  for cid, v in clean_eval.items()}
    clean_summary = {cid: dict(Q=v['Q'], C=v['C'], L=v['L'], n=v['n'])
                     for cid, v in clean_eval.items() if v['n'] == v['n_total']}

    out = dict(framing='fault30 = state intervention under the frozen fault model; '
                        'recovery-value conclusions only, no capability-change claims',
               clean_summary=clean_summary)

    # clean-side Y/X rankings (for step 4)
    ym, xm = {}, {}
    for cid, v in clean_summary.items():
        if not cid.endswith('__NONE__FRESH'):
            continue
        topo, fam, _, _ = cid.split('__')
        ym.setdefault(topo, []).append(v['Q'])
        xm.setdefault(fam, []).append(v['Q'])
    clean_Y = {k: round(sum(v) / len(v), 4) for k, v in ym.items()}
    clean_X = {k: round(sum(v) / len(v), 4) for k, v in xm.items()}
    out['clean_rankings'] = dict(Y_mean_Q=clean_Y, X_mean_Q=clean_X)

    if fault is None:
        (OUT / 'FAULT30_ANALYSIS.json').write_text(json.dumps(out, indent=1))
        print('FAULT30_RESULTS.json not present; clean side summarized only. '
              'Rerun after the fault30 stage completes.')
        return

    # ---- 1 provenance ----
    prov = {}
    prov_ok = True
    for seed in fault['seeds']:
        faults = fault30_protocol.build_faults(
            int(seed), fault30_protocol.RATE, tasks, pools)
        drawn_active = {u: fault30_protocol.map_fault_node(
            n, cid_topo) for cid_topo in ()}  # per-config below
        s = dict(drawn=len(faults), per_config={})
        for cid in fault30_protocol.CONFIGS:
            topo, fam, z, nodes = fault30_protocol.planned_models(cid)
            rows = fault['seeds'][seed].get(cid, {})
            mismatches = []
            for u, (node, failing) in faults.items():
                mapped = fault30_protocol.map_fault_node(node, topo)
                if not mapped or mapped not in nodes:
                    continue  # latent v-fault on v-less topology (frozen rule)
                r = rows.get(u)
                if r is None or not r.get('faulted') or r.get('fault_node') != mapped:
                    mismatches.append(u)
            s['per_config'][cid] = dict(
                active=sum(1 for u, (n, _) in faults.items()
                           if fault30_protocol.map_fault_node(n, topo)
                           and fault30_protocol.map_fault_node(n, topo) in nodes),
                mismatched_traces=len(mismatches), examples=mismatches[:3])
            prov_ok = prov_ok and not mismatches
        prov[seed] = s
    out['step1_provenance'] = dict(per_seed=prov, all_traceable=prov_ok)

    # ---- 2 paired fault effect ----
    per_cfg, paired, attributable, internal_anchor = {}, {}, {}, {}
    for cid in fault30_protocol.CONFIGS:
        agg = dict(Q=[], C=[], L=[])
        help_n = harm_n = f_help = f_harm = 0
        unf_mismatch = unf_n = 0
        for seed in fault['seeds']:
            srows = fault['seeds'][seed][cid]
            qs = [srows[u]['ok'] for u in uids]
            agg['Q'].append(sum(qs) / len(qs))
            agg['C'].append(sum(srows[u]['used'] for u in uids) / len(uids))
            agg['L'].append(sum(srows[u]['lat'] for u in uids) / len(uids))
            for u in uids:
                fr, cr = srows[u], clean_rows[cid][u]
                if cr['ok'] and not fr['ok']:
                    harm_n += 1
                if not cr['ok'] and fr['ok']:
                    help_n += 1
                if fr.get('faulted'):
                    if not cr['ok'] and fr['ok']:
                        f_help += 1
                    elif cr['ok'] and not fr['ok']:
                        f_harm += 1
                elif cid.endswith('__NONE__FRESH'):
                    unf_n += 1
                    if fr['ok'] != cr['ok'] or abs(fr['used'] - (cr['c'] or 0)) > 1e-9:
                        unf_mismatch += 1
        mean = lambda x: sum(x) / len(x)
        std = lambda x: (sum((y - mean(x)) ** 2 for y in x) / len(x)) ** 0.5 if len(x) > 1 else 0
        per_cfg[cid] = dict(Q=round(mean(agg['Q']), 4), Q_std=round(std(agg['Q']), 4),
                            C=round(mean(agg['C']), 1), C_std=round(std(agg['C']), 1),
                            L=round(mean(agg['L']), 3),
                            per_seed=dict(Q=[round(x, 4) for x in agg['Q']],
                                          C=[round(x, 1) for x in agg['C']],
                                          L=[round(x, 3) for x in agg['L']]),
                            n=len(uids) * len(fault['seeds']))
        paired[cid] = dict(help=help_n, harm=harm_n,
                           mcnemar_p=round(mcnemar_exact(help_n, harm_n), 5),
                           dQ_total=round(per_cfg[cid]['Q'] - clean_summary[cid]['Q'], 4))
        attributable[cid] = dict(fault_task_help=f_help, fault_task_harm=f_harm)
        if unf_n:
            internal_anchor[cid] = dict(unfaulted_n=unf_n, mismatch=unf_mismatch,
                                        pass_=unf_mismatch == 0)
    out['step2_paired'] = dict(per_config=paired, fault_attributable=attributable,
                               internal_anchor_unfaulted_must_equal_clean=internal_anchor)
    out['fault_per_config'] = per_cfg

    # ---- 3 Z value ----
    dz = {}
    for fam in fault30_protocol.FAMS:
        n = per_cfg.get(f'DYNAMICDAG__{fam}__NONE__FRESH')
        r = per_cfg.get(f'DYNAMICDAG__{fam}__LOCAL_REROUTE__FRESH')
        if not (n and r):
            continue
        dz[fam] = dict(dQ=round(r['Q'] - n['Q'], 4), dC=round(r['C'] - n['C'], 1),
                       dL=round(r['L'] - n['L'], 3),
                       per_seed_dQ=[round(a - b, 4) for a, b in zip(r['per_seed']['Q'],
                                                                    n['per_seed']['Q'])],
                       recovery_induced_pareto_tradeoff=bool(
                           r['Q'] - n['Q'] > 0.005 and (r['C'] - n['C'] > 0 or r['L'] - n['L'] > 0)))
    out['step3_Z_value'] = dict(delta_Z=dz,
                                note='D_Z = LOCAL_REROUTE - NONE on DYNAMICDAG; '
                                     'positive D_Z Q with cost increase = recovery-induced '
                                     'Pareto trade-off inside the cube')

    # ---- 4 Y/X rank shift ----
    fym, fxm = {}, {}
    fym_none = {}
    for cid, v in per_cfg.items():
        topo, fam, z, _ = cid.split('__')
        fym.setdefault(topo, []).append(v['Q'])
        fxm.setdefault(fam, []).append(v['Q'])
        if z == 'NONE':
            fym_none.setdefault(topo, []).append(v['Q'])
    fym_none = {k: round(sum(v) / len(v), 4) for k, v in fym_none.items()}
    fault_Y = {k: round(sum(v) / len(v), 4) for k, v in fym.items()}
    fault_X = {k: round(sum(v) / len(v), 4) for k, v in fxm.items()}
    clean_Y_none = {}
    for cid, v in clean_summary.items():
        if cid.endswith('__NONE__FRESH'):
            clean_Y_none.setdefault(cid.split('__')[0], []).append(v['Q'])
    clean_Y_none = {k: round(sum(v) / len(v), 4) for k, v in clean_Y_none.items()}
    out['step4_rank_shift'] = dict(
        fault_Y_mean_Q=fault_Y, fault_X_mean_Q=fault_X,
        clean_Y_mean_Q=clean_Y, clean_X_mean_Q=clean_X,
        Y_flips=order_flips(clean_Y, fault_Y), X_flips=order_flips(clean_X, fault_X),
        Y_Z_controlled=dict(
            clean_Y_mean_Q_NONE_only=clean_Y_none,
            fault_Y_mean_Q_NONE_only=fym_none,
            Y_flips_under_Z_NONE=order_flips(clean_Y_none, fym_none),
            interpretation='family-mean flip conflates Z (fault mixes NONE+REROUTE, '
                           'clean averages NONE only). Under Z=NONE control the '
                           'SERV-vs-DYNAMICDAG order is stable in both states; the '
                           'flip is recovery-driven value change of DynamicDAG, not '
                           'a pure topology effect'),
        interpretation='family-mean flips = recovery changes DynamicDAG relative '
                       'value (see Y_Z_controlled); no X flips')

    # ---- 5 Pareto ----
    def objs_of(summary, anchor):
        pts = {cid: (v['Q'], v['C'], v['L']) for cid, v in summary.items()}
        pts.update(anchor)
        Cmax = max(v[1] for v in pts.values())
        Lmax = max(v[2] for v in pts.values())
        return {cid: (q, 1 - c / Cmax, 1 - l / Lmax) for cid, (q, c, l) in pts.items()}

    single_f = dict(Q=0.3967, C=802.0, L=0.59)
    anchor_c = {'SINGLE__QUALITY__RETRY__FRESH': (0.55, 612.8, 0.46)}
    anchor_f = {'SINGLE__QUALITY__RETRY__FRESH': (single_f['Q'], single_f['C'], single_f['L'])}
    fault_summary = {cid: dict(Q=v['Q'], C=v['C'], L=v['L'])
                     for cid, v in per_cfg.items()}
    oc, of = objs_of(clean_summary, anchor_c), objs_of(fault_summary, anchor_f)
    front = lambda o: sorted(c for c in o if not any(
        all(x >= y for x, y in zip(o[d], o[c])) and any(x > y for x, y in zip(o[d], o[c]))
        for d in o if d != c))
    fc, ff = front(oc), front(of)
    out['step5_pareto'] = dict(
        P_clean=fc, P_fault=ff,
        gained_under_fault=sorted(set(ff) - set(fc)),
        lost_under_fault=sorted(set(fc) - set(ff)),
        hv_clean=round(hypervolume([oc[c] for c in fc]), 5),
        hv_fault=round(hypervolume([of[c] for c in ff]), 5),
        hv_note='computed with the FIXED sa_pgfs_v1.pareto.hypervolume '
                '(see test_pareto_regression.py)')

    # per-seed fronts -> membership frequency (locked statistical protocol)
    seed_names = sorted(fault['seeds'])
    freq = {cid: 0 for cid in fault_summary}
    per_seed_fronts = {}
    for si, seed in enumerate(seed_names):
        pts = {cid: (v['per_seed']['Q'][si], v['per_seed']['C'][si], v['per_seed']['L'][si])
               for cid, v in per_cfg.items()}
        pts['SINGLE__QUALITY__RETRY__FRESH'] = (single_f['Q'], single_f['C'], single_f['L'])
        Cm = max(p[1] for p in pts.values())
        Lm = max(p[2] for p in pts.values())
        o = {c: (q, 1 - cn / Cm, 1 - l / Lm) for c, (q, cn, l) in pts.items()}
        fs = [c for c in o if not any(
            all(x >= y for x, y in zip(o[d], o[c])) and any(x > y for x, y in zip(o[d], o[c]))
            for d in o if d != c)]
        per_seed_fronts[seed] = sorted(fs)
        for c in fs:
            if c in freq:
                freq[c] += 1
    out['step5_pareto']['front_membership'] = dict(
        per_seed_fronts=per_seed_fronts,
        freq={c: dict(n=v, frac=round(v / len(seed_names), 2),
                      reading='all-seed front' if v == len(seed_names)
                      else ('average-only front' if c in ff else 'single-seed push'))
              for c, v in sorted(freq.items()) if v > 0},
        note='freq(G) = fraction of per-seed fronts containing G; distinguishes '
             'robust vs average-only vs single-seed membership')
    out['weak_anchor_f30_dynamic'] = dict(
        measured=per_cfg.get('DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH', {}).get('Q'),
        legacy=0.4033, tolerance=0.02,
        pass_=abs(per_cfg.get('DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH',
                              {'Q': 0}).get('Q') - 0.4033) <= 0.02)

    (OUT / 'FAULT30_ANALYSIS.json').write_text(json.dumps(out, indent=1))
    print('step1 all_traceable:', prov_ok)
    print('step2 internal anchor:', {k: v['pass_'] for k, v in internal_anchor.items()})
    print('step3 delta_Z:', json.dumps(dz, indent=1))
    print('step4 flips Y/X:', out['step4_rank_shift']['Y_flips'],
          out['step4_rank_shift']['X_flips'])
    print('step5 fronts:', out['step5_pareto']['P_clean'], '->', out['step5_pareto']['P_fault'])


if __name__ == '__main__':
    run()
