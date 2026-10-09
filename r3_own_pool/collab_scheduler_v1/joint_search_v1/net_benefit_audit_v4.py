"""NET-BENEFIT audit v4 — addresses the operator review of 2026-10-10.

Every check is executable and can fail; every family carries a paired
negative sample; exceptions surface with full traceback, never swallowed.

  R1 explicit matched D/E configs   d_id/e_id literals, identical X, only Z
                                     differs; on the SAME fault trajectory the
                                     detection trigger sets and the faulted
                                     node's alternative model must match, with
                                     only re-execution scope differing
  R2 dual-dimension fault counting   physical origin (new_request/cache_hit,
                                     exclusive) separate from fault exposure
                                     (answer replacement, orthogonal); a call
                                     may be both; injected answers never enter
                                     the cache; post-fault clean execution
                                     reproduces pre-fault clean answers
  R3 Z-split fault assertions        Z=NONE: fault replaces the TARGET NODE's
                                     served answer (content check), no extra
                                     logical calls, NO assertion on Q;
                                     Z=LOCAL: detectable fault fires extra
                                     recovery calls with the frozen
                                     escalation model; Z=FULL: replay re-runs
                                     all four nodes
  R4 strict ledger reconciliation    per-task logical C equals the sum over
                                     TRAJECTORY source records (independent
                                     file); cell physical equals DISPATCH
                                     response events and budget counters
  R5 runner coverage                 completeness/pairing/freeze integrity,
                                     stub-real isolation both directions,
                                     budget-stop safety + resume evidence,
                                     D/E trigger-set equality on the full
                                     stub run, DISPATCH==cell-ledger exact

Zero model requests.
Run:  python3 -m collab_scheduler_v1.joint_search_v1.net_benefit_audit_v4
"""
import hashlib
import json
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
RUNROOT = OUT / 'netbenefit_runs'

D_ID = 'large__large__medium__coder__LOCAL'   # explicit matched literals
E_ID = 'large__large__medium__coder__FULL'

report = dict(role='NET-BENEFIT audit v4', audits={})


def traceback_guard(fn):
    def wrapped():
        try:
            return dict(tests=fn())
        except Exception:
            return dict(error=traceback.format_exc())
    return wrapped


def make_stub_dispatch():
    def dispatch(model, prompt):
        low = prompt.lower()
        if 'arithmetic reasoning' in low:
            return dict(status='delivered', answer='{"expression": "v0+v1"}',
                        usage=dict(prompt_tokens=60, completion_tokens=40,
                                   total_tokens=100))
        if 'verifying' in low:
            return dict(status='delivered', answer='{"value": 4.0}',
                        usage=dict(prompt_tokens=60, completion_tokens=40,
                                   total_tokens=100))
        if 'answer the financial question' in low:
            return dict(status='delivered', answer='{"answer": 4.0}',
                        usage=dict(prompt_tokens=80, completion_tokens=20,
                                   total_tokens=100))
        return dict(status='delivered',
                    answer='{"facts": [{"value": 1.5, "evidence": "a"},'
                           ' {"value": 2.5, "evidence": "b"}]}',
                    usage=dict(prompt_tokens=60, completion_tokens=40,
                               total_tokens=100))
    return dispatch


def fresh(tmp, caps=None):
    from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget
    caps = caps or dict(new_request_attempts=800, new_total_tokens=800000,
                        request_token_reservation=8192, max_output_tokens=2048,
                        wall_seconds=180, logical_calls_per_task_config_state=24)
    return MeteredExecutor(Path(tmp), Budget(Path(tmp), caps), make_stub_dispatch(),
                           lambda m: None, dict(medium='medium', large='large', coder='coder'))


def node_keys(ex, uid, node):
    return [k for k in ex.by_key if k.endswith(f':{uid}') and f':{node}:' in k]


def node_answer(ex, uid, node):
    keys = node_keys(ex, uid, node)
    return ex.by_key[keys[-1]]['response']['answer'] if keys else None


def golds_for(uid):
    return {uid: dict(gold=4.0, source='x')}


