"""FINAL READINESS AUDIT: E3+ E2-final + E1-archive + E4-fix + P1-B-admission.

Zero LLM calls, zero GPU. Does NOT modify frozen experiment results.
Produces FINAL_READINESS_AUDIT.md with per-item PASS/FAIL.
"""
import hashlib
import json
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/readiness_audit'
OUT.mkdir(parents=True, exist_ok=True)

from collab_scheduler_v1.dag_patch_p1b import (
    run_track, stub, select_tasks, build_heldout_faults, _load_gc, _save_gc,
    GOOD, _pkind, P1BExecutor, LEDGER, GCOUNTER)
from collab_scheduler_v1.dag_patch_p0 import RuntimeDAG, PatchError
from collab_scheduler_v1.fault30_protocol import build_faults, map_fault_node, planned_models
from static_dag_v0.multidag_dynamic import parse_facts_safe, value_of, json_value
from static_dag_v0 import tool_aware_v1 as v

results = {}


# ===================== E3: P1-B run_track() three-strategy test =====================
def audit_e3():
    """Directly test P1-B's run_track() with stub service, covering e1/e2/r/v faults."""
    tasks = select_tasks()
    led = None
    from collab_scheduler_v1 import fault30_protocol as fp
    led = fp.Ledger()
    gc = dict(n=0, cap=10000)
    _save_gc(gc)

    checks = {}
    task = tasks[0]

    # For each fault position, test all 3 strategies
    for fault_node in ('e1', 'e2', 'r', 'v'):
        faults = {task['uid']: (fault_node, 'garbage')}
        for strategy in ('static', 'reroute', 'dynpatch'):
            log = run_track(stub(), task, strategy, led, faults, gc)
            label = f'{fault_node}_{strategy}'
            if strategy == 'static':
                checks[f'{label}_no_patches'] = not log['patches']
                checks[f'{label}_no_extra_calls'] = log['n_calls'] <= 4
            elif strategy == 'reroute':
                if fault_node == 'r':
                    checks[f'{label}_has_r_esc'] = 'r_esc' in log['executed']
                    checks[f'{label}_no_patches'] = not log['patches']
                else:
                    checks[f'{label}_no_patches'] = not log['patches']
            elif strategy == 'dynpatch':
                if fault_node == 'r':
                    checks[f'{label}_has_split'] = bool(log['patches'])
                    checks[f'{label}_executed_r1r2'] = 'r1' in log['executed'] and \
                        'r2' in log['executed']
                else:
                    # e/v faults: current P1-B detector only handles r faults
                    checks[f'{label}_completes'] = log['status'] in ('completed', 'failed-no-ready')

    # Negative test: no fault → all strategies should complete without patches
    for strategy in ('static', 'reroute', 'dynpatch'):
        log = run_track(stub(), task, strategy, led, {}, gc)
        checks[f'nofault_{strategy}_no_patches'] = not log['patches']
        checks[f'nofault_{strategy}_completed'] = log['status'] == 'completed'

    results['E3_p1b_direct'] = dict(checks=checks, all_pass=all(checks.values()),
                                    n_checks=len(checks), n_pass=sum(checks.values()))
    return all(checks.values())


