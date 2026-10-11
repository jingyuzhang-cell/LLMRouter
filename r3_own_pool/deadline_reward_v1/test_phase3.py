"""Phase-3 zero-call consistency audit — prediction vs execution vs
settlement under ONE semantics. Zero real model calls.

Audit items (operator instruction):
  1. FULL (E-arm) prediction–execution consistency: a FULL-WINS scenario,
     reconciling predicted vs actual physical requests, tokens, switches,
     execution order, and the recovery outcome. FULL must never be
     predicted as ordinary cache reuse (the 7459698 defect, reproduced in
     PHASE3_AUDIT_REPORT).
  2. Deadline-probability correctness: nonzero switch time shifts mean AND
     p90 together; p90 < mean anomaly handled; both aggregation modes
     (conservative quantile_sum default, exact independent-normal
     variance) implemented and tested; V1/V8/V9/V10 goldens preserved.
  3. Reward consistency: expected lateness normalized by the frozen task
     duration D (same denominator as settlement); four settlement cases
     (correct+on-time / wrong / timeout / EARLY_STOP) and the fixed
     session_terminal condition.
  4. Cross-task causality: shared budget cannot be double-promised
     (commitment accounting); recovery-then-new-fault re-decides correctly;
     E2E from release per task.
Run: python3 -m deadline_reward_v1.test_phase3  (any CWD)
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import socket as _socket_mod
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import policy  # noqa: E402
from deadline_reward_v1.compensator import DeadlineCompensator  # noqa: E402
from deadline_reward_v1.predictor import OutcomePredictor, e1_on_time  # noqa: E402
from deadline_reward_v1.reward import expected_rtask  # noqa: E402
from deadline_reward_v1.scheduler_state import SchedulerState  # noqa: E402
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
BASE_PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'p3_runs'
NODES_MODELS = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
GOOD_E1 = '{"facts": [{"value": 1.5, "evidence": "a"}]}'
GOOD_E2 = '{"facts": [{"value": 2.5, "evidence": "b"}]}'
GOOD_R = '{"expression": "v0+v1"}'
GOOD_V = '{"value": 4.0}'
BASE_ANSWERS = {('e1', 'plain'): GOOD_E1, ('e2', 'plain'): GOOD_E2,
                ('r', 'plain'): GOOD_R, ('v', 'plain'): GOOD_V,
                ('e1', 'fb'): GOOD_E1, ('e2', 'fb'): GOOD_E2,
                ('e1', 'fbd'): GOOD_E1, ('e2', 'fbd'): GOOD_E2,
                ('r', 'fbd'): GOOD_R, ('r', 'esc'): GOOD_R,
                ('v', 'fbd'): GOOD_V, ('v', 'esc'): GOOD_V}


def task(i, a=1.5, b=2.5):
    return dict(uid=f'pt{i}', question=f'What is {a} + {b}?',
                derivation=f'{a}+{b}', answer=a + b,
                ctx_table=f'TABLE: | val | {a} |',
                ctx_text=f'PASSAGES: value is {b}')


def run(dirname, tasks, *, priors, deadline, q_min=0.80, eps=0.10,
        lam_c=0.5, token_alloc=4000.0, faults=(), engine_profile='golden_zero'):
    server = StubModelServer(dict(BASE_ANSWERS), priors, seed='p3')
    for uid, node, model, failing in faults:
        server.set_fault(uid, node, model, failing)
    clock = InjectedClock()
    engine = StubEngine(RUNS_DIR / dirname, server, clock, seed='p3',
                        profile_key=engine_profile)
    state = SchedulerState(
        clock, task_deadlines={t['uid']: deadline for t in tasks},
        token_allocation=token_alloc)
    state.attach(engine)
    params = dict(priors=priors, q_min=q_min, eps=eps, lam_c=lam_c,
                  lam_t=1.0, lam_f=2.0, c0=4000.0, session_bonus=1.0,
                  session_penalty=2.0)
    result = policy.run_episode(engine, state, tasks, NODES_MODELS, params)
    events, torn = load_ledger(RUNS_DIR / dirname / 'TASK_LEDGER.jsonl')
    return dict(engine=engine, state=state, events=events, torn=torn,
                result=result, decisions=[e for e in events
                                          if e['event'] == 'decision'],
                server=server, tasks=tasks)


def full_wins_priors():
    """q_observed_done=0.70 makes every LOCAL variant (e2 stays reused)
    quality-infeasible, while FULL (all-fresh, min q .85) passes — and
    node token profiles equal the engine's 100/call so predicted and
    actual ledgers reconcile exactly."""
    priors = copy.deepcopy(BASE_PRIORS)
    priors['policy'] = dict(priors['policy'], q_observed_done=0.70)
    for k, v in priors['node_profiles'].items():
        v['tokens_p90'] = 100
    return priors


@contextlib.contextmanager
def no_socket():
    def _raise(*_a, **_k):
        raise AssertionError('network access attempted (Z2)')
    saved = _socket_mod.socket
    _socket_mod.socket = _raise
    try:
        yield
    finally:
        _socket_mod.socket = saved


def main():
    import shutil
    shutil.rmtree(RUNS_DIR, ignore_errors=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    checks = {}
    recon = {}

    # ============ 1. FULL prediction–execution–settlement ==============
    r1 = run('full_wins', [task(0)], priors=full_wins_priors(),
             deadline=60.0,
             faults=[('pt0', 'e1', 'large', '{"facts": []}')])
    d1 = next(e for e in r1['decisions'] if e['stage'] == 'post_R1')
    # after the M5 static/dynamic FULL split, the legitimate winner of
    # this scenario is the DYNAMIC full-graph arm (it may upgrade the
    # planned coder v to large); the scenario's intent — a full-graph
    # plan beats every LOCAL because LOCAL reuses e2 at q_obs=0.70 — is
    # unchanged; the reconciliation follows the CHOSEN arm.
    chosen_arm = d1['chosen']['arm']
    assert chosen_arm in ('FULL', 'FULL_DYNAMIC')
    full_row = next(r for r in d1['table']
                    if r['arm'] == chosen_arm and r['feasible']
                    and r['pi'] == d1['chosen']['pi'])
    checks['p3_1_full_wins'] = (
        chosen_arm in ('FULL', 'FULL_DYNAMIC')
        and all(r['arm'] != 'LOCAL' or not r['feasible']
                for r in d1['table'])
        and full_row['q'] == 0.95)
    local_max_dcost = max(r['dcost'] for r in d1['table']
                          if r['arm'] == 'LOCAL')
    # uniform 100-token profiles make dcost a call-count proxy: FULL must
    # predict FOUR charged calls vs LOCAL's max three (the 7459698 defect
    # had FULL == LOCAL, i.e. replay predicted as cache reuse)
    checks['p3_1_full_not_predicted_as_cache'] = (
        full_row['dcost'] == 400.0 and local_max_dcost == 300.0)
    # reconcile predicted vs ACTUAL over ALL post-decision physical calls
    # of this task (the FULL execute set includes PENDING v, which runs in
    # its planned V1 stage under the chosen pi — never duplicated)
    dec_idx = next(i for i, e in enumerate(r1['events'])
                   if e['event'] == 'decision' and e['stage'] == 'post_R1')
    plan_calls = [e for e in r1['events'][dec_idx:]
                  if e['event'] == 'call' and e['task'] == 'pt0'
                  and (str(e.get('stage', '')).startswith('plan:')
                       or e.get('stage') == 'V1')]
    sw_idx = {c['switch_before'] for c in plan_calls} - {None}
    plan_sw = [e for e in r1['events'] if e['event'] == 'switch'
               and e['idx'] in sw_idx]
    actual_tokens = sum(c['usage']['total_tokens'] for c in plan_calls
                        if c['physical'])
    actual_sw = sum(e['wall_s'] for e in plan_sw)
    service_p90 = sum(
        full_wins_priors()['node_profiles'][
            f"{n}|{d1['chosen']['pi'][n]}"]['lat_p90_s']
        for n in ('e1', 'e2', 'r', 'v'))
    checks['p3_1_tokens_reconcile'] = (
        full_row['dcost'] == actual_tokens == 400.0
        and all(c['physical'] and not c['cached'] for c in plan_calls))
    phys = [c for c in plan_calls if c['physical']]
    checks['p3_1_requests_reconcile'] = (
        len(phys) == 4
        and [c['node'] for c in phys] == ['e1', 'e2', 'r', 'v']
        and [c['model'] for c in phys] == [
            d1['chosen']['pi'][n] for n in ('e1', 'e2', 'r', 'v')])
    # switch semantics after the boundary errata: the row's switch is a
    # PROVEN per-call upper bound (interleaving can force a re-switch
    # before every call), so reconciliation asserts BOUND >= actual and
    # the internal identity p90 == service_p90 + switch(+contention==0
    # here: single-task world) — tokens/requests still reconcile exactly.
    checks['p3_1_switch_reconcile'] = (
        full_row['switch'] >= actual_sw
        and abs(full_row['p90']
                - (service_p90 + full_row['switch'])) < 1e-9)
    st1 = r1['result']['settlement']['rewards'][0]
    checks['p3_1_settlement'] = (
        st1['q'] == 1.0 and not st1['degraded']
        and st1['c_full'] == 700  # 3 planned + 4 full-graph calls x 100
        and r1['result']['settlement']['session_terminal'] == 1.0)
    recon['full_wins'] = dict(predicted=full_row,
                              actual_tokens=actual_tokens,
                              actual_requests=len(phys),
                              actual_switch=actual_sw,
                              order=[c['node'] for c in phys])

    # ============ 2. p90/switch sync + anomaly + aggregation ============
    # nonzero-switch run: p90 must equal service p90 + switch (V10-style)
    real = copy.deepcopy(BASE_PRIORS)
    r2 = run('p90_sync', [task(0)], priors=real, deadline=60.0,
             faults=[('pt0', 'r', 'medium', '###BROKEN###')],
             engine_profile='v3_compat')
    d2 = next(e for e in r2['decisions'] if e['stage'] == 'post_R1')
    row2 = next(r for r in d2['table']
                if r['arm'] == 'LOCAL' and r['pi'].get('v') == 'coder'
                and r['pi'].get('r') == 'large')
    svc_p90 = (real['node_profiles']['r|large']['lat_p90_s']
               + real['node_profiles']['v|coder']['lat_p90_s'])
    checks['p3_2_p90_shifted_with_switch'] = (
        abs(row2['p90'] - (svc_p90 + row2['switch'])) < 1e-9
        and row2['p90'] >= row2['mu_e2e'])  # no degenerate sigma path
    # boundary task 4 updated semantics: p90 < mean is an ILLEGAL normal
    # profile — rejected at episode start with a named error (never a
    # silent point-mass for formal feasibility). The LEGAL zero-variance
    # limit (p90 == mean) still yields exact point-mass rows.
    weird = full_wins_priors()
    weird['node_profiles']['v|large'].update(lat_mean_s=10.0,
                                             lat_p90_s=5.0)
    try:
        run('p90_illegal', [task(0)], priors=weird, deadline=60.0,
            faults=[('pt0', 'r', 'medium', '###BROKEN###')])
        checks['p3_2_anomaly_point_mass'] = False
    except ValueError as exc:
        checks['p3_2_anomaly_point_mass'] = 'v|large' in str(exc)
    zero_var = full_wins_priors()
    zero_var['node_profiles']['v|large'].update(lat_mean_s=10.0,
                                                lat_p90_s=10.0)
    r2b = run('p90_zero_var', [task(0)], priors=zero_var, deadline=60.0,
              faults=[('pt0', 'r', 'medium', '###BROKEN###')])
    d2b = next(e for e in r2b['decisions'] if e['stage'] == 'post_R1')
    zv_rows = [r for r in d2b['table'] if r['pi'].get('v') == 'large'
               and r['arm'] == 'LOCAL']
    checks['p3_2_zero_variance_point_mass'] = (
        len(zv_rows) > 0
        and all(r['p_on_time'] in (0.0, 1.0) for r in zv_rows))
    # aggregation modes, tested on the predictor directly
    pred = OutcomePredictor(BASE_PRIORS)
    ex = [('r', True), ('v', True)]
    pi = {'r': 'large', 'v': 'coder'}
    nm = dict(NODES_MODELS)
    nstat = {n: 'PENDING' for n in NODES_MODELS}
    p_qs = pred.predict(execute=ex, pi=pi, node_model=nm, node_status=nstat)
    var_priors = copy.deepcopy(BASE_PRIORS)
    var_priors['policy'] = dict(var_priors['policy'],
                                p90_aggregation='variance')
    p_va = OutcomePredictor(var_priors).predict(execute=ex, pi=pi,
                                                node_model=nm,
                                                node_status=nstat)
    s_r = (10.5 - 10.0) / 1.2816
    s_v = (7.5 - 7.0) / 1.2816
    var_p90 = 17.0 + 1.2816 * math.sqrt(s_r ** 2 + s_v ** 2)
    checks['p3_2_aggregation_modes'] = (
        abs(p_qs.w_p90_s - 18.0) < 1e-9
        and abs(p_va.w_p90_s - var_p90) < 1e-9
        and p_qs.w_p90_s >= p_va.w_p90_s)  # quantile_sum is conservative

    # ============ 3. reward consistency =================================
    # expected lateness normalized by D_total (60), not d_remain (17.5)
    p_on, e_late = e1_on_time(17.0, 18.0, 17.5)
    score_d_total = expected_rtask(q_hat=0.85, d_cost=900.0,
                                   p_on_time=p_on, e_late=e_late,
                                   d_total=60.0, lam_c=0.5, lam_t=1.0,
                                   lam_f=2.0, c0=4000.0)
    manual = (p_on * 0.85 - 0.5 * 900 / 4000 - 1.0 * e_late / 60.0
              - 2.0 * (1 - p_on))
    checks['p3_3_expected_uses_D_total'] = (
        abs(score_d_total - manual) < 1e-12
        and abs(score_d_total
                - (p_on * 0.85 - 0.5 * 900 / 4000 - 1.0 * e_late / 60.0
                   - 2.0 * (1 - p_on))) < 1e-12)
    # four settlement cases via settle() on crafted states
    cases = {}

    def settle_case(name, *, v_answer, task_answer, completion, deadline_abs,
                    release=0.0, degraded=False):
        st = SchedulerState(InjectedClock(),
                            task_deadlines={'x': deadline_abs},
                            token_allocation=4000.0)
        ts = _mk_task_state()
        st.tasks['x'] = ts
        ts.release_time = release
        ts.completion_time = completion
        ts.answers['v'] = v_answer
        ts.tokens_physical = 500.0
        ts.degraded = degraded
        t = dict(uid='x', answer=task_answer)
        eng = _FakeEngine(RUNS_DIR / f'settle_{name}')
        rec = policy.reward_mod.settle(
            eng, st, [t], lam_c=0.5, lam_t=1.0, lam_f=2.0, c0=4000.0)
        cases[name] = rec['rewards'][0]
        return rec['rewards'][0]

    ok = settle_case('ok', v_answer=GOOD_V, task_answer=4.0,
                     completion=18.0, deadline_abs=20.0)
    wrong = settle_case('wrong', v_answer=GOOD_V, task_answer=999.0,
                        completion=18.0, deadline_abs=20.0)
    late = settle_case('late', v_answer=GOOD_V, task_answer=4.0,
                       completion=22.0, deadline_abs=20.0)
    stop = settle_case('stop', v_answer='', task_answer=4.0,
                       completion=15.0, deadline_abs=20.0, degraded=True)
    checks['p3_3_settlement_cases'] = (
        ok['q'] == 1.0 and ok['r_task'] > 0
        and wrong['q'] == 0.0 and wrong['r_task'] < 0
        and late['q'] == 1.0
        and abs(late['r_task'] - (0.0 - 0.0625 - 0.1 - 2.0)) < 1e-9
        and stop['degraded'] and stop['q'] == 0.0)
    # session terminal: read the settlement records' session_terminal
    def term_of(name):
        recs = (RUNS_DIR / f'settle_{name}' / 'REWARDS.jsonl').read_text()
        return json.loads(recs.splitlines()[-1])['session_terminal']
    checks['p3_3_session_terminal_fixed'] = (
        term_of('ok') == 1.0
        and term_of('wrong') == -2.0 and term_of('late') == -2.0
        and term_of('stop') == -2.0)

    # ============ 4. cross-task commitment + re-fault ===================
    golden = copy.deepcopy(BASE_PRIORS)      # REAL token profiles (900+)
    golden['policy'] = dict(golden['policy'], q_observed_done=1.0)
    golden['switch'] = {"family": "deterministic", "stop_s": 0.0,
                        "start_s": {"medium": 0.0, "large": 0.0,
                                    "coder": 0.0}, "synthetic": True}
    tasks4 = [task(0), task(1)]
    r4 = run('commit', tasks4, priors=golden, deadline=60.0,
             token_alloc=1500.0,
             faults=[('pt0', 'r', 'medium', '###BROKEN###'),
                     ('pt1', 'r', 'medium', '###BROKEN###')])
    dec = {e['task']: e for e in r4['decisions']}
    pt0_dcost = dec['pt0']['chosen']['score'] and next(
        r['dcost'] for r in dec['pt0']['table']
        if r['arm'] == dec['pt0']['chosen']['arm']
        and r['pi'] == dec['pt0']['chosen']['pi'])
    checks['p3_4_no_double_promise'] = (
        dec['pt0']['chosen'] is not None and pt0_dcost >= 900
        and dec['pt1']['degraded'] is True
        and any(v['constraint'] == 'budget'
                for vv in dec['pt1']['violations'] for v in vv['deficits'])
        and dec['pt1']['b_remain_tokens'] < 900.0)
    rewards4 = {r['task']: r for r in r4['result']['settlement']['rewards']}
    # boundary task 1 semantics: the residual reservation is RELEASED at
    # plan end, so at settlement committed == 0 and the conservation
    # invariant holds exactly; pt0's mid-run reservation existed (its
    # amount is visible in pt1's decision b_remain above).
    cons = r4['state'].budget_conservation()
    checks['p3_4_budget_reconciles'] = (
        rewards4['pt0']['q'] == 1.0 and rewards4['pt1']['degraded']
        and cons['spent'] <= r4['state'].token_allocation
        and r4['state'].budget()['committed_tokens'] == 0.0
        and cons['invariant'])
    # re-fault: r fault recovered at post_R1, then v faults at V1 ->
    # post_V1 decision fires and recovers v
    # deadline 22, resident models -> B chosen (v=coder) -> the v fault
    # fires at V1 -> post_V1 decision must recover v on large
    r4b = run('refault', [task(0)], priors=golden, deadline=22.0,
              faults=[('pt0', 'r', 'medium', '###BROKEN###'),
                      ('pt0', 'v', 'coder', '{"value": null}')])
    dv1 = next(e for e in r4b['decisions'] if e['stage'] == 'post_V1')
    v_calls = [e for e in r4b['events'] if e['event'] == 'call'
               and e['node'] == 'v']
    checks['p3_4_refault_redecides'] = (
        dv1['chosen'] is not None and dv1['chosen']['pi']['v'] == 'large'
        and len(v_calls) == 2 and v_calls[-1]['model'] == 'large'
        and v_calls[-1]['kind'] == 'esc'
        and r4b['result']['settlement']['rewards'][0]['q'] == 1.0)
    # E2E per task from release: definition holds exactly on the commit
    # run (zero-time profile => T == 0 is CORRECT there), and is strictly
    # positive on the nonzero-latency run (r2)
    checks['p3_4_e2e_from_release'] = (
        all(r['T'] == round(r4['state'].tasks[r['task']]
                            .completion_time
                            - r4['state'].tasks[r['task']].release_time, 6)
            for r in r4['result']['settlement']['rewards'])
        and r2['result']['settlement']['rewards'][0]['T'] > 0)

    # regression: original goldens preserved (V1/V8/V9/V10 live in
    # test_policy; run asserted separately by the driver)
    checks['p3_5_not_torn'] = not r1['torn'] and not r4['torn']
    checks['p3_5_z1'] = all(
        e['physical'] for e in r1['events'] if e['event'] == 'call'
        and e['stage'] == 'plan:FULL')

    all_pass = all(checks.values())
    evidence = dict(phase='3-audit', checks=checks, all_pass=all_pass,
                    zero_model_calls=True, reconciliation=recon,
                    settlement_cases=cases)
    (HERE / 'evidence' / 'P3_EVIDENCE.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{sum(checks.values())}/{len(checks)} checks; '
          f'zero_model_calls=true; '
          f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')
    return 0 if all_pass else 2


class _FakeEngine:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)


def _mk_task_state():
    from deadline_reward_v1.scheduler_state import _TaskState
    return _TaskState('x')


if __name__ == '__main__':
    with no_socket():
        raise SystemExit(main())
