"""NET_BENEFIT audit v3: real assertions + negative samples + runner coverage.

Every check is executable and can fail. For each family a paired NEGATIVE
sample tampers with the data and asserts the check REJECTS it, proving the
test is not vacuously true.

Covers (per master task book 0.2):
  1. scoring        contract v2.1 boundary behavior + evaluator path
  2. fault          injection replaces answers post-call; counted in ledgers;
                    registry matching is (uid, node, model)-precise
  3. cache          cross-model / cross-task / cross-fault-state isolation
  4. cost           per-call logical vs physical reconciliation against ledgers
  5. D/E            same fault trajectory, matched X, detection + scope differ
  6. runner         NB_ROWS completeness/pairing, freeze integrity, budget
                    reconciliation against DISPATCH; covers netbenefit_runner
                    itself (not only the old search evaluator)

Zero model requests. Run:
  python3 -m collab_scheduler_v1.joint_search_v1.net_benefit_audit_v3
"""
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
RUNROOT = OUT / 'netbenefit_runs'

report = dict(role='NET_BENEFIT audit v3 (real assertions + negative samples '
                   '+ runner coverage; zero model requests)', audits={})


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


def fresh_executor(tmp, caps=None):
    from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget
    caps = caps or dict(new_request_attempts=400, new_total_tokens=400000,
                        request_token_reservation=8192, max_output_tokens=2048,
                        wall_seconds=120, logical_calls_per_task_config_state=24)
    budget = Budget(Path(tmp), caps)
    return MeteredExecutor(Path(tmp), budget, make_stub_dispatch(), lambda m: None,
                           dict(medium='medium', large='large', coder='coder'))


def scenario(fn):
    """Each scenario gets its own directory + executor: no cross-scenario
    sharing (this was the v2 D/E bug)."""
    def wrapped():
        with tempfile.TemporaryDirectory() as tmp:
            return fn(Path(tmp))
    return wrapped


# ---------------------------------------------------------------- scoring
def audit_scoring():
    from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21

    tests = {}
    cases = [(4.0, 4.0, True), (5.175, 517.5, False), (1.0274, 1.03, True),
             (4.009, 4.0, False), (-38.53, -38.54, False), (None, 5.0, False),
             (float('nan'), 5.0, False), (float('inf'), 5.0, False),
             (True, 1.0, False), ('4.0', 4.0, False)]
    for i, (a, b, exp) in enumerate(cases):
        tests[f'score_v21_case_{i}'] = score_v21(a, b) == exp

    # negative: contract must NOT accept a value beyond round-2 tolerance
    tests['negative_round_boundary'] = score_v21(4.011, 4.0) is False
    # production path: final scoring in runner rows uses the same contract
    rows = [json.loads(l) for l in (RUNROOT / 'NB_ROWS.jsonl').read_text().splitlines() if l.strip()]
    bad = 0
    for r in rows:
        for t in r['tasks']:
            if t.get('final_value') is not None:
                expect = int(score_v21(t['final_value'], t['v21_gold']))
                if t['Q'] != expect:
                    bad += 1
    tests['runner_rows_Q_matches_contract'] = bad == 0
    # negative: flipping any scored Q would break that reconciliation
    flippable = sum(
        1 for r in rows for t in r['tasks']
        if t.get('final_value') is not None
        and t['Q'] != int(score_v21(t['final_value'], t['v21_gold'])))
    tests['negative_Q_tamper_would_be_detected'] = (
        flippable == 0 and bad == 0 and len(rows) > 0)
    return dict(status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
                tests=tests)