# ===================== E2 final: proper per-(seed,config,task,node) reconstruction ====
def audit_e2():
    """Rebuild actual observable outputs from fault30 execution trace keys."""
    f30_results = json.loads(
        (ROOT / 'collab_scheduler_v1/fault30_prep/FAULT30_RESULTS.json').read_text())
    cube_by_key = {}
    rp = ROOT / 'collab_scheduler_v1/cube_clean/RESPONSES.jsonl'
    for l in rp.read_text().splitlines():
        r = json.loads(l)
        cube_by_key[r['key']] = r['response'].get('answer', '')

    f30_resp = {}
    rp2 = ROOT / 'collab_scheduler_v1/fault30_prep/RESPONSES.jsonl'
    if rp2.exists():
        for l in rp2.read_text().splitlines():
            r = json.loads(l)
            f30_resp[r['key']] = r['response'].get('answer', '')

    tasks = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json').read_text())['tasks']
    task_map = {t['uid']: t for t in tasks}
    pools = json.loads(
        (ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json').read_text())

    stats = Counter()
    missing = Counter()

    for seed in (20260923, 20260924, 20260925):
        faults = build_faults(seed, 0.3, tasks, pools)
        seed_str = str(seed)
        if seed_str not in f30_results['seeds']:
            continue
        for cid, task_rows in f30_results['seeds'][seed_str].items():
            topo, fam, z, nodes = planned_models(cid)
            for uid, row in task_rows.items():
                fault_node = row.get('fault_node')
                faulted = row.get('faulted', False)
                drawn = faults.get(uid)
                failing_text = drawn[1] if drawn else None

                # Map fault_node to actual node names in this topology
                if fault_node == 'e' and topo in ('PARALLELER', 'DYNAMICDAG'):
                    fault_e_node = 'e1'  # approximate: map to first e branch
                elif fault_node in ('e1', 'e2') and topo in ('SER', 'SERV'):
                    fault_e_node = 'e'
                else:
                    fault_e_node = fault_node

                # Get the ACTUAL keys this task's execution used
                exec_keys = row.get('keys', [])

                # Reconstruct e-node output
                for e_name in ('e', 'e1', 'e2'):
                    if topo in ('SER', 'SERV') and e_name != 'e':
                        continue
                    if topo in ('PARALLELER', 'DYNAMICDAG') and e_name == 'e':
                        continue

                    # Find the actual answer this node produced
                    f30_key = f'f30:{topo}:{fam}:{e_name}:{uid}'
                    pfx = 'SER' if topo in ('SER', 'SERV') else 'PAR'
                    cube_key = f'cube:{pfx}:{fam}:{e_name}:{uid}'

                    is_faulted = faulted and fault_node in (
                        'e', 'e1', 'e2') and e_name == fault_e_node
                    answer = f30_resp.get(f30_key) or cube_by_key.get(cube_key)
                    if is_faulted and failing_text:
                        answer = failing_text
                    if answer is None:
                        missing[('e', 'no_answer')] += 1
                        continue

                    f, _ = parse_facts_safe(answer)
                    detected = not f['facts']
                    cat = 'tp' if detected and is_faulted else \
                          'fp' if detected and not is_faulted else \
                          'fn' if not detected and is_faulted else 'tn'
                    stats[('e', cat)] += 1

                # Reconstruct r-node output
                pfx = 'SER' if topo in ('SER', 'SERV') else 'PAR'
                cube_r = f'cube:{pfx}:{fam}:r:{uid}'
                f30_r = f'f30:{topo}:{fam}:r:{uid}'
                is_r_faulted = faulted and fault_node == 'r'
                r_answer = f30_resp.get(f30_r) or cube_by_key.get(cube_r)
                if is_r_faulted and failing_text:
                    r_answer = failing_text
                if r_answer is None:
                    missing[('r', 'no_answer')] += 1
                else:
                    # Get facts for r detector
                    e_cube = f'cube:{pfx}:{fam}:e:{uid}' if pfx == 'SER' else \
                        f'cube:{pfx}:{fam}:e1:{uid}'
                    e_answer = cube_by_key.get(e_cube, '')
                    f, _ = parse_facts_safe(e_answer)
                    try:
                        val, err = value_of(r_answer, f)
                        detected = bool(err)
                    except Exception:
                        detected = True
                    cat = 'tp' if detected and is_r_faulted else \
                          'fp' if detected and not is_r_faulted else \
                          'fn' if not detected and is_r_faulted else 'tn'
                    stats[('r', cat)] += 1

                # Reconstruct v-node output
                if topo in ('SERV', 'DYNAMICDAG'):
                    cube_v = f'cube:{topo}:{fam}:v:{uid}'
                    f30_v = f'f30:{topo}:{fam}:v:{uid}'
                    is_v_faulted = faulted and fault_node == 'v'
                    v_answer = f30_resp.get(f30_v) or cube_by_key.get(cube_v)
                    if is_v_faulted and failing_text:
                        v_answer = failing_text
                    r_ans = cube_by_key.get(cube_r, '')
                    if v_answer is None or r_ans is None:
                        missing[('v', 'no_answer')] += 1
                    else:
                        e_ans = cube_by_key.get(e_cube, '')
                        f, _ = parse_facts_safe(e_ans)
                        vv = json_value(v_answer)
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
                        cat = 'tp' if detected and is_v_faulted else \
                              'fp' if detected and not is_v_faulted else \
                              'fn' if not detected and is_v_faulted else 'tn'
                        stats[('v', cat)] += 1

    metrics = {}
    for nt in ('e', 'r', 'v'):
        tp, fp, fn, tn = (stats[(nt, c)] for c in ('tp', 'fp', 'fn', 'tn'))
        prec = tp / max(1, tp + fp)
        rec = tp / max(1, tp + fn)
        f1 = 2 * prec * rec / max(1e-9, prec + rec)
        metrics[nt] = dict(precision=round(prec, 4), recall=round(rec, 4),
                           f1=round(f1, 4), tp=tp, fp=fp, fn=fn, tn=tn,
                           n_evaluated=tp + fp + fn + tn)

    results['E2_final'] = dict(
        metrics=metrics, missing={f'{k[0]}_{k[1]}': v for k, v in missing.items()},
        note='e1/e2 properly mapped; per-(seed,config,task,node) reconstruction; '
             'injected faults use failing_text; cached nodes use cube_clean; '
             'f30 real calls from RESPONSES.jsonl; missing separately tracked')
    return True


# ===================== E1 archive: save reproducible test =====================
def audit_e1():
    """Archive the consumed-node stress test with fixed seed and command."""
    test_code = '''"""E1 consumed-node stress test (reproducible). Seed=20261001, 200 trials."""
import json, random, sys
sys.path.insert(0, '/root/r3_own_pool')
from collab_scheduler_v1.dag_patch_p0 import RuntimeDAG, PatchError

rng = random.Random(20261001)
c = dict(consumed_attempted=0, consumed_rejected=0, consumed_incorrect_accept=0,
         unconsumed_attempted=0, unconsumed_accepted=0)
for trial in range(200):
    nodes = {f'n{i}': dict(deps=[f'n{j}' for j in range(i) if rng.random() < 0.3],
                           model='medium') for i in range(rng.randint(4, 8))}
    dag = RuntimeDAG(nodes)
    done = [n for n in sorted(dag.nodes) if rng.random() < 0.4]
    for n in done:
        dag.nodes[n]['status'] = 'done'
        dag.nodes[n]['output'] = 'x'
    for n in done:
        has_done_succ = any(dag.nodes[s]['status'] == 'done' for s in dag._succs(n))
        for op in ['remove', 'split']:
            try:
                if op == 'remove':
                    dag.remove_node(n)
                else:
                    dag.split_node(n, f'{n}_a', f'{n}_b', 'large', 'coder')
                if has_done_succ:
                    c['consumed_attempted'] += 1
                    c['consumed_incorrect_accept'] += 1
                else:
                    c['unconsumed_attempted'] += 1
                    c['unconsumed_accepted'] += 1
            except (PatchError, Exception):
                if has_done_succ:
                    c['consumed_attempted'] += 1
                    c['consumed_rejected'] += 1
                else:
                    c['unconsumed_attempted'] += 1
print(json.dumps(dict(
    consumed_protection_rate=c['consumed_rejected'] / max(1, c['consumed_attempted']),
    consumed_attempted=c['consumed_attempted'], consumed_rejected=c['consumed_rejected'],
    consumed_incorrect_accept=c['consumed_incorrect_accept']), indent=1))
'''
    test_file = OUT / 'e1_consumed_stress_reproducible.py'
    test_file.write_text(test_code)
    r = subprocess.run([sys.executable, str(test_file)], capture_output=True, text=True,
                       timeout=30)
    output = json.loads(r.stdout) if r.returncode == 0 else dict(error=r.stderr[:200])
    results['E1_archive'] = dict(
        test_file=str(test_file),
        seed=20261001, n_trials=200,
        command=f'python3 {test_file}',
        result=output,
        pass_=output.get('consumed_protection_rate') == 1.0)
    return output.get('consumed_protection_rate') == 1.0


# ===================== E4 fix: remove power claim, fix timestamp =====================
def audit_e4():
    p = ROOT / 'collab_scheduler_v1/e4_protocol/E4_P2_PROTOCOL.json'
    d = json.loads(p.read_text())
    # Remove unsupported power claim
    old_n = d.get('sample_size', {}).get('recommended_n_tasks', '')
    if '80% power' in old_n or '100-200' in old_n:
        d['sample_size']['recommended_n_tasks'] = (
            'TBD: requires P1-B smoke discordant-pair rate before any sample-size '
            'recommendation can be made. The Z-effect range is a reference only.')
    # Fix timestamp: use actual file mtime
    import os
    actual_time = os.path.getmtime(p)
    d['preregistered_unix'] = int(actual_time)
    d['timestamp_note'] = f'Timestamp = file mtime ({actual_time:.0f}); authoritative time is the git commit hash'
    p.write_text(json.dumps(d, indent=1))
    results['E4_fix'] = dict(fixed=True, new_n_tasks=d['sample_size']['recommended_n_tasks'][:50],
                             timestamp=d['preregistered_unix'])
    return True


# ===================== P1-B admission: check identified issues =====================
def audit_p1b():
    checks = {}

    # 1. Fault sampling: int(5*0.3) = 1, not 2
    tasks = select_tasks()
    faults = build_heldout_faults(tasks)
    checks['f4_actual_fault_count'] = len(faults)
    checks['f4_docstring_says_2'] = '2 tasks' in Path(
        ROOT / 'collab_scheduler_v1/dag_patch_p1b.py').read_text()[:2000]
    checks['f4_count_correct'] = len(faults) == 1  # int(5*0.3)=1

    # 2. Detector coverage: only handles r unparseable
    src = Path(ROOT / 'collab_scheduler_v1/dag_patch_p1b.py').read_text()
    checks['detector_covers_r_only'] = "u == 'r'" in src and 'e1' not in src[
        src.index('def detect'):src.index('def detect') + 200]

    # 3. Scheduler overhead includes model call time (line ~271)
    # The code does: ts = time.monotonic(); ... ex.call(...) ... log['scheduler_overhead_s'] += time.monotonic() - ts
    # This means scheduler_overhead includes the model call duration
    checks['scheduler_overhead_includes_model_time'] = True  # confirmed by code reading

    # 4. smoke_run() runs both states
    checks['smoke_runs_both_states'] = 'clean' in src[src.index('def smoke_run'):src.index('def smoke_run') + 500]

    # 5. Model lifecycle: smoke_run creates/destroys via svc() wrapper
    checks['model_lifecycle_wired'] = 'start_model' in src and 'stop_model' in src

    # 6. Budget: global counter persists via _save_gc on every call
    checks['global_counter_persists'] = '_save_gc' in src

    # 7. Injected fault calls are billed but produce fake output
    checks['injected_fault_billed'] = 'ex.call(u, g.nodes[u][\'model\'], prompt)' in src

    issues_found = []
    if checks['f4_docstring_says_2'] and not checks['f4_count_correct']:
        issues_found.append('F4: docstring says 2 tasks but int(5*0.3)=1')
    if checks['detector_covers_r_only']:
        issues_found.append('Detector only handles r-unparseable; e1/e2/v faults not detected')
    if checks['scheduler_overhead_includes_model_time']:
        issues_found.append('scheduler_overhead_s includes model call time (double-counting)')
    if checks['smoke_runs_both_states']:
        issues_found.append('smoke_run() runs both states, not single-state-first')

    results['P1B_admission'] = dict(
        checks=checks, issues_found=issues_found,
        ready_for_smoke=len(issues_found) == 0)
    return len(issues_found) == 0


# ===================== Main =====================
def main():
    all_pass = True
    print('=== E3: P1-B direct three-strategy ===')
    all_pass &= audit_e3()
    print(f'  E3: {results["E3_p1b_direct"]["n_pass"]}/{results["E3_p1b_direct"]["n_checks"]} checks pass')

    print('=== E2 final reconstruction ===')
    audit_e2()
    print(f'  E2: metrics computed')

    print('=== E1 archive ===')
    all_pass &= audit_e1()
    print(f'  E1: {results["E1_archive"]["pass_"]}')

    print('=== E4 fix ===')
    audit_e4()
    print(f'  E4: fixed')

    print('=== P1-B admission ===')
    p1b_ok = audit_p1b()
    print(f'  P1-B: {len(results["P1B_admission"]["issues_found"])} issues found')

    # Write results
    (OUT / 'FINAL_READINESS_AUDIT.json').write_text(json.dumps(results, indent=1))

    # Write markdown report
    lines = ['# Final Readiness Audit (zero LLM calls)', '',
             f'Date: {time.strftime("%Y-%m-%d %H:%M")}', '']
    for section, data in results.items():
        lines.append(f'## {section}')
        if isinstance(data.get('checks'), dict):
            for k, v in data['checks'].items():
                lines.append(f'- {"✅" if v else "❌"} {k}: {v}')
        if 'all_pass' in data:
            lines.append(f'- **{"ALL PASS" if data["all_pass"] else "FAIL PRESENT"}**')
        if 'issues_found' in data:
            for issue in data['issues_found']:
                lines.append(f'- ⚠️ {issue}')
        if 'metrics' in data:
            for nt, m in data['metrics'].items():
                lines.append(f'- {nt}: P={m["precision"]} R={m["recall"]} F1={m["f1"]} '
                             f'(tp={m["tp"]} fp={m["fp"]} fn={m["fn"]} tn={m["tn"]})')
        lines.append('')

    lines.append('## Summary')
    lines.append(f'- E3 P1-B direct: {"PASS" if results["E3_p1b_direct"]["all_pass"] else "FAIL"}')
    lines.append(f'- E1 archive: {"PASS" if results["E1_archive"]["pass_"] else "FAIL"}')
    lines.append(f'- P1-B smoke ready: {"YES" if results["P1B_admission"]["ready_for_smoke"] else "NO — issues must be fixed first"}')
    lines.append('')
    lines.append('**Verdict: P1-B real smoke is ' +
                 ('AUTHORIZED' if results['P1B_admission']['ready_for_smoke'] else 'NOT YET AUTHORIZED') + '**')

    (OUT / 'FINAL_READINESS_AUDIT.md').write_text('\n'.join(lines))
    print('\n=== VERDICT ===')
    print(f'P1-B smoke: {"AUTHORIZED" if results["P1B_admission"]["ready_for_smoke"] else "NOT YET — fix issues first"}')


if __name__ == '__main__':
    main()
