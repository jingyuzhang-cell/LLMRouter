"""Boundary audit suite (operator phase-3 final boundary instruction).

Four task groups, each with minimal counterexamples pinned by tests:
  T1 budget-reservation ownership (per task / per decision, FIFO drain,
     plan-end release, honest overspend, conservation invariant);
  T2 probability-conservatism applicability (path-p90 upper bound vs
     on-time-probability lower bound; the D < mu counterexample where an
     inflated sigma RAISES the computed probability; row annotation);
  T3 cross-task time contention (conservative shared-work bound enters
     mean AND p90; the solo-approval/actual-late counterexample is now
     rejected; predictions cover actual interleaved execution);
  T4 latency-profile legality (normal p90 < mean REJECTED by name;
     deterministic and zero-variance-normal point masses legal).

Zero real model calls; socket blocked; original six suites unchanged.
Run: python3 -m deadline_reward_v1.test_boundary  (any CWD)
"""
from __future__ import annotations

import contextlib
import copy
import json
import socket as _socket_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import policy  # noqa: E402
from deadline_reward_v1.predictor import (  # noqa: E402
    OutcomePredictor, e1_on_time, validate_node_profiles)
from deadline_reward_v1.scheduler_state import SchedulerState  # noqa: E402
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
BASE_PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'b_runs'
NODES_MODELS = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
GOOD_E1 = '{"facts": [{"value": 1.5, "evidence": "a"}]}'
GOOD_E2 = '{"facts": [{"value": 2.5, "evidence": "b"}]}'
GOOD_R = '{"expression": "v0+v1"}'
GOOD_V = '{"value": 4.0}'
ANSWERS = {('e1', 'plain'): GOOD_E1, ('e2', 'plain'): GOOD_E2,
           ('r', 'plain'): GOOD_R, ('v', 'plain'): GOOD_V,
           ('e1', 'fb'): GOOD_E1, ('e2', 'fb'): GOOD_E2,
           ('e1', 'fbd'): GOOD_E1, ('e2', 'fbd'): GOOD_E2,
           ('r', 'fbd'): GOOD_R, ('r', 'esc'): GOOD_R,
           ('v', 'fbd'): GOOD_V, ('v', 'esc'): GOOD_V}


def task(i):
    return dict(uid=f'bt{i}', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table=f'TABLE: | val | 1.5 |',
                ctx_text=f'PASSAGES: value is 2.5 -{i}')


def run(dirname, tasks, *, priors, deadline, token_alloc=4000.0,
        faults=(), engine_profile='golden_zero', q_min=0.80, eps=0.10):
    server = StubModelServer(dict(ANSWERS), priors, seed='b')
    for uid, node, model, failing in faults:
        server.set_fault(uid, node, model, failing)
    clock = InjectedClock()
    engine = StubEngine(RUNS_DIR / dirname, server, clock, seed='b',
                        profile_key=engine_profile)
    state = SchedulerState(
        clock, task_deadlines={t['uid']: deadline for t in tasks},
        token_allocation=token_alloc)
    state.attach(engine)
    snaps = []

    def probe(ev):
        if ev.get('event') == 'call':
            b = state.budget()
            snaps.append(dict(task=ev['task'], stage=ev.get('stage'),
                              committed=b['committed_tokens'],
                              spent=b['tokens_spent'],
                              available=b['b_remain_tokens'],
                              invariant=(b['tokens_spent']
                                         + b['committed_tokens']
                                         + b['b_remain_tokens']
                                         == state.token_allocation)))
    engine.add_observer(probe)
    params = dict(priors=priors, q_min=q_min, eps=eps, lam_c=0.5,
                  lam_t=1.0, lam_f=2.0, c0=4000.0, session_bonus=1.0,
                  session_penalty=2.0)
    result = policy.run_episode(engine, state, tasks, NODES_MODELS, params)
    events, torn = load_ledger(RUNS_DIR / dirname / 'TASK_LEDGER.jsonl')
    return dict(engine=engine, state=state, events=events, snaps=snaps,
                torn=torn, result=result, server=server, tasks=tasks,
                decisions=[e for e in events if e['event'] == 'decision'])