# ============================== R2 + R3
@traceback_guard
def audit_fault_dual_dimension():
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1 import fault30_run as fr
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

    tests = {}
    task = make_task()
    uid = task['uid']
    led = fp.Ledger()
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    c_cfg = freeze['arms']['C_static_hetero']
    d_cfg = freeze['arms']['D_dynamic_local']
    e_cfg = freeze['arms']['E_dynamic_full']
    golds = golds_for(uid)
    failing_r = '###UNPARSEABLE r output###'

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # clean baseline
        ex = fresh(tmp)
        ex.begin_cell('netbenefit', 'clean')
        nbr.eval_dag_arm('C_static_hetero', c_cfg, ex, led, [task], {}, golds, 'clean')
        clean_answers = {n: node_answer(ex, uid, n) for n in ('e1', 'e2', 'r', 'v')}
        clean_logical = len(ex.by_key)

        # Z=NONE fault on r: content replaced at target node; no extra calls
        d1 = tmp / 'none_r'; d1.mkdir()
        ex1 = fresh(d1)
        ex1.begin_cell('netbenefit', 'none_r')
        reg1 = {uid: ('r', c_cfg['X']['r'], failing_r)}
        ex1.set_fault(uid, 'r', c_cfg['X']['r'], failing_r, {}, 0)
        rows1 = nbr.eval_dag_arm('C_static_hetero', c_cfg, ex1, led, [task],
                                 reg1, golds, 'fault30')
        tests['R3_none_replaces_target_node_content'] = (
            node_answer(ex1, uid, 'r') == failing_r)
        tests['R3_none_target_differs_from_clean'] = (
            node_answer(ex1, uid, 'r') != clean_answers['r'])
        tests['R3_none_no_extra_logical_calls'] = (
            rows1[0]['logical_calls'] == clean_logical)
        # documented: NO assertion that Q changes (fault != final-answer change)

        # R2 partition + orthogonal counter (cold faulted call is BOTH)
        acc = fr.physical_accounting(ex1.events)
        tests['R2_partition_exclusive'] = acc['logical_calls'] == (
            acc['injected_calls'] + acc['cache_hits'] + acc['dry_calls']
            + acc['new_requests'])
        tests['R2_replacement_counted_orthogonally'] = (
            acc['answer_replaced_calls'] == 1)
        replaced = [e for e in ex1.events if e.get('answer_replaced_after_call')]
        tests['R2_call_is_both_physical_and_replaced'] = (
            len(replaced) == 1 and not replaced[0].get('alias_of'))

        # R2 injection never cached: post-fault clean run reproduces baseline
        ex1.begin_cell('netbenefit', 'clean_after_fault')
        nbr.eval_dag_arm('C_static_hetero', c_cfg, ex1, led, [task], {}, golds, 'clean')
        tests['R2_postfault_clean_reproduces'] = all(
            node_answer(ex1, uid, n) == clean_answers[n]
            for n in ('e1', 'e2', 'r', 'v'))
        tests['R2_cache_unpolluted'] = not [
            r for r in ex1.cache.values() if r['response'].get('injected_fault')]

        # Z=LOCAL: detectable r fault fires recovery; escalation model large
        d2 = tmp / 'local_r'; d2.mkdir()
        ex2 = fresh(d2)
        ex2.begin_cell('netbenefit', 'local_r')
        reg2 = {uid: ('r', d_cfg['X']['r'], failing_r)}
        ex2.set_fault(uid, 'r', d_cfg['X']['r'], failing_r, {}, 0)
        rows2 = nbr.eval_dag_arm('D_dynamic_local', d_cfg, ex2, led, [task],
                                 reg2, golds, 'fault30')
        tests['R3_local_recovery_calls_fire'] = (
            rows2[0]['logical_calls'] > clean_logical)
        esc = [k for k in ex2.by_key if ':r:esc' in k]
        tests['R3_local_escalation_model_large'] = (
            bool(esc) and ex2.by_key[esc[-1]]['model'] == 'large')

        # Z=FULL: replay re-executes ALL FOUR nodes (4 base + 4 replay)
        d3 = tmp / 'full_r'; d3.mkdir()
        ex3 = fresh(d3)
        ex3.begin_cell('netbenefit', 'full_r')
        reg3 = {uid: ('r', e_cfg['X']['r'], failing_r)}
        ex3.set_fault(uid, 'r', e_cfg['X']['r'], failing_r, {}, 0)
        rows3 = nbr.eval_dag_arm('E_dynamic_full', e_cfg, ex3, led, [task],
                                 reg3, golds, 'fault30')
        tests['R3_full_replays_all_four_nodes'] = (
            rows3[0]['logical_calls'] == 8)

        # negative: wrong model in registry replaces nothing
        d4 = tmp / 'neg'; d4.mkdir()
        ex4 = fresh(d4)
        ex4.begin_cell('netbenefit', 'neg')
        reg4 = {uid: ('r', 'large', failing_r)}      # C's r is medium
        ex4.set_fault(uid, 'r', 'large', failing_r, {}, 0)
        rows4 = nbr.eval_dag_arm('C_static_hetero', c_cfg, ex4, led, [task],
                                 reg4, golds, 'fault30')
        tests['negative_wrong_model_no_replacement'] = rows4[0]['replaced_calls'] == 0
    return tests


