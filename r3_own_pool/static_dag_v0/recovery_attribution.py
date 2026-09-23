"""Recovery Attribution Analysis (zero model calls).

Question: WHERE does Dynamic's robustness come from — which failure types are
detected, which are repaired, which are not?

Attribution sets:
  A. Clean scenario (corrected RD arm): the 78 initially-wrong tasks, primary
     failure type by topological order of the initial pass:
       evidence (parse/empty)  -> e1/e2 facts unparseable or empty
       evidence (wrong values) -> e outputs well-formed but gold-derivation
                                  literals not all present (operand-recall gap)
       execution (r)           -> r expression unparseable/unexecutable
       reasoning (r)           -> r executes but computes a wrong value
       verification (v)        -> r fine (value on facts == gold) but v wrong
     For each type: n, node-level detection rate (an RD event fired on the
     failing node), task-level detection (any event), recovery success
     (task ok in corrected RD), tokens on that task set.
  B. Fault scenarios (10/20/30%): injected faults by node type; recovery
     success per type (evidence=e1/e2 injections, execution=r injections
     (unexecutable outputs), verification=v injections (prose outputs)).
  C. Verifier set: disagreement-signal tasks (reasoning errors): detection
     82% precision, repair 7/34 (from DV_RESULT).

Writes adaptive_benchmark/RECOVERY_ATTRIBUTION.json + .md (paper Table 3).
"""
import json
import time

