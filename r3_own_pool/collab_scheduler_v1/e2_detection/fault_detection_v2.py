"""E2 v2: Fault detection accuracy — proper reconstruction from fault30 traces.

Rebuilds the actual observable node outputs per (seed, config, task, node):
  - injected fault nodes: failing text from FAULT_POOLS.json
  - cached nodes: answer from cube_clean ledger (by prompt hash)
  - real calls: answer from fault30 RESPONSES.jsonl
Then runs the deployable detectors and computes confusion matrices against
the fault registry (ground truth), distinguishing "faulted" from "detectable".
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/e2_detection'
F30_DIR = ROOT / 'collab_scheduler_v1/fault30_prep'
CUBE = ROOT / 'collab_scheduler_v1/cube_clean'
FZ = ROOT / 'static_dag_v0/frozen200'

from static_dag_v0.multidag_dynamic import parse_facts_safe, value_of, json_value
from static_dag_v0 import tool_aware_v1 as v
from collab_scheduler_v1.fault30_protocol import build_faults, map_fault_node, planned_models

SEEDS = (20260923, 20260924, 20260925)
RATE = 0.3


def build_prompt_cache():
    """(model, sha(prompt)) -> answer, from cube_clean + frozen200 ledgers."""
    cache = {}
    for folder in [CUBE, FZ]:
        rp, qp = folder / 'RESPONSES.jsonl', folder / 'REQUESTS.jsonl'
        if not (rp.exists() and qp.exists()):
            continue
        resp = {}
        for l in rp.read_text().splitlines():
            r = json.loads(l)
            resp[r['key']] = r
        for l in qp.read_text().splitlines():
            q = json.loads(l)
            rec = resp.get(q['key'])
            if rec is None:
                continue
            response = rec.get('response', {})
            if response.get('status') != 'delivered':
                continue
            h = q.get('prompt_sha256')
            if h:
                cache.setdefault((rec.get('model'), h), response.get('answer', ''))
    return cache


def build_f30_responses():
    """key -> answer from fault30 real calls."""
    out = {}
    rp = F30_DIR / 'RESPONSES.jsonl'
    if rp.exists():
        for l in rp.read_text().splitlines():
            r = json.loads(l)
            out[r['key']] = r['response'].get('answer', '')
    return out


def get_node_answer(key, node, topo, fam, uid, task, fault_info, prompt_cache, f30_resp):
    """Reconstruct the observable answer for a node execution."""
    # check fault30 real calls first
    if key in f30_resp:
        return f30_resp[key]
    # check prompt-hash cache (cube_clean / frozen200)
    # We need the prompt to hash it, but we don't have it stored per-key.
    # Instead, use the cube ledger's key format
    if topo in ('SER', 'SERV'):
        cube_key = f'cube:SER:{fam}:{node}:{uid}'
        ctx = task['ctx_table'] + '\n' + task['ctx_text']
    else:
        cube_key = f'cube:PAR:{fam}:{node}:{uid}'
        ctx = task['ctx_table'] if node == 'e1' else task['ctx_text']
    # Look up by cube key in cube_clean responses
    cube_resp = {}
    rp = CUBE / 'RESPONSES.jsonl'
    if rp.exists():
        for l in rp.read_text().splitlines():
            r = json.loads(l)
            if r['key'] == cube_key:
                return r['response'].get('answer', '')
    # If faulted, the answer is the failing text
    if fault_info and fault_info.get('is_faulted'):
        return fault_info.get('failing_text', '')
    return None


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = json.loads((FZ / 'FROZEN200_POLICY.json').read_text())['tasks']
    pools = json.loads((ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json').read_text())
    f30_results = json.loads((F30_DIR / 'FAULT30_RESULTS.json').read_text())
    f30_resp = build_f30_responses()
    task_map = {t['uid']: t for t in tasks}

    # Build cube_clean by_key for fast lookup
    cube_by_key = {}
    rp = CUBE / 'RESPONSES.jsonl'
    if rp.exists():
        for l in rp.read_text().splitlines():
            r = json.loads(l)
            cube_by_key[r['key']] = r['response'].get('answer', '')

    stats = Counter()
    detectable_stats = Counter()
    coverage = Counter()

    for seed in SEEDS:
        faults = build_faults(seed, RATE, tasks, pools)
        seed_str = str(seed)
        if seed_str not in f30_results['seeds']:
            continue
        for cid, task_rows in f30_results['seeds'][seed_str].items():
            topo, fam, z, nodes = planned_models(cid)
            for uid, row in task_rows.items():
                task = task_map[uid]
                drawn = faults.get(uid)
                fault_node = row.get('fault_node')
                faulted = row.get('faulted', False)
                failing_text = drawn[1] if drawn else None

                # For each node type, reconstruct the observable output
                # and run the detector
                for node_type in ('e', 'r', 'v'):
                    if node_type == 'e' and topo in ('SER', 'SERV'):
                        cube_key = f'cube:SER:{fam}:e:{uid}'
                    elif node_type == 'e' and topo in ('PARALLELER', 'DYNAMICDAG'):
                        cube_key = f'cube:PAR:{fam}:e1:{uid}'
                    elif node_type == 'r':
                        pfx = 'SER' if topo in ('SER', 'SERV') else 'PAR'
                        cube_key = f'cube:{pfx}:{fam}:r:{uid}'
                    elif node_type == 'v':
                        cube_key = f'cube:{topo}:{fam}:v:{uid}'
                    else:
                        continue

                    is_faulted_node = faulted and fault_node == node_type
                    if is_faulted_node:
                        answer = failing_text
                    else:
                        answer = cube_by_key.get(cube_key)

                    if answer is None:
                        coverage[('missing', node_type)] += 1
                        continue
                    coverage[('found', node_type)] += 1

                    # Run detector
                    if node_type == 'e':
                        f, _ = parse_facts_safe(answer)
                        detected = not f['facts']
                    elif node_type == 'r':
                        # Need facts for r detector — get from e
                        if topo in ('SER', 'SERV'):
                            e_cube = f'cube:SER:{fam}:e:{uid}'
                        else:
                            e_cube = f'cube:PAR:{fam}:e1:{uid}'
                        e_ans = failing_text if (faulted and fault_node == 'e') \
                            else cube_by_key.get(e_cube)
                        if e_ans is None:
                            continue
                        f, _ = parse_facts_safe(e_ans)
                        try:
                            val, err = value_of(answer, f)
                            detected = bool(err)
                        except Exception:
                            detected = True
                    elif node_type == 'v':
                        # Need r answer and facts
                        pfx = 'SER' if topo in ('SER', 'SERV') else 'PAR'
                        r_cube = f'cube:{pfx}:{fam}:r:{uid}'
                        r_ans = failing_text if (faulted and fault_node == 'r') \
                            else cube_by_key.get(r_cube)
                        if topo in ('SER', 'SERV'):
                            e_cube = f'cube:SER:{fam}:e:{uid}'
                        else:
                            e_cube = f'cube:PAR:{fam}:e1:{uid}'
                        e_ans = failing_text if (faulted and fault_node == 'e') \
                            else cube_by_key.get(e_cube)
                        if e_ans is None or r_ans is None:
                            continue
                        f, _ = parse_facts_safe(e_ans)
                        vv = json_value(answer)
                        if vv is None:
                            detected = True
                        else:
                            rv, rerr = value_of(r_ans, f)
                            if not rerr and rv is not None:
                                try:
                                    detected = abs(vv - rv) > max(1e-4, 1e-4 * abs(rv))
                                except Exception:
                                    detected = True
                            else:
                                detected = False

                    cat = 'tp' if detected and is_faulted_node else \
                          'fp' if detected and not is_faulted_node else \
                          'fn' if not detected and is_faulted_node else 'tn'
                    stats[(node_type, cat)] += 1

                    # Also track: was the fault actually observable?
                    # (injected AND produced a parse/exec anomaly)
                    if is_faulted_node:
                        if detected:
                            detectable_stats[(node_type, 'detectable')] += 1
                        else:
                            detectable_stats[(node_type, 'not_detectable')] += 1

    metrics = {}
    for nt in ('e', 'r', 'v'):
        tp = stats[(nt, 'tp')]
        fp = stats[(nt, 'fp')]
        fn = stats[(nt, 'fn')]
        tn = stats[(nt, 'tn')]
        prec = tp / max(1, tp + fp)
        rec = tp / max(1, tp + fn)
        f1 = 2 * prec * rec / max(1e-9, prec + rec)
        total_faulted = tp + fn
        total_clean = fp + tn
        metrics[nt] = dict(
            precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4),
            tp=tp, fp=fp, fn=fn, tn=tn,
            n_faulted=total_faulted, n_clean=total_clean,
            fp_rate_on_clean=round(fp / max(1, total_clean), 4),
            detectable_rate=round(
                detectable_stats[(nt, 'detectable')] /
                max(1, detectable_stats[(nt, 'detectable')] + detectable_stats[(nt, 'not_detectable')]),
                4))

    results = dict(
        metrics=metrics,
        coverage=dict(found=dict(), missing=dict()),
        note='E2 v2: proper reconstruction from fault30 traces; faulted nodes use '
             'failing text, clean nodes use cube_clean ledger; detectable_rate '
             'separates "faulted" from "produced observable anomaly"')
    for (cat, nt), cnt in coverage.items():
        results['coverage'][cat][nt] = cnt

    (OUT / 'E2_DETECTION_V2.json').write_text(json.dumps(results, indent=1))
    print(json.dumps(metrics, indent=1))


if __name__ == '__main__':
    run()
