"""P0-A/P0-B/P0-C verification (operator ruling 2026-10-12): the M5
closure fix, decision-row persistence, and SS exception semantics.

Deterministic stub scenarios for e-node failures (the gap that made the
LOCAL family unreachable in run_20261012_092146):
  S1 single extraction node FAILED, r DONE, v PENDING
  S2 single extraction node FAILED, r AND v both DONE
  S3 e-node AND r-node failures together
  S4 upstream recovery triggers downstream closure completion (calls!)
  S5 downstream RUNNING -> illegal plans rejected (no LOCAL candidates)
  S6 fixed-model LOCAL vs dynamic LOCAL: legality + actual call diff
  P0-C: SS picks the fixed LOCAL recipe on ordinary e-failures (never a
        silent NONE); STATIC_RECOVERY_UNAVAILABLE only for genuinely
        illegal states
  P0-B: full decision rows persisted BEFORE execution, joinable by id

Run: python3 -m deadline_reward_v1.test_m5_closure_fix
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

from deadline_reward_v1 import arm_entry, policy
from deadline_reward_v1 import dag_closure as dc
from deadline_reward_v1 import supplementary_runner as sr
from deadline_reward_v1.reassign import apply_whole_plan, \
    enumerate_candidates
from deadline_reward_v1.scheduler_state import SchedulerState
from deadline_reward_v1.stub_engine import (InjectedClock, StubEngine,
                                            StubModelServer)

PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
PLANNED = dict(e1='large', e2='large', r='medium', v='coder')
# r's canned expression references v0 ONLY, so it stays evaluable (DONE)
# on e1's facts alone even when e2 fails with empty facts; v matches r.
G = dict(e1='{"facts": [{"value": 1.5, "evidence": "a"}]}',
         e2='{"facts": [{"value": 2.5, "evidence": "b"}]}',
         r='{"expression": "v0"}', v='{"value": 1.5}')
ANS = {('e1', 'plain'): G['e1'], ('e2', 'plain'): G['e2'],
       ('r', 'plain'): G['r'], ('v', 'plain'): G['v'],
       ('e1', 'fb'): G['e1'], ('e2', 'fb'): G['e2'],
       ('e1', 'fbd'): G['e1'], ('e2', 'fbd'): G['e2'],
       ('r', 'fbd'): G['r'], ('r', 'esc'): G['r'],
       ('v', 'fbd'): G['v'], ('v', 'esc'): G['v']}
# answers for the DYNAMIC (reassigned) models — different values so the
# call-sequence difference is observable
GD = dict(e2='{"facts": [{"value": 10.5, "evidence": "b2"}]}',
          r='{"expression": "v0"}', v='{"value": 10.5}')
TASK = dict(uid='m5x_task', question='q', derivation='1.5+2.5',
            answer=4.0, ctx_table='T', ctx_text='P')
OUT = HERE / 'evidence' / 'm5_closure_fix'


def _episode(out, fault_node='e2', fault_model='large',
             run_v1=False, answers=None, drive=True):
    """Build a stub episode with an e/r-node fault. drive=True runs the
    planned stages (unit scenarios: enumeration on the post-R1 state);
    drive=False only sets the fault and hands the engine to run_cell,
    which drives its own panel/stages."""
    server = StubModelServer(dict(answers or ANS), PRIORS, seed='m5x')
    server.set_fault(TASK['uid'], fault_node, fault_model,
                     '{"facts": []}')            # D1: empty facts
    clock = InjectedClock()
    engine = StubEngine(out, server, clock, seed='m5x',
                        profile_key='v3_compat')
    state = SchedulerState(clock, task_deadlines={TASK['uid']: 3600.0},
                           token_allocation=100000.0)
    state.attach(engine)
    if not drive:
        return engine, state, server
    engine.start_panel([TASK], PLANNED)
    engine.run_jobs('A', engine.planned_jobs([TASK], PLANNED, ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs([TASK], PLANNED, ('r',)))
    if run_v1:
        engine.run_jobs('V1', engine.planned_jobs([TASK], PLANNED, ('v',)))
    return engine, state, server


def _policy_params():
    pol = PRIORS['policy']
    return dict(priors=PRIORS, q_min=pol['q_min'], eps=pol['eps'],
                lam_c=pol['lam_c'], lam_t=pol['lam_t'], lam_f=pol['lam_f'],
                c0=pol['c0'])


def _row(cand):
    return dict(arm=cand.arm, R_pi=dict(cand.pi))


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    checks, detail = {}, {}

    # ---- S1: e2 FAILED, r DONE, v PENDING ----------------------------
    eng, st, srv = _episode(OUT / 's1')
    s = st.tasks[TASK['uid']]
    assert s.node_status['e2'] == 'FAILED' and s.node_status['r'] == 'DONE' \
        and s.node_status['v'] == 'PENDING'
    cands = enumerate_candidates(st, TASK['uid'], PLANNED)
    locals_ = [c for c in cands if c.arm == 'LOCAL']
    checks['S1_local_exists'] = bool(locals_)
    # closure explicit: every LOCAL candidate's judgment re-executes e2 AND r
    checks['S1_closure_in_execute'] = all(
        {'e2', 'r'} <= {n for n, _ in c.judgment.execute} for c in locals_)
    # v is PENDING first execution, never a re-execution in R
    checks['S1_v_pending_only'] = all(
        'v' not in {n for n, _ in c.judgment.execute}
        or s.node_status.get('v') == 'PENDING' for c in locals_)
    planned_pick = arm_entry.static_recipe_pick(cands, PLANNED)
    checks['S1_ss_static_pick_exists'] = planned_pick is not None
    detail['S1'] = dict(n_local=len(locals_),
                        sample_pi=[dict(c.pi) for c in locals_[:3]])

    # ---- S2: e2 FAILED, r DONE, v DONE --------------------------------
    eng2, st2, _ = _episode(OUT / 's2', run_v1=True)
    s2 = st2.tasks[TASK['uid']]
    assert s2.node_status['e2'] == 'FAILED' and s2.node_status['r'] == 'DONE'\
        and s2.node_status['v'] == 'DONE'
    cands2 = enumerate_candidates(st2, TASK['uid'], PLANNED)
    locals2 = [c for c in cands2 if c.arm == 'LOCAL']
    checks['S2_local_exists'] = bool(locals2)
    checks['S2_full_closure'] = all(
        {'e2', 'r', 'v'} <= {n for n, _ in c.judgment.execute}
        for c in locals2)
    checks['S2_ss_pick'] = arm_entry.static_recipe_pick(
        cands2, PLANNED) is not None
    detail['S2'] = dict(n_local=len(locals2))

    # ---- S3: e1 AND r both FAILED --------------------------------------
    eng3, st3, _ = _episode(OUT / 's3', fault_node='e1')
    srv3 = eng3.server
    srv3.set_fault(TASK['uid'], 'r', 'medium', '###D3###')
    # re-run R1 with the r fault: r retry needs a fresh attempt key —
    # drive a second r call through run_jobs
    eng3.run_jobs('R1b', [dict(task=TASK, node='r', kind='esc',
                               model='medium', no_cache=True)])
    s3 = st3.tasks[TASK['uid']]
    assert s3.node_status['e1'] == 'FAILED' and s3.node_status['r'] == 'FAILED'
    cands3 = enumerate_candidates(st3, TASK['uid'], PLANNED)
    locals3 = [c for c in cands3 if c.arm == 'LOCAL']
    checks['S3_local_exists'] = bool(locals3)
    checks['S3_kinds'] = all(
        c.kinds.get('e1') == 'fb' and c.kinds.get('r') == 'esc'
        for c in locals3)
    detail['S3'] = dict(n_local=len(locals3))

    # ---- S4: upstream recovery REALLY re-executes downstream ----------
    eng4, st4, _ = _episode(OUT / 's4')
    cands4 = enumerate_candidates(st4, TASK['uid'], PLANNED)
    pick4 = arm_entry.static_recipe_pick(cands4, PLANNED)
    before = eng4.requests_total
    apply_whole_plan(eng4, st4, TASK, PLANNED, pick4)
    events = [json.loads(l) for l in
              (OUT / 's4' / 'TASK_LEDGER.jsonl').read_text().splitlines()]
    plan_calls = [e for e in events if e['event'] == 'call'
                  and e['stage'].startswith('plan')]
    nodes = [c['node'] for c in plan_calls]
    checks['S4_e2_retry'] = 'e2' in nodes
    checks['S4_r_refreshed'] = 'r' in nodes          # closure re-execution
    checks['S4_kinds_fbd'] = any(c['kind'] == 'fbd' and c['node'] == 'r'
                                 for c in plan_calls)
    detail['S4'] = dict(plan_calls=[(c['node'], c['model'], c['kind'])
                                    for c in plan_calls],
                        new_requests=eng4.requests_total - before)

    # ---- S5: RUNNING downstream -> no LOCAL candidates -----------------
    eng5, st5, _ = _episode(OUT / 's5')
    s5 = st5.tasks[TASK['uid']]
    # put v into RUNNING via a synthetic call_start (call never lands)
    s5.node_status['v'] = dc.RUNNING
    cands5 = enumerate_candidates(st5, TASK['uid'], PLANNED)
    checks['S5_no_local'] = not any(c.arm == 'LOCAL' for c in cands5)
    # and SS records STATIC_RECOVERY_UNAVAILABLE (P0-C), never NONE
    rec5 = arm_entry.decide_arm(
        st5, TASK['uid'], cands5, 'SS', PLANNED, _policy_params(),
        policy.OutcomePredictor(PRIORS), policy.DeadlineCompensator(PRIORS),
        lambda: eng5.current_model)
    checks['S5_ss_reason'] = (rec5['degraded'] is True
                              and rec5['reason']
                              == 'STATIC_RECOVERY_UNAVAILABLE')
    detail['S5'] = dict(reason=rec5['reason'])

    # ---- S6: fixed vs dynamic LOCAL — legality + call difference -------
    eng6, st6, _ = _episode(OUT / 's6')
    cands6 = enumerate_candidates(st6, TASK['uid'], PLANNED)
    fixed = arm_entry.static_recipe_pick(cands6, PLANNED)
    dynamic = next((c for c in cands6 if c.arm == 'LOCAL'
                    and c.pi.get('r') == 'large'
                    and c.pi.get('e2') == 'coder'), None)
    checks['S6_both_legal'] = fixed is not None and dynamic is not None
    eng_f, st_f, _ = _episode(OUT / 's6f')
    cands_f = enumerate_candidates(st_f, TASK['uid'], PLANNED)
    apply_whole_plan(eng_f, st_f, TASK, PLANNED,
                     arm_entry.static_recipe_pick(cands_f, PLANNED))
    ev_f = [json.loads(l) for l in
            (OUT / 's6f' / 'TASK_LEDGER.jsonl').read_text().splitlines()]
    calls_f = [(e['node'], e['model']) for e in ev_f
               if e['event'] == 'call' and e['stage'].startswith('plan')]
    dyn_answers = {**ANS, ('e2', 'fbd'): GD['e2'],
                   ('e2', 'fb'): GD['e2'], ('r', 'fbd'): GD['r'],
                   ('v', 'plain'): GD['v']}
    eng_d, st_d, _ = _episode(OUT / 's6d', answers=dyn_answers)
    # NOTE: e2's DYNAMIC answer differs => r's refreshed input differs
    cands_d = enumerate_candidates(st_d, TASK['uid'], PLANNED)
    dyn_pick = next(c for c in cands_d if c.arm == 'LOCAL'
                    and c.pi.get('r') == 'large' and c.pi.get('e2') == 'coder')
    apply_whole_plan(eng_d, st_d, TASK, PLANNED, dyn_pick)
    ev_d = [json.loads(l) for l in
            (OUT / 's6d' / 'TASK_LEDGER.jsonl').read_text().splitlines()]
    calls_d = [(e['node'], e['model']) for e in ev_d
               if e['event'] == 'call' and e['stage'].startswith('plan')]
    checks['S6_calls_differ'] = calls_f != calls_d
    detail['S6'] = dict(fixed=calls_f, dynamic=calls_d)

    # ---- P0-C: SS on S1 through run_cell — fixed recipe, no NONE -------
    eng7, st7, _ = _episode(OUT / 'p0c', drive=False)
    pol = _policy_params()
    rows, metering = sr.run_cell(
        eng7, eng7.server, st7, [TASK], PLANNED, 'SS', 'clean', set(),
        policy.OutcomePredictor(PRIORS), policy.DeadlineCompensator(PRIORS),
        pol, OUT / 'p0c')
    checks['P0C_ss_executes_fixed_recipe'] = (
        rows[0]['decision']['chosen'] is not None
        and rows[0]['decision']['chosen']['arm'] == 'LOCAL'
        and rows[0]['decision']['chosen']['pi']
        == {k: PLANNED[k] for k in ('e2', 'r', 'v')}
        and not rows[0]['degraded']
        and rows[0]['logical_calls'] == 6)
    # 6 = e1 + e2(R1, faulted) + r(R1) + e2(fb retry) + r(fbd closure
    # refresh) + v(V stage, exactly once) — the legal fixed LOCAL recipe
    # WITH the explicit closure refresh
    led7 = [json.loads(l) for l in
            (OUT / 'p0c' / 'TASK_LEDGER.jsonl').read_text().splitlines()]
    v_calls7 = [e for e in led7 if e['event'] == 'call' and e['node'] == 'v']
    checks['P0C_v_ran_once'] = len(v_calls7) == 1

    # ---- P0-B: full rows persisted BEFORE execution, joinable ----------
    dec_ev = [e for e in led7 if e['event'] == 'arm_decision']
    checks['P0B_decision_event_exists'] = len(dec_ev) == 1
    d7 = dec_ev[0]
    need = {'q', 'mu_e2e', 'p90', 'p_on_time', 'e_late', 'dcost', 'score',
            'estimator', 'estimator_claim', 'execute', 'reuse',
            'deficits', 'pi', 'arm'}
    # SS is static (no scored table) — check the policy arm instead.
    # r-fault scenario so the policy EXECUTES a plan (a plan-stage call
    # follows the decision event; e-fault scenarios would degrade under
    # the stub beliefs and produce no plan calls).
    eng8, st8, _ = _episode(OUT / 'p0b', fault_node='r',
                            fault_model='medium', drive=False)
    rows8, _ = sr.run_cell(
        eng8, eng8.server, st8, [TASK], PLANNED, 'DD', 'clean', set(),
        policy.OutcomePredictor(PRIORS), policy.DeadlineCompensator(PRIORS),
        _policy_params(), OUT / 'p0b')
    led8 = [json.loads(l) for l in
            (OUT / 'p0b' / 'TASK_LEDGER.jsonl').read_text().splitlines()]
    dec8 = [e for e in led8 if e['event'] == 'arm_decision'][0]
    checks['P0B_full_row_fields'] = all(
        need <= set(r) for r in dec8['table'])
    checks['P0B_context_fields'] = all(
        k in dec8 for k in ('decision_id', 'decision_unix', 'd_remain',
                            'b_remain_tokens', 'reason'))
    dec_idx = next(i for i, e in enumerate(led8)
                   if e['event'] == 'arm_decision')
    exec_idx = next((i for i, e in enumerate(led8)
                     if e['event'] == 'call'
                     and str(e['stage']).startswith('plan')), None)
    checks['P0B_before_execution'] = exec_idx is not None \
        and dec_idx < exec_idx
    checks['P0B_no_oracle_fields'] = not any(
        k in r for r in dec8['table']
        for k in ('gold', 'fault', 'actual', 'future'))
    detail['P0B'] = dict(n_rows=len(dec8['table']),
                         row0_keys=sorted(dec8['table'][0].keys()))

    # ---- r-only regression: R_eff == failed (unchanged behavior) -------
    eng9, st9, _ = _episode(OUT / 'reg', fault_node='r',
                            fault_model='medium')
    cands9 = enumerate_candidates(st9, TASK['uid'], PLANNED)
    locals9 = [c for c in cands9 if c.arm == 'LOCAL']
    checks['REG_r_only_pi_domain'] = all(
        set(c.pi) == {'r', 'v'} for c in locals9)
    checks['REG_r_only_count'] = len(locals9) == 4   # 2(r) x 2(v) menu

    evidence = dict(milestone='P0_ABC_verification',
                    ruling='operator 2026-10-12 (baseline f0b3e5e)',
                    checks=checks, detail=detail,
                    zero_model_calls=True,
                    all_pass=all(checks.values()))
    (HERE / 'evidence' / 'M5_CLOSURE_FIX.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f"\n{sum(checks.values())}/{len(checks)}; zero_model_calls=true; "
          f"{'ALL PASS' if all(checks.values()) else 'FAIL PRESENT'}")
    return 0 if all(checks.values()) else 2


if __name__ == '__main__':
    raise SystemExit(main())