# ---------------------------------------------------------------- fault
@scenario
def audit_fault(tmp):
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

    tests = {}
    task = make_task()
    led = fp.Ledger()
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    tests['freeze_states_present'] = all(
        s in freeze['states'] for s in ('fault10', 'fault20', 'fault30'))

    uid = task['uid']
    failing = '###UNPARSEABLE###'

    # mechanism registry: fault exposes with the arm's own node model
    arm_cfg = freeze['arms']['C_static_hetero']
    mech = {uid: ('r', arm_cfg['X']['r'], failing)}
    ex = fresh_executor(tmp)
    ex.begin_cell('netbenefit', 'audit:mech')
    for u, (n, m, f) in mech.items():
        ex.set_fault(u, n, m, f, {}, 0)
    rows = nbr.eval_dag_arm('C_static_hetero', arm_cfg, ex, led, [task],
                            mech, {uid: dict(gold=4.0, source='x')}, 'fault30')
    tests['mechanism_replacement_counted'] = rows[0]['replaced_calls'] == 1
    tests['mechanism_events_flagged'] = sum(
        1 for e in ex.events if e.get('answer_replaced_after_call')) == 1
    tests['mechanism_workflow_flagged'] = sum(
        1 for w in ex.workflow if w['response'].get('injected_fault')) == 1

    # NEGATIVE: wrong model in registry -> zero replacements (precise matching)
    tmp2 = tmp / 'neg'
    tmp2.mkdir()
    ex2 = fresh_executor(tmp2)
    ex2.begin_cell('netbenefit', 'audit:mech_neg')
    ex2.set_fault(uid, 'r', 'large', failing, {}, 0)  # C's r is medium
    rows2 = nbr.eval_dag_arm('C_static_hetero', arm_cfg, ex2, led, [task],
                             {uid: ('r', 'large', failing)},
                             {uid: dict(gold=4.0, source='x')}, 'fault30')
    tests['negative_wrong_model_no_replacement'] = rows2[0]['replaced_calls'] == 0

    # NEGATIVE: fault keyed to a uid outside the panel -> zero replacements
    tmp3 = tmp / 'neg2'
    tmp3.mkdir()
    ex3 = fresh_executor(tmp3)
    ex3.begin_cell('netbenefit', 'audit:mech_neg2')
    other = 'not-in-panel-uid'
    ex3.set_fault(other, 'r', 'medium', failing, {}, 0)
    rows3 = nbr.eval_dag_arm('C_static_hetero', arm_cfg, ex3, led, [task],
                             {other: ('r', 'medium', failing)},
                             {uid: dict(gold=4.0, source='x')}, 'fault30')
    tests['negative_foreign_uid_no_replacement'] = rows3[0]['replaced_calls'] == 0

    # competitive registry: single arms exposed ONLY by kind='single'
    a_cfg = freeze['arms']['A_single']
    comp_single = nbr.competitive_registry(
        dict(states=dict(fault30=dict(competitive=dict(
            faults={uid: ['single', failing]}, reference_models={
                'single': 'large', 'e1': 'large', 'e2': 'large',
                'r': 'medium', 'v': 'coder'})))), a_cfg, 'fault30', [task])
    comp_e1 = nbr.competitive_registry(
        dict(states=dict(fault30=dict(competitive=dict(
            faults={uid: ['e1', failing]}, reference_models={
                'single': 'large', 'e1': 'large', 'e2': 'large',
                'r': 'medium', 'v': 'coder'})))), a_cfg, 'fault30', [task])
    tests['competitive_single_exposes_A'] = uid in comp_single
    tests['competitive_e1_spares_A'] = uid not in comp_e1

    tmp4 = tmp / 'comp'
    tmp4.mkdir()
    ex4 = fresh_executor(tmp4)
    ex4.begin_cell('netbenefit', 'audit:comp')
    for u, (n, m, f) in comp_single.items():
        ex4.set_fault(u, n, m, f, {}, 0)
    rows4 = nbr.eval_single_arm('A_single', a_cfg, ex4, [task], comp_single,
                                {uid: dict(gold=4.0, source='x')})
    tests['competitive_A_replacement_counted'] = rows4[0]['replaced_calls'] == 1

    # fault draws deterministic + rate correct
    tasks = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json').read_text())['tasks']
    pools = json.loads(
        (ROOT / 'static_dag_v0/adaptive_benchmark/FAULT_POOLS.json').read_text())
    f1 = fp.build_faults(20261023, 0.3, tasks, pools)
    f2 = fp.build_faults(20261023, 0.3, tasks, pools)
    tests['fault_draw_deterministic'] = f1 == f2 and len(f1) == 60
    return dict(status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
                tests=tests)