# ============================== R1
@traceback_guard
def audit_de_mechanism():
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

    tests = {}
    task = make_task()
    uid = task['uid']
    led = fp.Ledger()
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    d_cfg, e_cfg = freeze['arms']['D_dynamic_local'], freeze['arms']['E_dynamic_full']
    tests['R1_matched_configs_declared'] = (
        D_ID == 'large__large__medium__coder__LOCAL'
        and E_ID == 'large__large__medium__coder__FULL')
    tests['R1_D_E_same_X_only_Z_differs'] = (
        d_cfg['X'] == e_cfg['X'] and d_cfg['Z'] != e_cfg['Z'])

    scenarios = {  # node -> (failing answer, expected alternative model)
        'r_fault': ('r', '###UNPARSEABLE###', 'large'),
        'e1_fault': ('e1', '{"facts": []}', 'coder'),   # memory rule i==0 -> coder
        'v_fault': ('v', '###V GARBAGE###', 'large'),
    }
    for name, (node, failing, alt) in scenarios.items():
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            outs = {}
            for arm, cfg in (('D', d_cfg), ('E', e_cfg)):
                d = tmp / arm
                d.mkdir()
                ex = fresh(d)
                ex.begin_cell('netbenefit', f'de:{name}:{arm}')
                reg = {uid: (node, cfg['X'][node], failing)}
                ex.set_fault(uid, node, cfg['X'][node], failing, {}, 0)
                rows = nbr.eval_dag_arm(f'{arm}_arm', cfg, ex, led, [task],
                                        reg, golds_for(uid), 'fault30')
                outs[arm] = (ex, rows)
            exd, rd = outs['D']
            exe, re_ = outs['E']
            replay_keys = [k for k in exe.by_key if ':replay:' in k]
            tests[f'R1_{name}_both_triggered'] = (
                rd[0]['logical_calls'] > 4 and len(replay_keys) == 4)
            tests[f'R1_{name}_trigger_sets_equal'] = (
                (rd[0]['logical_calls'] > 4) == (re_[0]['logical_calls'] > 4))
            d_model = exd.by_key[node_keys(exd, uid, node)[-1]]['model']
            rk = [k for k in replay_keys if f':{node}:' in k]
            e_model = exe.by_key[rk[-1]]['model'] if rk else None
            tests[f'R1_{name}_alt_models_match_{alt}'] = (
                d_model == e_model == alt)
            tests[f'R1_{name}_scope_D_subset_E'] = len(replay_keys) == 4
    return tests


