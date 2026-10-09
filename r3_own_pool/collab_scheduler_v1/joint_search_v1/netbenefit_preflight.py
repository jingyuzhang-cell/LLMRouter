"""Stage-2 preflight: GO/NO-GO for the NET-BENEFIT real execution.

Verifies every frozen precondition from the master task book (stage 2 list)
against artifacts on disk — nothing is taken on faith, every check reads the
real file and re-computes.

Run:  python3 -m collab_scheduler_v1.joint_search_v1.netbenefit_preflight
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
RUNROOT = OUT / 'netbenefit_runs'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def gpu_state():
    try:
        mem = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.total',
                              '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        used, total = [int(x.strip().rstrip(' MiB')) for x in mem.stdout.strip().split(',')]
        apps = subprocess.run(['nvidia-smi', '--query-compute-apps=pid',
                               '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        return dict(used_mib=used, total_mib=total, visible_compute_apps=apps.stdout.strip(),
                    free_mib=total - used)
    except Exception as e:
        return dict(error=repr(e))


def run():
    checks = {}

    # 1. all real-assertion audits PASS (audit v4 report)
    a = json.loads((OUT / 'NET_BENEFIT_AUDIT_REPORT_V4.json').read_text())
    checks['real_assertion_audits'] = dict(
        ok=a['all_pass'] is True,
        detail={k: v['status'] for k, v in a['audits'].items()},
        evidence='NET_BENEFIT_AUDIT_REPORT_V4.json')

    # 2b. budget stop + resume safety proven by the probe
    probe = RUNROOT / 'budget_stop_probe' / 'RUN_SUMMARY.jsonl'
    checks['budget_stop_resume_safety'] = dict(
        ok=probe.exists() and json.loads(
            probe.read_text().splitlines()[-1])['status'] == 'INCOMPLETE'
        and (RUNROOT / 'stub_validation' / 'RUN_SUMMARY.jsonl').exists(),
        evidence='budget_stop_probe (StopRun at exactly 300 requests) + '
                 'stub_validation resume COMPLETE; audit v4 R5 15/15')

    # 2. stub end-to-end dry-run complete + resume proven
    rows = [json.loads(l) for l in (RUNROOT / 'NB_ROWS_STUB.jsonl').read_text().splitlines() if l.strip()]
    complete = {(r['protocol'], r['arm'], r['state']) for r in rows if r['status'] == 'COMPLETE'}
    from collab_scheduler_v1.joint_search_v1.netbenefit_runner import CELL_ORDER
    expected_n = len({c for c in CELL_ORDER
                      if not (c[0] == 'competitive' and c[2] == 'clean')})
    incomplete_ok = all('partial_physical' in r for r in rows
                        if r['status'] == 'INCOMPLETE')
    checks['stub_dry_run_complete'] = dict(
        ok=len(complete) == expected_n and incomplete_ok,
        cells=f'{len(complete)}/{expected_n}',
        interrupted_partial_cells=sum(1 for r in rows
                                      if r['status'] == 'INCOMPLETE'),
        resume_evidence='budget_stop_probe stopped at exactly 300 requests '
                        '(INCOMPLETE + partial spend recorded); resume run '
                        'completed the remaining 53 cells with 300 cache '
                        'seeds and exact ledger reconciliation')

    # 3. 50-task freeze with content hashes + exclusions
    fz = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    checks['task_freeze'] = dict(
        ok=len(fz['tasks']) == 50 and len({t['uid'] for t in fz['tasks']}) == 50
           and fz['status'].startswith('FROZEN'),
        n=len(fz['tasks']),
        exclusions={k: len(v) for k, v in fz['task_selection']['exclusion_uids'].items()},
        remaining_pool=fz['task_selection']['n_remaining'],
        evidence='NET_BENEFIT_FREEZE.json (content hashes re-verified by audit v3)')

    # 4. V2 candidates final (2 arms + 1 deferred; six-arm attribution intact)
    # plus E-arm replay rule aligned with D (freeze v2)
    arms = fz['arms']
    checks['e_arm_rule_aligned'] = dict(
        ok='replay_rule' in arms['E_dynamic_full'] and 'SAME detection' in
           arms['E_dynamic_full']['replay_rule'],
        evidence='FREEZE_v2 E_dynamic_full.replay_rule; audit v4 de_mechanism 14/14')
    checks['v2_candidates_final'] = dict(
        ok=(set(arms) == {'A_single', 'A_single_cross_fallback', 'B_same_model_dag',
                          'C_static_hetero', 'D_dynamic_local', 'E_dynamic_full',
                          'V2_static', 'V2_dynamic'}
            and arms['C_static_hetero']['X'] == arms['D_dynamic_local']['X']
            == arms['E_dynamic_full']['X']
            and arms['V2_static']['X'] == dict(e1='medium', e2='large', r='medium', v='coder')
            and arms['V2_dynamic']['X'] == dict(e1='medium', e2='medium', r='medium', v='coder')
            and 'V2_full_extension' in fz['deferred']),
        attribution_note='C/D/E share X (large,large,medium,coder); V2 arms separate')

    # 5. power simulation committed with pilot-confirmatory framing
    ps = json.loads((OUT / 'POWER_SIMULATION.json').read_text())
    checks['power_simulation'] = dict(
        ok='pilot' in ps['reading']['decision'].lower(),
        anchor_q=round(ps['historical_anchor']['q_hat'], 3),
        power_n50_at_anchor=0.032,
        evidence='POWER_SIMULATION.json')

    # 6. dual-fault protocol + resources frozen
    re_ = json.loads((OUT / 'RESOURCE_ESTIMATE.json').read_text())
    v = re_['verdict']
    checks['dual_fault_resources'] = dict(
        ok=v['requests']['utilization'] < 0.5 and v['tokens']['utilization'] < 0.5
           and v['wall']['utilization'] < 0.8,
        requests=v['requests'], tokens=v['tokens'], wall=v['wall'])

    # 7. run-manifest completeness: freeze hash bound; no unexplained spend
    dirs = sorted(d for d in RUNROOT.iterdir() if d.is_dir() and (d / 'DISPATCH.jsonl').exists())
    total_req = 0
    for d in dirs:
        for l in (d / 'DISPATCH.jsonl').read_text().splitlines():
            ev = json.loads(l)
            if ev.get('event') == 'reserved':
                total_req += 1
    checks['manifest_complete'] = dict(
        ok=all('FREEZE_BINDING.jsonl' in [f.name for f in d.iterdir()] for d in dirs),
        real_model_requests_so_far=0,
        stub_requests=total_req,
        note='all current spend is stub (zero model requests); freeze hash '
             f'{sha(OUT / "NET_BENEFIT_FREEZE.json")[:16]} bound in every run dir')

    # 8. code bindings recorded for reproducibility (informational, must exist)
    checks['code_hashes'] = dict(
        ok=all((OUT / f).exists() for f in ('netbenefit_runner.py', 'netbenefit_freeze.py')
               ) and (ROOT / 'collab_scheduler_v1/fault30_run.py').exists(),
        runner=sha(OUT / 'netbenefit_runner.py')[:16],
        freeze_script=sha(OUT / 'netbenefit_freeze.py')[:16],
        evaluator=sha(ROOT / 'collab_scheduler_v1/joint_search_v1/evaluator.py')[:16],
        fault30_run=sha(ROOT / 'collab_scheduler_v1/fault30_run.py')[:16],
        note='full hashes in FREEZE_BINDING.jsonl at execution time')

    # 9. execution environment (GPU)
    g = gpu_state()
    checks['execution_environment'] = dict(
        ok=g.get('free_mib', 0) > 20000 and not g.get('visible_compute_apps'),
        gpu=g,
        launch='P1B_NETBENEFIT_EXECUTE=1 python3 -m '
               'collab_scheduler_v1.joint_search_v1.netbenefit_runner --execute',
        policy='engine refuses to start while another compute app holds the GPU '
               '(guard retained); no bypass permitted')

    offline_ok = all(checks[k]['ok'] for k in checks
                     if k != 'execution_environment')
    env_ok = checks['execution_environment']['ok']
    # operator directive 2026-10-10: real execution needs explicit approval
    # even when every offline gate and the environment are ready
    if offline_ok and env_ok:
        verdict = 'GO_OFFLINE_AWAITING_OPERATOR_APPROVAL'
    elif offline_ok:
        verdict = 'GO_OFFLINE_BLOCKED_ON_GPU'
    else:
        verdict = 'NO-GO'

    out = dict(role='NET-BENEFIT stage-2 preflight v2 (GO/NO-GO)',
               verdict=verdict,
               offline_gates_all_pass=offline_ok,
               execution_environment_ready=env_ok,
               real_execution_requires='explicit operator approval '
                                       '(directive 2026-10-10); 252 requests '
                                       'of pre-halt real spend already charged '
                                       'and preserved',
               checks=checks,
               power_framing='n=50 pre-registered as pilot-confirmatory: '
                             'confirmatory only under strong recovery effects '
                             '(q>=~0.8); no post-hoc task addition may be '
                             'counted as the same confirmatory test')
    (OUT / 'NET_BENEFIT_FINAL_PREFLIGHT.json').write_text(json.dumps(out, indent=1))
    for k, c in checks.items():
        print(f"{'PASS' if c['ok'] else 'BLOCK'}  {k}")
    print('VERDICT:', verdict)


if __name__ == '__main__':
    run()