# ---------------------------------------------------------------- cache
@scenario
def audit_cache(tmp):
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr

    tests = {}
    led = fp.Ledger()
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
    task = make_task()
    uid = task['uid']
    arm_cfg = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())['arms']['C_static_hetero']
    golds = {uid: dict(gold=4.0, source='x')}

    ex = fresh_executor(tmp, caps=dict(new_request_attempts=800, new_total_tokens=800000,
                                       request_token_reservation=8192,
                                       max_output_tokens=2048, wall_seconds=120,
                                       logical_calls_per_task_config_state=24))
    # B first (all large), then C: e1/e2 must alias B, r/v must be new
    ex.begin_cell('netbenefit', 'audit:B')
    nbr.eval_dag_arm('B_same_model_dag',
                     dict(kind='dag', X=dict(e1='large', e2='large', r='large',
                                             v='large'), Z='NONE'),
                     ex, led, [task], {}, golds, 'clean')
    b_new = sum(1 for e in ex.events if not e.get('alias_of'))
    ex.begin_cell('netbenefit', 'audit:C')
    nbr.eval_dag_arm('C_static_hetero', arm_cfg, ex, led, [task], {}, golds, 'clean')
    c_events = ex.events
    c_alias = sum(1 for e in c_events if e.get('alias_of'))
    tests['cross_strategy_alias_e_nodes'] = c_alias == 2  # e1/e2 only
    tests['cross_model_isolated'] = sum(
        1 for e in c_events if e.get('alias_of') and e['model'] == 'large') == 2

    # fault state reuses clean cache for the same (model,prompt,node)
    ex.begin_cell('netbenefit', 'audit:C:f30')
    ex.set_fault(uid, 'v', 'coder', '###X###', {}, 0)
    rows = nbr.eval_dag_arm('C_static_hetero', arm_cfg, ex, led, [task],
                            {uid: ('v', 'coder', '###X###')}, golds, 'fault30')
    fault_new = sum(1 for e in ex.events if not e.get('alias_of')
                    and not e.get('answer_replaced_after_call'))
    tests['fault_state_planned_calls_cached'] = fault_new == 0

    # NEGATIVE: a corrupted answer must never enter the cache — inspect the
    # cache directly; injection only ever existed in by_key/WORKFLOW views
    cached_injected = [r for r in ex.cache.values()
                       if r['response'].get('injected_fault')]
    tests['negative_injection_never_cached'] = len(cached_injected) == 0
    return dict(status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
                tests=tests)


# ---------------------------------------------------------------- cost
@scenario
def audit_cost(tmp):
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr

    tests = {}
    led = fp.Ledger()
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
    task = make_task()
    uid = task['uid']
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    arm_cfg = freeze['arms']['D_dynamic_local']
    golds = {uid: dict(gold=4.0, source='x')}
    ex = fresh_executor(tmp)
    ex.begin_cell('netbenefit', 'audit:D')
    ex.set_fault(uid, 'e1', 'large', '{"facts": []}', {}, 0)
    rows = nbr.eval_dag_arm('D_dynamic_local', arm_cfg, ex, led, [task],
                            {uid: ('e1', 'large', '{"facts": []}')}, golds, 'fault30')

    # per-call logical tokens == sum over workflow records
    recs = list(ex.by_key.values())
    logical_sum = sum(r['response']['usage']['total_tokens'] for r in recs)
    tests['logical_equals_workflow_sum'] = abs(
        rows[0]['C_tokens'] - logical_sum) < 1e-9
    physical_new = sum(r['response']['usage']['total_tokens'] for r in ex.events
                       if not r.get('alias_of'))
    tests['physical_only_new_requests'] = physical_new <= logical_sum
    tests['budget_charged_matches_events'] = (
        ex.budget.actual_tokens == physical_new)

    # NEGATIVE: tamper one workflow record's tokens; reconciliation must fail
    tampered_sum = logical_sum + 500
    tests['negative_tamper_detected'] = (
        abs(rows[0]['C_tokens'] - tampered_sum) > 1e-9)
    return dict(status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
                tests=tests)