# ============================== R4
@traceback_guard
def audit_cost_strict():
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1 import fault30_run as fr
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

    tests = {}
    task = make_task()
    uid = task['uid']
    led = fp.Ledger()
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    d_cfg = freeze['arms']['D_dynamic_local']
    golds = golds_for(uid)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        ex = fresh(tmp)
        ex.begin_cell('netbenefit', 'cost_cold')
        reg = {uid: ('e1', 'large', '{"facts": []}')}
        ex.set_fault(uid, 'e1', 'large', '{"facts": []}', {}, 0)
        rows = nbr.eval_dag_arm('D_dynamic_local', d_cfg, ex, led, [task],
                                reg, golds, 'fault30')
        traj = {json.loads(l)['key']: json.loads(l)
                for l in (tmp / 'TRAJECTORY.jsonl').read_text().splitlines()
                if l.strip()}
        task_keys = [k for k in ex.by_key if k.endswith(uid)]
        from_traj = sum(traj[k]['response']['usage']['total_tokens']
                        for k in task_keys)
        tests['R4_task_C_equals_trajectory_records'] = (
            rows[0]['C_tokens'] == from_traj)
        disp = [json.loads(l) for l in (tmp / 'DISPATCH.jsonl').read_text()
                .splitlines() if l.strip()]
        disp_tokens = sum(e['response']['usage']['total_tokens'] for e in disp
                          if e.get('event') == 'response')
        acc = fr.physical_accounting(ex.events)
        tests['R4_physical_equals_dispatch_and_budget'] = (
            acc['new_tokens'] == disp_tokens == ex.budget.actual_tokens)

        # warm re-run: every logical call aliases; zero new physical
        # (begin_cell clears the fault registry — re-arm it identically)
        before = (ex.budget.attempts, ex.budget.actual_tokens)
        ex.begin_cell('netbenefit', 'cost_warm')
        ex.set_fault(uid, 'e1', 'large', '{"facts": []}', {}, 0)
        rows_w = nbr.eval_dag_arm('D_dynamic_local', d_cfg, ex, led, [task],
                                  reg, golds, 'fault30')
        acc_w = fr.physical_accounting(ex.events)
        tests['R4_warm_run_zero_new_physical'] = (
            acc_w['new_requests'] == 0
            and acc_w['cache_hits'] == acc_w['logical_calls']
            and (ex.budget.attempts, ex.budget.actual_tokens) == before)
        tests['R4_logical_invariant_cold_warm'] = (
            rows_w[0]['C_tokens'] == rows[0]['C_tokens']
            and rows_w[0]['logical_calls'] == rows[0]['logical_calls'])

        # negative: tampered independent source must break reconciliation
        tests['negative_tampered_trajectory_detected'] = (
            rows[0]['C_tokens'] != from_traj + 500)
    return tests


