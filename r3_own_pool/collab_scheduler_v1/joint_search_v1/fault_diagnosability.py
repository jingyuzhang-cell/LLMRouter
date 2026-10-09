"""Experiment 8: fault type & diagnosability boundary analysis.

Derives from real NB_ROWS.jsonl + the frozen fault draws (zero model requests).

For every faulted (task, node) event under the mechanism protocol:
  exposed        the strategy actually replaced an answer (replaced_calls>0)
  detected       D's recovery machinery fired (logical_calls_D > logical_calls_C
                 OR the faulted node's downstream re-ran)
  recovery_tried D spent extra calls on this task
  repaired       task was wrong for C and right for D (Help, plain Q)
  harmed         task was right for C and wrong for D (Harm, plain Q)
  undetected_error exposed but not detected, final answer wrong
  false_trigger  recovery fired on an UNfaulted task (natural failure path)

Classification boundary: mechanically-detectable (parse/empty/exec/verify
inconsistency) vs runtime-observable is reported as the gap between exposed
and detected.

Run (post real run):  python3 -m ...fault_diagnosability [--stub]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'


def run(stub=False):
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    path = OUT / 'netbenefit_runs' / ('NB_ROWS_STUB.jsonl' if stub else 'NB_ROWS.jsonl')
    rows = {}
    for l in path.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get('status') == 'COMPLETE':
            rows[(r['protocol'], r['arm'], r['state'])] = r
    out = dict(role='Experiment 8: fault diagnosability (derived, zero calls)',
               source='STUB structural proof' if stub else 'NET-BENEFIT real run',
               states={})
    for state in ('fault10', 'fault20', 'fault30'):
        kc, kd = ('mechanism', 'C_static_hetero', state), ('mechanism', 'D_dynamic_local', state)
        if kc not in rows or kd not in rows:
            continue
        C = {t['uid']: t for t in rows[kc]['tasks']}
        D = {t['uid']: t for t in rows[kd]['tasks']}
        faults = freeze['states'][state]['mechanism']['faults']
        cls = Counter()
        per_node = {}
        for uid, (node, _ans) in faults.items():
            c, d = C.get(uid), D.get(uid)
            if c is None or d is None:
                continue
            exposed = d.get('replaced_calls', 0) > 0
            recovery_tried = d['logical_calls'] > c['logical_calls']
            repaired = c['Q'] == 0 and d['Q'] == 1
            harmed = c['Q'] == 1 and d['Q'] == 0
            e = per_node.setdefault(node, Counter())
            cls['exposed'] += int(exposed)
            cls['recovery_tried'] += int(recovery_tried)
            cls['repaired'] += int(repaired)
            cls['harmed'] += int(harmed)
            cls['undetected_error'] += int(exposed and not recovery_tried and d['Q'] == 0)
            for k in ('exposed', 'recovery_tried', 'repaired', 'harmed'):
                e[k] += int(dict(exposed=exposed, recovery_tried=recovery_tried,
                                 repaired=repaired, harmed=harmed)[k])
        naturals = [u for u in C if u not in faults
                    and D[u]['logical_calls'] > C[u]['logical_calls']]
        cls['natural_recovery_triggers'] = len(naturals)
        out['states'][state] = dict(
            n_faulted=len(faults),
            funnel=dict(cls),
            per_fault_node={k: dict(v) for k, v in per_node.items()},
            note='detected = recovery machinery actually fired; repaired is a '
                 'distinct event (detection success != repair success)')
    (OUT / 'FAULT_DIAGNOSABILITY_ANALYSIS.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(out['states'].get('fault30', {}), indent=1)[:500])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stub', action='store_true')
    run(stub=ap.parse_args().stub)