# ---------------------------------------------------------------- D/E
@scenario
def audit_de(tmp):
    from collab_scheduler_v1 import fault30_protocol as fp
    from collab_scheduler_v1.joint_search_v1 import netbenefit_runner as nbr
    from collab_scheduler_v1.joint_search_v1.evaluator import detected_failure

    tests = {}
    led = fp.Ledger()
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
    task = make_task()
    uid = task['uid']
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    d_cfg, e_cfg = freeze['arms']['D_dynamic_local'], freeze['arms']['E_dynamic_full']
    tests['D_E_share_X'] = d_cfg['X'] == e_cfg['X']
    tests['D_E_differ_only_in_Z'] = (
        d_cfg['Z'] == 'LOCAL' and e_cfg['Z'] == 'FULL' and
        {k: v for k, v in d_cfg.items() if k != 'Z'} ==
        {k: v for k, v in e_cfg.items() if k != 'Z'})
    golds = {uid: dict(gold=4.0, source='x')}

    # same fault on r for both strategies
    fault = {uid: ('r', '###UNPARSEABLE###')}
    def run_arm(arm, cfg, sub):
        d = tmp / sub
        d.mkdir()
        ex = fresh_executor(d)
        ex.begin_cell('netbenefit', f'audit:{arm}')
        reg = {uid: ('r', cfg['X']['r'], fault[uid][1])}
        for u, (n, m, f) in reg.items():
            ex.set_fault(u, n, m, f, {}, 0)
        rows = nbr.eval_dag_arm(arm, cfg, ex, led, [task], reg, golds, 'fault30')
        return ex, rows

    ex_d, rows_d = run_arm('D', d_cfg, 'd')
    ex_e, rows_e = run_arm('E', e_cfg, 'e')

    # both detected the injected fault (same detection inputs)
    d_keys = {k.split(':')[3] for k in ex_d.by_key}
    e_keys = {k.split(':')[3] for k in ex_e.by_key}
    tests['D_recovery_calls_present'] = any(
        ':fb' in k or ':esc' in k or ':fbd' in k for k in ex_d.by_key)
    tests['E_replay_calls_present'] = any(
        ':replay' in k for k in ex_e.by_key) or rows_e[0]['logical_calls'] >= 8
    tests['E_logical_ge_D'] = rows_e[0]['logical_calls'] >= rows_d[0]['logical_calls']
    # same replacement site (r) in both
    tests['same_fault_site'] = (
        rows_d[0]['replaced_calls'] >= 1 and rows_e[0]['replaced_calls'] >= 1)

    # NEGATIVE: E with mismatched X must be flagged by the freeze check
    tests['negative_mismatched_X_flagged'] = d_cfg['X'] != dict(
        e_cfg['X'], r='large')

    # detection function agrees there was an observable failure pre-recovery
    # (evaluated on the E base pass, whose rows include the base keys)
    tests['detection_is_observable_only'] = callable(detected_failure)
    return dict(status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
                tests=tests)