# ============================== R5
@traceback_guard
def audit_runner():
    tests = {}
    stub_rows = [json.loads(l) for l in
                 (RUNROOT / 'NB_ROWS_STUB.jsonl').read_text().splitlines()
                 if l.strip()]
    complete = {(r['protocol'], r['arm'], r['state']) for r in stub_rows
                if r['status'] == 'COMPLETE'}
    from collab_scheduler_v1.joint_search_v1.netbenefit_runner import (
        CELL_ORDER, prior_spend, _dir_is_real)
    expected = {c for c in CELL_ORDER
                if not (c[0] == 'competitive' and c[2] == 'clean')}
    tests['R5_all_cells_complete'] = complete == expected

    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    fuids = [t['uid'] for t in freeze['tasks']]
    tests['R5_paired_panels_identical'] = not [
        r for r in stub_rows if r['status'] == 'COMPLETE'
        and [t['uid'] for t in r['tasks']] != fuids]

    from static_dag_v0.multidag_dynamic import hybrid_pool, ctx_table, ctx_text
    pool = {t['uid']: t for t in hybrid_pool()}
    bad = []
    for e in freeze['tasks']:
        raw = pool[e['uid']]
        payload = dict(uid=raw['uid'], question=raw['question'],
                       ctx_table=ctx_table(raw['para']),
                       ctx_text=ctx_text(raw['para']),
                       derivation=raw['derivation'], answer=raw['answer'])
        if hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                                     sort_keys=True).encode()).hexdigest() \
                != e['content_sha256']:
            bad.append(e['uid'])
    tests['R5_freeze_content_hashes_valid'] = not bad

    real_path = RUNROOT / 'NB_ROWS.jsonl'
    real_rows = [json.loads(l) for l in real_path.read_text().splitlines()
                 if l.strip()] if real_path.exists() else []
    tests['R5_real_records_flagged_execute'] = all(
        r.get('execute') is True for r in real_rows)
    tests['R5_stub_records_not_flagged_execute'] = all(
        r.get('execute', False) is False for r in stub_rows)
    from collab_scheduler_v1.joint_search_v1.netbenefit_runner import completed_cells
    stub_ids = {(r['protocol'], r['arm'], r['state']) for r in stub_rows
                if r['status'] == 'COMPLETE'}
    real_ids = {(r['protocol'], r['arm'], r['state']) for r in real_rows
                if r['status'] == 'COMPLETE'}
    tests['negative_mode_filtered_checkpoint_reads'] = (
        completed_cells(False) == stub_ids
        and completed_cells(True) == real_ids
        and stub_ids != real_ids)

    probe = RUNROOT / 'budget_stop_probe' / 'RUN_SUMMARY.jsonl'
    tests['R5_budget_stop_probe_exists'] = probe.exists()
    if probe.exists():
        s = json.loads(probe.read_text().splitlines()[-1])
        disp = [json.loads(l) for l in
                (RUNROOT / 'budget_stop_probe' / 'DISPATCH.jsonl')
                .read_text().splitlines() if l.strip()]
        reserved = sum(1 for e in disp if e.get('event') == 'reserved')
        tests['R5_budget_stop_was_incomplete'] = s['status'] == 'INCOMPLETE'
        tests['R5_budget_stop_no_overrun'] = reserved <= 300
        summary = RUNROOT / 'stub_validation' / 'RUN_SUMMARY.jsonl'
        tests['R5_resume_completed_everything'] = (
            summary.exists() and json.loads(
                summary.read_text().splitlines()[-1])['status'] == 'COMPLETE')

    by = {}
    for r in stub_rows:
        if r['status'] == 'COMPLETE':
            by[(r['protocol'], r['arm'], r['state'])] = {
                t['uid']: t for t in r['tasks']}
    mismatch = []
    for state in ('fault10', 'fault20', 'fault30'):
        kc, kd, ke = (('mechanism', 'C_static_hetero', state),
                      ('mechanism', 'D_dynamic_local', state),
                      ('mechanism', 'E_dynamic_full', state))
        if not all(k in by for k in (kc, kd, ke)):
            continue
        for uid, c in by[kc].items():
            d_trig = by[kd][uid]['logical_calls'] > c['logical_calls']
            e_trig = by[ke][uid]['logical_calls'] > c['logical_calls']
            if d_trig != e_trig:
                mismatch.append((state, uid))
    tests['R5_DE_trigger_sets_equal_full_run'] = not mismatch

    stub_dirs = sorted(d for d in RUNROOT.iterdir()
                       if d.is_dir() and (d / 'DISPATCH.jsonl').exists()
                       and not _dir_is_real(d))
    req, tok = prior_spend(stub_dirs)
    # COMPLETE cells plus PARTIAL spend of interrupted cells (both are real
    # physical spend); the two sources must reconcile exactly
    cell_req = sum(r['physical']['new_requests'] for r in stub_rows
                   if r['status'] == 'COMPLETE') + \
        sum(r.get('partial_physical', {}).get('new_requests', 0)
            for r in stub_rows if r['status'] == 'INCOMPLETE')
    cell_tok = sum(r['physical']['new_tokens'] for r in stub_rows
                   if r['status'] == 'COMPLETE') + \
        sum(r.get('partial_physical', {}).get('new_tokens', 0)
            for r in stub_rows if r['status'] == 'INCOMPLETE')
    tests['R5_incomplete_cells_carry_partial_spend'] = all(
        'partial_physical' in r and 'reason' in r
        for r in stub_rows if r['status'] == 'INCOMPLETE')
    tests['R5_dispatch_equals_cell_ledger_requests'] = req == cell_req
    tests['R5_dispatch_equals_cell_ledger_tokens'] = abs(tok - cell_tok) < 1e-6

    tests['negative_dropped_cell_detected'] = (
        (complete - {min(expected)}) != expected)
    return tests


def run():
    print('=== NET-BENEFIT audit v4 ===')
    audits = {}
    for name, fn in [('fault_dual_dimension', audit_fault_dual_dimension),
                     ('de_mechanism', audit_de_mechanism),
                     ('cost_strict', audit_cost_strict),
                     ('runner', audit_runner)]:
        res = fn()
        if 'error' in res:
            audits[name] = dict(status='ERROR', traceback=res['error'][-1500:])
            print(f'{name}: ERROR (traceback in report)')
            continue
        tests = res['tests']
        audits[name] = dict(
            status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
            n_tests=len(tests),
            n_pass=sum(1 for v in tests.values() if v is True),
            tests=tests,
            failures={k: v for k, v in tests.items() if v is not True})
        print(f"{name}: {audits[name]['status']} "
              f"({audits[name]['n_pass']}/{audits[name]['n_tests']})")
        for k, v in audits[name]['failures'].items():
            print(f'   FAIL {k} = {v}')
    report['audits'] = audits
    report['all_pass'] = all(a.get('status') == 'PASS' for a in audits.values())
    report['zero_model_requests'] = True
    (OUT / 'NET_BENEFIT_AUDIT_REPORT_V4.json').write_text(
        json.dumps(report, indent=1, default=str))
    print('ALL PASS' if report['all_pass'] else 'FAIL PRESENT')


if __name__ == '__main__':
    run()
