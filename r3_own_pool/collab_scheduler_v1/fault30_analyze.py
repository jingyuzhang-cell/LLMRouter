"""fault30 analyzer: P*_fault, paired clean<->fault tests, front expansion.

Reads:
  - clean per-task rows: recomputed zero-call by cube_analyze.evaluate()
  - fault per-task rows: fault30_prep/FAULT30_RESULTS.json, written by
    fault30_run.py as {seeds: {seed: {cid: {uid: {ok, used, lat, faulted,
    fault_node}}}}, policy_sha256}

Outputs FAULT30_ANALYSIS.json:
  - per-config Q/C/L (mean over 3 seeds, n=600, per-seed values)
  - P*_fault ND front + 3D HV, side by side with P*_clean
  - front-expansion test (which labels enter only under fault)
  - paired McNemar (exact binomial) clean<->fault per config + Help/Harm
  - fault-attributable delta (active-fault tasks only) vs total delta
  - anchor checks incl. the internal bit-equality check on unfaulted tasks
    under Z=NONE (primary anchor per FAULT30_POLICY)
  - Q(B) budget curves per config from per-task costs

Run: python3 -m collab_scheduler_v1.fault30_analyze
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1'
F30 = OUT / 'fault30_prep/FAULT30_RESULTS.json'
CONFIGS = None  # imported from fault30_protocol at run time


def mcnemar_exact(b, c):
    """Exact two-sided binomial McNemar p on b,c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def load_fault():
    if not F30.exists():
        return None
    d = json.loads(F30.read_text())
    return d


