"""E2: Fault detection accuracy from real fault30 logs (zero LLM calls).

Replays the ACTUAL node outputs from the fault30 executor and runs the
deployable detector on each, comparing against the ground-truth injection
labels. Reports Precision/Recall/F1 by node type, plus false-positive and
false-negative analysis.

Key principle: the `injected` flag from the fault registry is the EVALUATION
label only; the detector sees ONLY the node output text (no injection flag).
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/e2_detection'
F30 = ROOT / 'collab_scheduler_v1/fault30_prep'

from static_dag_v0.multidag_dynamic import parse_facts_safe, value_of, json_value
from static_dag_v0 import tool_aware_v1 as v


def detect_e(answer):
    """Deployable e-node detector: facts empty after parse."""
    f, _ = parse_facts_safe(answer or '')
    return not f['facts']


def detect_r(answer, facts):
    """Deployable r-node detector: expression unparseable or unexecutable."""
    try:
        expr = v.decode(answer or '')
        val, err = value_of(answer or '', facts)
        return bool(err)
    except Exception:
        return True


def detect_v(answer, r_answer, facts):
    """Deployable v-node detector: value None or disagrees with r."""
    vv = json_value(answer or '')
    if vv is None:
        return True
    rv, rerr = value_of(r_answer or '', facts)
    if not rerr and rv is not None:
        try:
            return abs(vv - rv) > max(1e-4, 1e-4 * abs(rv))
        except Exception:
            return True
    return False


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    # Load fault30 execution results with per-node detail
    f30_res = json.loads((F30 / 'FAULT30_RESULTS.json').read_text())
    # Load fault registry (which tasks were faulted, which node)
    policy = json.loads((F30 / 'FAULT30_POLICY.json').read_text())
    # We need the actual node outputs — check if the executor stored them
    # The fault30_run stored per-task {ok, used, lat, faulted, fault_node, keys}
    # The actual answers are in the executor's ledger

    # Use the fault30_run's executor responses if available
    resp_file = F30 / 'RESPONSES.jsonl'
    req_file = F30 / 'REQUESTS.jsonl'
    if not resp_file.exists():
        print('No executor responses found — using aggregated analysis only')
        run_aggregated(f30_res)
        return

    resp = {}
    for l in resp_file.read_text().splitlines():
        r = json.loads(l)
        resp[r['key']] = r['response']

    # Also need the fault30 protocol's fault draw to know which node was faulted
    from collab_scheduler_v1.fault30_protocol import build_faults, map_fault_node, planned_models
    from pathlib import Path as P
    tasks = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json').read_text())['tasks']
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json').read_text())
    SEEDS = (20260923, 20260924, 20260925)

    stats = Counter()
    details = []

    for seed in SEEDS:
        faults = build_faults(seed, 0.3, tasks, pools)
        seed_str = str(seed)
        if seed_str not in f30_res['seeds']:
            continue
        for cid, task_rows in f30_res['seeds'][seed_str].items():
            topo, fam, z, nodes = planned_models(cid)
            for uid, row in task_rows.items():
                faulted = row.get('faulted', False)
                fault_node = row.get('fault_node')
                t = next(tt for tt in tasks if tt['uid'] == uid)
                drawn = faults.get(uid)

                # Get node answers from the executor for this (seed, config, task)
                # The executor stores under keys like f30:{TOPO}:{FAM}:{node}:{uid}
                e_answer = None
                r_answer = None
                v_answer = None
                for key in resp:
                    if uid in key and fam in key:
                        node_part = key.split(':')[3] if len(key.split(':')) > 3 else ''
                        if node_part.startswith('e'):
                            e_answer = resp[key].get('answer')
                        elif node_part.startswith('r') and not node_part.startswith('r1') \
                                and not node_part.startswith('r2'):
                            r_answer = resp[key].get('answer')
                        elif node_part == 'v':
                            v_answer = resp[key].get('answer')

                # Run detectors
                e_detect = detect_e(e_answer) if e_answer else None
                r_detect = None
                if r_answer and e_answer:
                    f, _ = parse_facts_safe(e_answer)
                    r_detect = detect_r(r_answer, f)
                v_detect = None
                if v_answer and r_answer and e_answer:
                    f, _ = parse_facts_safe(e_answer)
                    v_detect = detect_v(v_answer, r_answer, f)

                # Determine ground truth for each node
                gt_e = faulted and fault_node in ('e', 'e1', 'e2')
                gt_r = faulted and fault_node == 'r'
                gt_v = faulted and fault_node == 'v'

                for node_type, detect, gt in [('e', e_detect, gt_e),
                                               ('r', r_detect, gt_r),
                                               ('v', v_detect, gt_v)]:
                    if detect is None:
                        continue
                    stats[(node_type, 'tp' if detect and gt else
                           'fp' if detect and not gt else
                           'fn' if not detect and gt else 'tn')] += 1

    results = dict(
        confusion={f'{nt}_{cat}': stats[(nt, cat)] for nt in ('e', 'r', 'v')
                   for cat in ('tp', 'fp', 'fn', 'tn')},
        metrics={})
    for nt in ('e', 'r', 'v'):
        tp = stats[(nt, 'tp')]
        fp = stats[(nt, 'fp')]
        fn = stats[(nt, 'fn')]
        tn = stats[(nt, 'tn')]
        prec = tp / max(1, tp + fp)
        rec = tp / max(1, tp + fn)
        f1 = 2 * prec * rec / max(1e-9, prec + rec)
        results['metrics'][nt] = dict(
            precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4),
            tp=tp, fp=fp, fn=fn, tn=tn)

    (OUT / 'E2_DETECTION.json').write_text(json.dumps(results, indent=1))
    print(json.dumps(results['metrics'], indent=1))


def run_aggregated(f30_res):
    """Fallback: aggregated analysis using fault_node field only."""
    stats = Counter()
    for seed_str, configs in f30_res['seeds'].items():
        for cid, rows in configs.items():
            for uid, row in rows.items():
                nt = row.get('fault_node', 'none')
                stats[(nt, 'faulted' if row['faulted'] else 'clean')] += 1
    results = dict(aggregated=Counter_dict(stats))
    (OUT / 'E2_DETECTION_AGGREGATED.json').write_text(json.dumps(results, indent=1))
    print(json.dumps(dict(message='aggregated only', counts=Counter_dict(stats)), indent=1))


def Counter_dict(c):
    return {f'{k[0]}_{k[1]}': v for k, v in c.items()}


if __name__ == '__main__':
    run()