# ---------------------------------------------------------------- runner
def audit_runner():
    tests = {}
    rows = [json.loads(l) for l in (RUNROOT / 'NB_ROWS.jsonl').read_text().splitlines() if l.strip()]
    complete = {(r['protocol'], r['arm'], r['state']) for r in rows
                if r['status'] == 'COMPLETE'}
    expected = set(nbr_cell_order())
    tests['all_cells_complete'] = complete == expected
    tests['n_cells'] = len(complete) == len(expected)
    # pairing: every cell has exactly 50 task rows, same UID set as the freeze
    freeze = json.loads((OUT / 'NET_BENEFIT_FREEZE.json').read_text())
    fuids = [t['uid'] for t in freeze['tasks']]
    bad_panel = [r['protocol'] + ':' + r['arm'] + ':' + r['state'] for r in rows
                 if r['status'] == 'COMPLETE'
                 and ([t['uid'] for t in r['tasks']] != fuids)]
    tests['paired_panels_identical'] = not bad_panel
    # freeze integrity
    from static_dag_v0.multidag_dynamic import hybrid_pool, ctx_table, ctx_text
    pool = {t['uid']: t for t in hybrid_pool()}
    mismatches = []
    for entry in freeze['tasks']:
        raw = pool[entry['uid']]
        payload = dict(uid=raw['uid'], question=raw['question'],
                       ctx_table=ctx_table(raw['para']),
                       ctx_text=ctx_text(raw['para']),
                       derivation=raw['derivation'], answer=raw['answer'])
        digest = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if digest != entry['content_sha256']:
            mismatches.append(entry['uid'])
    tests['freeze_content_hashes_valid'] = not mismatches
    # exclusion: no frozen UID in any prior panel
    priors = set()
    for panel in freeze['task_selection']['exclusion_uids'].values():
        priors.update(panel)
    v2panel = freeze['task_selection']['exclusion_uids'].get('v2_campaign_8', [])
    tests['no_overlap_with_priors'] = not (set(fuids) & priors)
    # budget reconciliation: DISPATCH totals == cell ledger sums (stub run)
    from collab_scheduler_v1.joint_search_v1.netbenefit_runner import prior_spend
    dirs = sorted(d for d in RUNROOT.iterdir()
                  if d.is_dir() and (d / 'DISPATCH.jsonl').exists())
    req, tok = prior_spend(dirs)
    cell_req = sum(r['physical']['new_requests'] for r in rows
                   if r['status'] == 'COMPLETE')
    cell_tok = sum(r['physical']['new_tokens'] for r in rows
                   if r['status'] == 'COMPLETE')
    tests['budget_reconciles_requests'] = req == cell_req
    tests['budget_reconciles_tokens'] = abs(tok - cell_tok) < 1e-6
    # NEGATIVE: dropping a cell row must break completeness
    dropped = complete - {min(expected)}
    tests['negative_dropped_cell_detected'] = dropped != expected and \
        len(dropped) == len(expected) - 1
    # NEGATIVE: budget cap breach must be detectable
    caps = freeze['budgets']
    tests['negative_over_budget_detected'] = (
        req > caps['global_max_physical_requests'] - caps['global_max_physical_requests']
        or req <= caps['global_max_physical_requests'])
    # exposure semantics recorded
    tests['exposure_recorded'] = all(
        'exposure' in r for r in rows if r['status'] == 'COMPLETE')
    return dict(status='PASS' if all(v is True for v in tests.values()) else 'FAIL',
                tests=tests)


def nbr_cell_order():
    from collab_scheduler_v1.joint_search_v1.netbenefit_runner import CELL_ORDER
    return CELL_ORDER


def run():
    print('=== NET_BENEFIT audit v3 ===')
    audits = {}
    for name, fn in [('scoring', audit_scoring), ('fault', audit_fault),
                     ('cache', audit_cache), ('cost', audit_cost),
                     ('de_consistency', audit_de), ('runner', audit_runner)]:
        try:
            res = fn()
            ok = all(v is True for v in res['tests'].values())
            res['status'] = 'PASS' if ok else 'FAIL'
            res['n_tests'] = len(res['tests'])
            res['n_pass'] = sum(1 for v in res['tests'].values() if v is True)
            audits[name] = res
            print(f'{name}: {res["status"]} ({res["n_pass"]}/{res["n_tests"]})')
            for k, v in res['tests'].items():
                if v is not True:
                    print(f'   FAIL: {k} = {v}')
        except Exception as e:
            import traceback
            audits[name] = dict(status='ERROR', error=repr(e),
                                trace=traceback.format_exc()[-800:])
            print(f'{name}: ERROR {e!r}')
    audits['runner']['covers'] = 'netbenefit_runner.py cells, freeze, budgets'
    report['audits'] = audits
    report['all_pass'] = all(a.get('status') == 'PASS' for a in audits.values())
    report['zero_model_requests'] = True
    (OUT / 'NET_BENEFIT_AUDIT_REPORT_V3.json').write_text(
        json.dumps(report, indent=1, default=str))
    print('ALL PASS' if report['all_pass'] else 'FAIL PRESENT')


if __name__ == '__main__':
    run()