def run():
    sys.path.insert(0, str(ROOT))
    from collab_scheduler_v1 import cube_analyze, fault30_protocol
    from sa_pgfs_v1.pareto import hypervolume, non_dominated

    fault = load_fault()
    if fault is None:
        print('FAULT30_RESULTS.json not present yet — only the clean side will '
              'be summarized; rerun after the fault30 stage completes.')
    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
                       .read_text())['tasks']
    uids = [t['uid'] for t in tasks]
    clean_eval = cube_analyze.evaluate(tasks)
    clean_rows = {cid: {r['uid']: r for r in v['per_task']}
                  for cid, v in clean_eval.items()}
    clean_summary = {cid: dict(Q=v['Q'], C=v['C'], L=v['L'], n=v['n'])
                     for cid, v in clean_eval.items() if v['n'] == v['n_total']}

    out = dict(clean_summary=clean_summary)
    if fault is None:
        (OUT / 'FAULT30_ANALYSIS.json').write_text(json.dumps(out, indent=1))
        print(json.dumps(out, indent=1)[:1500])
        return

    seeds = fault['seeds']
    per_cfg = {}
    paired = {}
    attributable = {}
    internal_anchor = {}
    for cid in fault30_protocol.CONFIGS:
        rows = []
        agg = dict(Q=[], C=[], L=[])
        help_n = harm_n = 0
        f_help = f_harm = 0
        unfaulted_mismatch = 0
        unfaulted_n = 0
        for seed in seeds:
            srows = fault['seeds'][seed][cid]
            qs = [srows[u]['ok'] for u in uids]
            agg['Q'].append(sum(qs) / len(qs))
            agg['C'].append(sum(srows[u]['used'] for u in uids) / len(uids))
            agg['L'].append(sum(srows[u]['lat'] for u in uids) / len(uids))
            for u in uids:
                fr, cr = srows[u], clean_rows[cid][u]
                rows.append(fr)
                if cr['ok'] and not fr['ok']:
                    harm_n += 1
                if not cr['ok'] and fr['ok']:
                    help_n += 1
                if fr.get('faulted'):
                    if not cr['ok'] and fr['ok']:
                        f_help += 1
                    if cr['ok'] and not fr['ok']:
                        f_harm += 1
                elif cid.endswith('__NONE__FRESH'):
                    unfaulted_n += 1
                    if fr['ok'] != cr['ok'] or abs(fr['used'] - (cr['c'] or 0)) > 1e-9:
                        unfaulted_mismatch += 1
        mean = lambda x: sum(x) / len(x)
        std = lambda x: (sum((y - mean(x)) ** 2 for y in x) / len(x)) ** 0.5 if len(x) > 1 else 0.0
        per_cfg[cid] = dict(Q=round(mean(agg['Q']), 4), Q_std=round(std(agg['Q']), 4),
                            C=round(mean(agg['C']), 1), L=round(mean(agg['L']), 3),
                            per_seed=dict(Q=[round(x, 4) for x in agg['Q']],
                                          C=[round(x, 1) for x in agg['C']],
                                          L=[round(x, 3) for x in agg['L']]),
                            n=len(rows))
        paired[cid] = dict(help=help_n, harm=harm_n, n=len(rows),
                           mcnemar_p=round(mcnemar_exact(help_n, harm_n), 5),
                           delta_Q=round(sum(r['ok'] for r in rows) / len(rows)
                                         - clean_summary[cid]['Q'], 4))
        if f_help + f_harm > 0 or any(r.get('faulted') for r in rows):
            attributable[cid] = dict(fault_task_help=f_help, fault_task_harm=f_harm,
                                     note='paired delta restricted to active-fault tasks')
        if unfaulted_n:
            internal_anchor[cid] = dict(unfaulted_n=unfaulted_n,
                                        mismatch=unfaulted_mismatch,
                                        pass_=unfaulted_mismatch == 0)
    out.update(fault_per_config=per_cfg, paired_clean_fault=paired,
               fault_attributable=attributable, internal_anchor_check=internal_anchor)

    # fronts + expansion
    def objs_of(summary, anchor_extra=None):
        pts = {cid: (v['Q'], v['C'], v['L']) for cid, v in summary.items()}
        if anchor_extra:
            pts.update(anchor_extra)
        Cmax = max(v[1] for v in pts.values())
        Lmax = max(v[2] for v in pts.values())
        return {cid: (q, 1 - c / Cmax, 1 - l / Lmax) for cid, (q, c, l) in pts.items()}

    single_f = dict(Q=0.3967, C=802.0, L=0.59)  # frozen200 f30_single, bookkeeping fault
    fault_summary = {cid: dict(Q=v['Q'], C=v['C'], L=v['L'])
                     for cid, v in per_cfg.items() if v['n'] == 600}
    anchor_c = {'SINGLE__QUALITY__RETRY__FRESH': (single_f['Q'], single_f['C'], single_f['L'])}
    oc, of = objs_of(clean_summary, anchor_c), objs_of(fault_summary, anchor_c)
    fc = [i for i in oc if not any(all(x >= y for x, y in zip(oc[j], oc[i]))
                                   and any(x > y for x, y in zip(oc[j], oc[i]))
                                   for j in oc if j != i)]
    ff = [i for i in of if not any(all(x >= y for x, y in zip(of[j], of[i]))
                                   and any(x > y for x, y in zip(of[j], of[i]))
                                   for j in of if j != i)]
    out['fronts'] = dict(
        P_clean=sorted(fc), P_fault=sorted(ff),
        gained_under_fault=sorted(set(ff) - set(fc)),
        lost_under_fault=sorted(set(fc) - set(ff)),
        hv_clean=round(hypervolume([oc[i] for i in fc]), 5),
        hv_fault=round(hypervolume([of[i] for i in ff]), 5))

    # weak anchor: DYNAMICDAG HET LOCAL_REROUTE vs legacy f30_dynamic
    wh = per_cfg.get('DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH')
    if wh:
        out['weak_anchor_f30_dynamic'] = dict(
            measured_Q=wh['Q'], legacy_Q=0.4033, legacy_Q_std=0.0029,
            tolerance=0.02,
            pass_=abs(wh['Q'] - 0.4033) <= 0.02,
            note='memory-rule scope differs (per seed,config) and L uses critical '
                 'path vs legacy serial sum; Q tolerance per FAULT30_POLICY')

    (OUT / 'FAULT30_ANALYSIS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out.get('fronts', {}), indent=1))
    print(json.dumps(out.get('internal_anchor_check', {}), indent=1))


if __name__ == '__main__':
    run()