from .multidag_dynamic import OUT, close, parse_facts_safe, value_of
from .multidag_fullgraph import FG
from .multidag_ablation import ABL
from .benchmark_run import BENCH, RATES
from .tatqa_benchmark_build import literals
from .verifier_run import DV


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    n = len(tasks)
    uids = [t['uid'] for t in tasks]
    resp = {}
    for f in (OUT, ABL, FG):
        for l in (f / 'RESPONSES.jsonl').read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r
    corrected = json.loads((OUT.parent / 'corrected_replay' / 'CORRECTED_ARMS.json').read_text())
    rd = corrected['arms']['rd']

    # ---- A. clean attribution ----
    rows = {}
    init_v_ok = {}
    for t in tasks:
        u = t['uid']
        f1, _ = parse_facts_safe(resp[f'e1:{u}']['response']['answer'])
        f2, _ = parse_facts_safe(resp[f'e2:{u}']['response']['answer'])
        combined = f1['facts'] + f2['facts']
        gold_lits = [x for x in literals(t['derivation']) if x not in (0.0, 1.0, 100.0)]
        recall_ok = all(any(abs(f['value'] - g) <= 1e-6 for f in combined) for g in gold_lits)
        rval, rerr = value_of(resp[f'r:{u}']['response']['answer'], {'facts': combined})
        from .verifier_subset_analyze import n_ops  # noqa
        from . import tool_aware_v1 as v
        vv = None
        try:
            vv = float(json.loads(resp[f'v:{u}']['response']['answer'].strip().strip('`'))['value'])
        except Exception:
            try:
                vv = float(v.decode(resp[f'v:{u}']['response']['answer'])['value'])
            except Exception:
                vv = None
        init_v_ok[u] = close(vv, t['answer'])
        if not f1['facts'] or not f2['facts']:
            ftype, fnode = 'evidence (parse/empty)', 'e'
        elif not recall_ok:
            ftype, fnode = 'evidence (wrong values)', 'e'
        elif rerr:
            ftype, fnode = 'execution (r)', 'r'
        elif not close(rval, t['answer']):
            ftype, fnode = 'reasoning (r)', 'r'
        elif not init_v_ok[u]:
            ftype, fnode = 'verification (v)', 'v'
        else:
            ftype, fnode = None, None
        if ftype and not init_v_ok[u]:
            rows.setdefault(ftype, []).append(dict(uid=u, node=fnode))
    n_wrong = sum(1 for u in uids if not init_v_ok[u])
    attribution = {}
    for ftype, items in rows.items():
        us = [x['uid'] for x in items]
        node = items[0]['node']
        node_detect = 0
        any_detect = 0
        recovered = 0
        for u in us:
            evs = rd[u]['events']
            if any(e.get('node', '').startswith(node) if node == 'e' else e.get('node') == node for e in evs):
                node_detect += 1
            if evs:
                any_detect += 1
            if rd[u]['ok']:
                recovered += 1
        attribution[ftype] = dict(n=len(us), node_detection=round(node_detect / len(us), 4),
                                   any_detection=round(any_detect / len(us), 4),
                                   recovery_success=round(recovered / len(us), 4),
                                   recovered=recovered)
    # ---- B. fault attribution ----
    fault_attr = {}
    for rate in RATES:
        fr = json.loads((BENCH / f'fault_p{int(rate * 100)}' / 'FAULT_RESULT.json').read_text())
        fset = fr['faulted']
        by = {}
        for u, node in fset.items():
            key = {'e1': 'evidence (injected e)', 'e2': 'evidence (injected e)',
                   'r': 'execution (injected r)', 'v': 'verification (injected v)'}[node]
            by.setdefault(key, []).append(u)
        fault_attr[rate] = {k: dict(n=len(us),
                                    recovery_success=round(sum(1 for u in us if fr['dynamic'][u]['ok']) / len(us), 4),
                                    static_survival=round(sum(1 for u in us if fr['static'][u]['ok']) / len(us), 4))
                            for k, us in by.items()}
    # ---- C. verifier set ----
    dv = json.loads((DV / 'DV_RESULT.json').read_text())
    dv_stat = dv['signal_stats']
    dv_res = dv['dv']
    fired = [u for u, r in dv_res.items() if r['signal'] == 'disagreement']
    verifier = dict(signal_fired=dv_stat['fired'],
                    true_reasoning_errors=dv_stat['new_fired'],
                    detection_precision=round(dv_stat['new_fired'] / dv_stat['fired'], 4),
                    repaired=sum(1 for u in fired if dv_res[u]['ok']),
                    repair_rate=round(sum(1 for u in fired if dv_res[u]['ok']) / dv_stat['fired'], 4))

    rep = dict(generated_unix=time.time(), n_initially_wrong=n_wrong,
               A_clean_attribution=attribution,
               B_fault_attribution=fault_attr,
               C_verifier_set=verifier,
               note='Success = Detection x Repairability: rows quantify each factor by failure type')
    (BENCH / 'RECOVERY_ATTRIBUTION.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))

    lines = ['# Recovery Attribution Analysis (paper Table 3)', '',
             'Success = Detection x Repairability x Execution — each row quantifies the factors by failure type.', '',
             '## A. Clean scenario: initially-wrong tasks under Dynamic (corrected RD arm)', '',
             f'N = {n_wrong} initially-wrong tasks (fixed parser); recovery = task ends correct under RD.', '',
             '| Failure type (primary, topological) | n | node detection | any detection | recovery success |',
             '|---|---:|---:|---:|---:|']
    order = ['evidence (parse/empty)', 'evidence (wrong values)', 'execution (r)', 'reasoning (r)', 'verification (v)']
    for k in order:
        if k in attribution:
            a = attribution[k]
            lines.append(f"| {k} | {a['n']} | {a['node_detection']:.0%} | {a['any_detection']:.0%} | "
                         f"{a['recovery_success']:.0%} ({a['recovered']}/{a['n']}) |")
    lines += ['', '## B. Fault scenarios: injected faults, Dynamic recovery vs Static survival', '']
    for rate in RATES:
        lines.append(f'### fault {int(rate * 100)}%')
        lines.append('| Faulted node type | n | Dynamic recovery | Static survival |')
        lines.append('|---|---:|---:|---:|')
        for k, a in fault_attr[rate].items():
            lines.append(f"| {k} | {a['n']} | {a['recovery_success']:.0%} | {a['static_survival']:.0%} |")
        lines.append('')
    lines += ['## C. Verifier set: reasoning errors made detectable', '',
              f"signal fired {verifier['signal_fired']} times; true reasoning errors {verifier['true_reasoning_errors']} "
              f"(detection precision {verifier['detection_precision']:.0%}); repaired {verifier['repaired']} "
              f"(repair rate {verifier['repair_rate']:.0%}).", '',
              'Reading: execution-level failures are detected and partly repaired; evidence-value and reasoning '
              'failures are detected only partially (verifier adds 82%-precision reasoning detection) but their '
              'repair rate is the bottleneck — the ceiling is model capability on decomposed subtasks, not '
              'diagnosability.']
    (BENCH / 'RECOVERY_ATTRIBUTION.md').write_text('\n'.join(lines))
    print('\n'.join(lines))


if __name__ == '__main__':
    run()