def zero_switch(priors):
    p = copy.deepcopy(priors)
    p['switch'] = {"family": "deterministic", "stop_s": 0.0,
                   "start_s": {"medium": 0.0, "large": 0.0, "coder": 0.0},
                   "synthetic": True}
    return p


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
    det = {}

    golden = zero_switch(BASE_PRIORS)

    # ================= T1: reservation ownership ========================
    # pt0 r-faulted (decides, reserves 900); pt1 CLEAN (no decision, its
    # V1 call is unreserved). Old global scalar would release pt0's
    # reservation on pt1's call — per-task ledger must not.
    r1 = run('t1_owner', [task(0), task(1)], priors=golden,
             deadline=60.0,
             faults=[('bt0', 'r', 'medium', '###BROKEN###')])
    d0 = next(e for e in r1['decisions'] if e['task'] == 'bt0')
    reserved = next(r['dcost'] for r in d0['table']
                    if r['arm'] == d0['chosen']['arm']
                    and r['pi'] == d0['chosen']['pi'])
    # foreign-call check: committed is IDENTICAL across pt1's unreserved
    # V1 call (compare the snapshots immediately before and at that call;
    # pt0's own plan call has legitimately drained 100 beforehand)
    idx = next(i for i, s in enumerate(r1['snaps'])
               if s['task'] == 'bt1' and s['stage'] == 'V1')
    before, at = r1['snaps'][idx - 1], r1['snaps'][idx]
    checks['t1_foreign_call_no_release'] = (
        before['committed'] == at['committed'] and at['committed'] > 0.0
        and reserved >= 900.0)
    # own plan call drains ONLY own reservation (FIFO), by exactly usage
    pt0_plan = [s for s in r1['snaps'] if s['task'] == 'bt0'
                and str(s['stage']).startswith('plan:')]
    if len(pt0_plan) >= 1:
        first = pt0_plan[0]
        checks['t1_own_call_drains_own'] = (
            first['committed'] == max(0.0, reserved - 100.0))
    else:
        checks['t1_own_call_drains_own'] = False
    # conservation invariant at EVERY snapshot, and residuals released
    checks['t1_conservation_all_snaps'] = all(
        s['invariant'] for s in r1['snaps'])
    final_b = r1['state'].budget()
    checks['t1_plan_end_release'] = (
        final_b['committed_tokens'] == 0.0
        and r1['state'].budget_conservation()['invariant'])

    # overspend honesty: predictor under-charges (tokens_p90=50) while the
    # engine meters 100/call -> reservation drains to 0, excess eats the
    # pool, b_remain goes NEGATIVE, and the post_V1 re-decision must see
    # budget deficits (never a silent top-up)
    cheap = copy.deepcopy(golden)
    for v in cheap['node_profiles'].values():
        v['tokens_p90'] = 50
    # allocation 450: planned 300; tight deadline picks B (v=coder -> the
    # v fault fires); the cheap reservation (100) under-counts the real
    # metering (100/call), the v overspend pushes spend past the
    # allocation, and the post_V1 re-decision must see the honest deficit
    r1b = run('t1_overspend', [task(0)], priors=cheap, deadline=22.0,
              token_alloc=450.0,
              faults=[('bt0', 'r', 'medium', '###BROKEN###'),
                      ('bt0', 'v', 'coder', '{"value": null}')])
    dv1 = [e for e in r1b['decisions'] if e['stage'] == 'post_V1']
    late_b = r1b['state'].budget()
    checks['t1_overspend_honest'] = (
        len(dv1) == 1
        and (dv1[0]['degraded']
             or any(x['constraint'] == 'budget'
                    for vv in dv1[0]['violations'] for x in vv['deficits']))
        and late_b['b_remain_tokens'] < 0.0
        and r1b['state'].budget_conservation()['invariant'])
    det['t1'] = dict(reserved=reserved, final_budget=final_b,
                     overspend_b_remain=late_b['b_remain_tokens'])

    # ================= T2: conservatism applicability ===================
    # reviewer's exact counterexample: mu=20, D=18; sigma 2 vs 3
    p_s2 = e1_on_time(20.0, 20.0 + 1.2816 * 2.0, 18.0)[0]
    p_s3 = e1_on_time(20.0, 20.0 + 1.2816 * 3.0, 18.0)[0]
    checks['t2_d_below_mu_counterexample'] = (
        abs(p_s2 - 0.15866) < 1e-3 and abs(p_s3 - 0.25249) < 1e-3
        and p_s3 > p_s2)   # inflated sigma RAISES the probability here
    # row annotation: D >= mu -> p_conservative True; D < mu -> False
    r2a = run('t2_ge', [task(0)], priors=golden, deadline=60.0,
              faults=[('bt0', 'r', 'medium', '###BROKEN###')])
    rows_a = next(e for e in r2a['decisions'])['table']
    feasible_rows = [r for r in rows_a if r['feasible']]
    checks['t2_annotation_d_ge_mu'] = (
        len(feasible_rows) >= 1
        and all(r['p_conservative'] for r in feasible_rows))
    r2b = run('t2_lt', [task(0)], priors=golden, deadline=14.0,
              faults=[('bt0', 'r', 'medium', '###BROKEN###')])
    rows_b = next(e for e in r2b['decisions'])['table']
    below = [r for r in rows_b if r['mu_e2e'] > 14.0]
    checks['t2_annotation_d_lt_mu'] = (
        len(below) >= 1 and all(not r['p_conservative'] for r in below)
        and next(e for e in r2b['decisions'])['degraded'])
    varp = copy.deepcopy(golden)
    varp['policy'] = dict(varp['policy'], p90_aggregation='variance')
    r2c = run('t2_var', [task(0)], priors=varp, deadline=60.0,
              faults=[('bt0', 'r', 'medium', '###BROKEN###')])
    rows_c = next(e for e in r2c['decisions'])['table']
    checks['t2_variance_mode_annotated_valid'] = (
        all(r['p_conservative'] for r in rows_c if r['feasible']))
    det['t2'] = dict(p_sigma2=p_s2, p_sigma3=p_s3)

    # ================= T3: cross-task contention ========================
    # Task 1 (errata): the flip counterexample must compare SOLO vs
    # CONTENTIOUS predictions AT THE SAME decision-time d_remain (never
    # the initial deadline). Window: d_remain=26.0 -> solo z=+3.20
    # (P=0.9993 >= 0.90) but contention z=-5.77 (P ~ 4e-9 < 0.90), with
    # contention traceable to the co-resident task's priors-derived
    # remaining-work estimate at decision time.
    real = copy.deepcopy(BASE_PRIORS)
    r3 = run('t3_contention', [task(0), task(1)], priors=real,
             deadline=32.7,
             faults=[('bt0', 'r', 'medium', '###BROKEN###')],
             engine_profile='v3_compat')
    d3 = next(e for e in r3['decisions'] if e['task'] == 'bt0')
    d_rem = d3['d_remain']
    b_row = next(r for r in d3['table']
                 if r['arm'] == 'LOCAL' and r['pi'].get('r') == 'large'
                 and r['pi'].get('v') == 'coder')
    cont = b_row['contention']
    solo_p = e1_on_time(b_row['mu_e2e'] - cont,
                        b_row['p90'] - cont, d_rem)[0]
    # traceability: contention == the co-resident task's frozen-prior
    # remaining-work estimate (its planned v mean), set BEFORE the
    # decision from observable state + priors only
    v_mean = float(real['node_profiles']['v|coder']['lat_mean_s'])
    sw_full = (float(real['switch']['stop_s'])
               + float(real['switch']['start_s']['coder']))
    checks['t3_bound_flips_approval'] = (
        abs(d_rem - 26.0) < 0.2            # decision-time remainder used
        and cont > 0.0 and abs(cont - (v_mean + sw_full)) < 1e-9
        and solo_p >= 0.90                 # SOLO at d_rem: would approve
        and b_row['p_on_time'] < 0.90      # WITH contention at the SAME
        and not b_row['feasible']          # d_rem: must not
        and any(x['constraint'] == 'on_time' for x in b_row['deficits']))
    # contention never silent
    checks['t3_field_always_present'] = all(
        'contention' in r for r in d3['table'])
    det['t3'] = dict(d_remain=d_rem, b_row=b_row, solo_p=solo_p,
                     contention_source='v|coder lat_mean + full switch '
                                      'allowance (frozen priors)',
                     degraded=d3['degraded'])

    # ---- Task 2 (errata): NON-VACUOUS coverage across deterministic
    # scripted samples: every sample must contain >=1 CHOSEN cross-task
    # decision whose task REALLY completes; for each, verify decision
    # clock, predicted mu/p90, actual completion, actual elapsed, and
    # that other tasks' calls/switches genuinely interleaved inside the
    # window. This is DETERMINISTIC-SAMPLE COVERAGE — explicitly NOT a
    # general P90 probability guarantee.
    def coverage_sample(name, *, fault_task, engine_profile, priors,
                        deadline=60.0):
        tasks_c = [task(0), task(1)]
        rr = run(name, tasks_c, priors=priors, deadline=deadline,
                 faults=[(f'bt{fault_task}', 'r', 'medium', '###B###')],
                 engine_profile=engine_profile)
        st = rr['state']
        covered = 0
        interleaved = 0
        for e in rr['decisions']:
            if e['chosen'] is None:
                continue
            u = e['task']
            row = next(r for r in e['table']
                       if r['arm'] == e['chosen']['arm']
                       and r['pi'] == e['chosen']['pi'])
            clock_at_dec = deadline - e['d_remain']
            completion = st.tasks[u].completion_time
            assert completion is not None
            actual = completion - clock_at_dec
            if actual > row['p90'] + 1e-6:
                return dict(ok=False, why='actual exceeds p90', e=e)
            covered += 1
            # other-task work inside the decision->completion window
            for c in rr['events']:
                if (c['event'] == 'call' and c['task'] != u
                        and c['physical']
                        and clock_at_dec <= c['t_start'] <= completion):
                    interleaved += 1
        if covered == 0:
            return dict(ok=False, why='no chosen decision (vacuous)')
        if interleaved == 0:
            return dict(ok=False, why='no real interleaving observed')
        return dict(ok=True, covered=covered, interleaved=interleaved)

    # sample A: v3_compat latencies, fault on the FIRST task
    sA = coverage_sample('t3_cov_a', fault_task=0,
                         engine_profile='v3_compat', priors=real)
    # sample B: fault on the SECOND task (different interleaving order)
    sB = coverage_sample('t3_cov_b', fault_task=1,
                         engine_profile='v3_compat', priors=real)
    # sample C: per-node deterministic latencies EQUAL to the priors'
    # means (engine_profile=None -> the server resolves each call by
    # (node|model)) — the tight case where actual service ~= predicted
    tight = copy.deepcopy(real)
    for key, prof in real['node_profiles'].items():
        tight['profiles'][key] = {
            'family': 'deterministic',
            'latency_s': prof['lat_mean_s'], 'total_tokens': 100,
            'synthetic': True}
    sC = coverage_sample('t3_cov_c', fault_task=0,
                         engine_profile=None, priors=tight)
    checks['t3_cover_nonvacuous'] = all(
        s.get('ok') for s in (sA, sB, sC))
    det['t3_coverage'] = dict(A=sA, B=sB, C=sC,
        claim='deterministic-sample coverage only — NOT a general P90 '
              'probability guarantee')

    # ================= T4: profile legality =============================
    bad = copy.deepcopy(golden)
    bad['node_profiles']['v|large'].update(lat_mean_s=9.0, lat_p90_s=8.0)
    try:
        run('t4_illegal', [task(0)], priors=bad, deadline=60.0,
            faults=[('bt0', 'r', 'medium', '###BROKEN###')])
        checks['t4_illegal_profile_rejected'] = False
    except ValueError as exc:
        checks['t4_illegal_profile_rejected'] = ('v|large' in str(exc))
    try:
        validate_node_profiles(golden)
        legal_ok = True
    except ValueError:
        legal_ok = False
    checks['t4_legal_profiles_accepted'] = legal_ok
    det['t4'] = 'see t4_illegal'

    # P3-B fix 1 regression: session_summary.calls == number of call
    # EVENTS (injected/corrupted calls are already inside requests)
    evb = r1['events']
    sess_b = next(e for e in evb if e['event'] == 'session_summary')
    n_events_b = sum(1 for e in evb if e['event'] == 'call')
    n_inj_b = sum(1 for e in evb if e['event'] == 'call' and e.get('injected'))
    n_cached_b = sum(1 for e in evb if e['event'] == 'call'
                     and e.get('cached'))
    checks['p3b_calls_field_conservation'] = (
        sess_b['calls'] == n_events_b
        and n_events_b == sess_b['requests'] + n_cached_b
        and n_inj_b <= sess_b['requests'])
    det['p3b_calls'] = dict(calls_field=sess_b['calls'],
                            call_events=n_events_b, injected=n_inj_b,
                            cached=n_cached_b,
                            requests=sess_b['requests'])

    # ---- P3-B2 (final evidence gap): DETERMINISTIC mixed scenario with
    # physical>0 AND cached>0 AND injected>0 in ONE ledger, with full
    # per-event conservation (the earlier regression had cached=0 and
    # proved only the injected non-double-count).
    from deadline_reward_v1 import reassign as _re
    tmx = dict(uid='mx0', question='q', derivation='d', answer=4.0,
               ctx_table='T', ctx_text='P')
    srv_mx = StubModelServer(dict(ANSWERS), BASE_PRIORS, seed='mx')
    srv_mx.set_fault('mx0', 'r', 'medium', '###BROKEN###')
    # ONE clock shared by engine AND state (the frozen single time
    # authority); the previous version used two independent clocks
    clock_mx = InjectedClock()
    eng_mx = StubEngine(RUNS_DIR / 'mixed', srv_mx, clock_mx,
                        seed='mx', profile_key='v3_compat')
    st_mx = SchedulerState(clock_mx,
                           task_deadlines={'mx0': 100.0},
                           token_allocation=100000.0)
    st_mx.attach(eng_mx)
    eng_mx.start_panel([tmx], NODES_MODELS)
    eng_mx.run_jobs('A', eng_mx.planned_jobs([tmx], NODES_MODELS,
                                             ('e1', 'e2')))
    eng_mx.run_jobs('R1', eng_mx.planned_jobs([tmx], NODES_MODELS,
                                              ('r',)))
    cands_mx = _re.enumerate_candidates(st_mx, 'mx0', NODES_MODELS)
    cand_mx = next(c for c in cands_mx if c.arm == 'FULL_DYNAMIC'
                   and c.pi == dict(e1='large', e2='large', r='large',
                                    v='coder'))
    _re.apply_whole_plan(eng_mx, st_mx, tmx, NODES_MODELS, cand_mx)
    eng_mx.write_task_summaries([tmx])
    eng_mx.write_session_summary(1)
    ev_mx, _ = load_ledger(eng_mx.ledger_path)
    c_mx = [e for e in ev_mx if e['event'] == 'call']
    phys_mx = [c for c in c_mx if c['physical']]
    cached_mx = [c for c in c_mx if c['cached']]
    inj_mx = [c for c in c_mx if c['injected']]
    sess_mx = next(e for e in ev_mx if e['event'] == 'session_summary')
    tok_phys = sum(c['usage']['total_tokens'] for c in phys_mx)
    st_mx_view = st_mx.tasks['mx0']
    checks['p3b2_mixed_scenario_strictly_positive'] = (
        len(phys_mx) > 0 and len(cached_mx) > 0 and len(inj_mx) > 0)
    checks['p3b2_calls_equals_events'] = (
        sess_mx['calls'] == len(c_mx)
        and sess_mx['calls'] == sess_mx['requests'] + sess_mx['cached_calls'])
    # per-event SET containment (not just counts): every injected event
    # IS a physical, non-cached event; physical and cached are mutually
    # exclusive and together cover ALL call events
    inj_ids = {id(c) for c in inj_mx}
    checks['p3b2_field_counts_match_events'] = (
        sess_mx['requests'] == len(phys_mx)
        and sess_mx['cached_calls'] == len(cached_mx)
        and sess_mx['injected_calls'] == len(inj_mx)
        and all(c['physical'] and not c['cached'] for c in inj_mx)
        and inj_ids <= {id(c) for c in phys_mx}
        and not (inj_ids & {id(c) for c in cached_mx})
        and {id(c) for c in phys_mx}.isdisjoint({id(c) for c in cached_mx})
        and len(phys_mx) + len(cached_mx) == len(c_mx))
    # reverse: an injected-but-cached event MUST fail this checker
    def mixed_ok(calls_list):
        inj = [c for c in calls_list if c.get('injected')]
        phys = [c for c in calls_list if c.get('physical')]
        cached = [c for c in calls_list if c.get('cached')]
        return (all(c['physical'] and not c['cached'] for c in inj)
                and phys and cached
                and {id(c) for c in phys}.isdisjoint(
                    {id(c) for c in cached}))
    poisoned_ev = [dict(c) for c in c_mx]
    # make one cached event falsely injected
    victim = next(c for c in poisoned_ev if c['cached'])
    victim['injected'] = True
    checks['p3b2_reverse_injected_cached_detected'] = not mixed_ok(
        poisoned_ev)
    checks['p3b2_tokens_and_settlement'] = (
        sess_mx['tokens_total'] == tok_phys
        and st_mx_view.tokens_physical == tok_phys)
    # clock-sync assertion: engine and state still share the SAME clock
    # object and agree on the current time after the whole run
    checks['p3b2_shared_clock_sync'] = (
        eng_mx.clock is st_mx.clock
        and eng_mx.clock.time() == st_mx.clock.time()
        and eng_mx.clock.time() > 0.0)
    det['p3b2_mixed'] = dict(call_events=len(c_mx),
                             physical=len(phys_mx), cached=len(cached_mx),
                             injected=len(inj_mx),
                             calls_field=sess_mx['calls'],
                             requests=sess_mx['requests'],
                             tokens=sess_mx['tokens_total'])

    all_pass = all(checks.values())
    evidence = dict(audit='boundary', checks=checks, all_pass=all_pass,
                    zero_model_calls=True, detail=det)
    (HERE / 'evidence' / 'BOUNDARY_EVIDENCE.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{sum(checks.values())}/{len(checks)} checks; '
          f'zero_model_calls=true; '
          f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')
    return 0 if all_pass else 2


if __name__ == '__main__':
    with no_socket():
        raise SystemExit(main())
