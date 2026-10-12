"""Zero-call tests for the joint-verification runner (operator mandate
2026-10-12; NO real model entry, NO GPU init — stub engine only):

  T1 six-arm end-to-end recording (5 DAG arms + MONO): every row carries
     Q / C / T / D / on_time_correct / R_task + settlement separation
  T2 reward manual verification (hand-computed realized_rtask cases,
     incl. the exact T==D boundary and T==D+eps lateness)
  T3 gold isolation: perturbing the gold map changes ONLY terminal
     settlement, never decisions (counterfactual on the stub)
  T4 fault isolation: DAG D3 faults never touch MONO rows and vice versa
  T5 interruption & ledger: mid-cell exception -> INCOMPLETE artifact,
     official file absent, never overwritten

Run: python3 -m deadline_reward_v1.test_joint_verification
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

from deadline_reward_v1 import joint_verification_runner as jv
from deadline_reward_v1 import policy
from deadline_reward_v1.reward import realized_rtask
from deadline_reward_v1.scheduler_state import SchedulerState
from deadline_reward_v1.stub_engine import (InjectedClock, StubEngine,
                                            StubModelServer)

LAM = jv.LAM

PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
PLANNED = dict(e1='large', e2='large', r='medium', v='coder')
G = dict(e1='{"facts": [{"value": 1.5, "evidence": "a"}]}',
         e2='{"facts": [{"value": 2.5, "evidence": "b"}]}',
         r='{"expression": "v0"}', v='{"value": 1.5}')
ANS = {(n, 'plain'): g for n, g in G.items()}
ANS.update({('e1', 'fb'): G['e1'], ('e2', 'fb'): G['e2'],
            ('e1', 'fbd'): G['e1'], ('e2', 'fbd'): G['e2'],
            ('r', 'fbd'): G['r'], ('r', 'esc'): G['r'],
            ('v', 'fbd'): G['v'], ('v', 'esc'): G['v'],
            ('v', 'mono'): 'The answer is 1.5',
            ('v', 'mono_bad'): 'garbage',
            ('v', 'mono_retry'): '{"value": 1.5}'})
TASKS = [dict(uid=f'jv{i}', question=f'q{i}', derivation='1.5',
              answer=1.5, ctx_table='T', ctx_text='P') for i in range(3)]


def _episode(out, fault=False):
    server = StubModelServer(dict(ANS), PRIORS, seed='jv')
    if fault:
        server.set_fault(TASKS[0]['uid'], 'r', 'medium', '###D3###')
    clock = InjectedClock()
    engine = StubEngine(out, server, clock, seed='jv',
                        profile_key='v3_compat')
    state = SchedulerState(clock,
                           task_deadlines={t['uid']: 100.0
                                           for t in TASKS},
                           token_allocation=100000.0)
    state.attach(engine)
    return engine, state, server


def _params():
    p = PRIORS['policy']
    return dict(priors=PRIORS, q_min=p['q_min'], eps=p['eps'],
                lam_c=p['lam_c'], lam_t=p['lam_t'], lam_f=p['lam_f'],
                c0=p['c0']), dict(LAM)


def main():
    out = HERE / 'evidence' / 'jv_tests'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    checks, detail = {}, {}
    params, lam = _params()
    pred = policy.OutcomePredictor(PRIORS)
    comp = policy.DeadlineCompensator(PRIORS)

    # gold map: tasks have plain numeric answers; contract falls back
    gold_map = {t['uid']: dict(gold=t['answer'],
                               gold_source='v1_fallback') for t in TASKS}
    D_abs = {t['uid']: 100.0 for t in TASKS}

    # ---- T1: six arms end-to-end --------------------------------------
    t1 = {}
    for arm in ('SS', 'DS', 'SD', 'DD', 'NONE'):
        eng, st, _ = _episode(out / arm, fault=(arm != 'NONE'))
        rows, settled, metering = jv.run_dag_cell(
            eng, st, TASKS, PLANNED, arm, 'fault30_D3',
            {TASKS[0]['uid']} if arm != 'NONE' else set(), pred, comp,
            params, gold_map, lam, D_abs)
        ok = all({'Q', 'C_tokens', 'T', 'D', 'on_time_correct', 'R_task',
                  'degraded'} <= set(s) for s in settled)
        t1[arm] = ok and len(settled) == 3
    eng, st, _ = _episode(out / 'MONO')
    mono_rows = jv.run_mono_cell(eng, st, TASKS, 'large', gold_map, lam,
                                 D_abs)
    t1['MONO'] = all(r['Q'] == 1 and r['R_task'] > 0 for r in mono_rows)
    checks['T1_six_arms_recorded'] = all(t1.values())
    detail['T1'] = t1

    # ---- T2: reward manual verification -------------------------------
    r_exact = realized_rtask(q=1, c_full=400, T=10.0, D=10.0, **lam)
    assert abs(r_exact - (1 - 0.5 * 400 / 4000)) < 1e-12   # on-time exact
    r_late = realized_rtask(q=1, c_full=400, T=10.5, D=10.0, **lam)
    want = (-0.5 * 400 / 4000 - 1.0 * 0.5 / 10.0 - 2.0)
    assert abs(r_late - want) < 1e-12                       # late: all terms
    checks['T2_reward_manual'] = True
    detail['T2'] = dict(on_time_exact=r_exact, late=r_late, want=want)

    # ---- T3: gold isolation -------------------------------------------
    engA, stA, _ = _episode(out / 'goldA', fault=True)
    rowsA, _, _ = jv.run_dag_cell(engA, stA, TASKS, PLANNED, 'DD',
                                  'fault30_D3', {TASKS[0]['uid']},
                                  pred, comp, params, gold_map, lam, D_abs)
    decA = [e for e in _load(out / 'goldA') if e['event'] == 'arm_decision']
    gm2 = {u: dict(gold=999.0, gold_source='perturbed')
           for u in gold_map}
    engB, stB, _ = _episode(out / 'goldB', fault=True)
    rowsB, _, _ = jv.run_dag_cell(engB, stB, TASKS, PLANNED, 'DD',
                                  'fault30_D3', {TASKS[0]['uid']},
                                  pred, comp, params, gm2, lam, D_abs)
    decB = [e for e in _load(out / 'goldB') if e['event'] == 'arm_decision']

    def _stable(events):
        # strip volatile fields (timestamps); the substantive decision
        # content must be identical when only gold changes
        out = []
        for e in events:
            e = {k: v for k, v in e.items() if k != 'decision_unix'}
            out.append(e)
        return json.dumps(out, sort_keys=True)

    same_decisions = _stable(decA) == _stable(decB)
    qA = {r['uid']: r['Q_v21'] for r in rowsA}
    qB = {r['uid']: r['R_settlement']['Q'] for r in rowsB}
    checks['T3_gold_isolation'] = (same_decisions
                                   and sum(qA.values()) > sum(qB.values()))
    detail['T3'] = dict(decisions_identical=same_decisions,
                        q_original=sum(qA.values()),
                        q_perturbed=sum(qB.values()))

    # ---- T4: fault isolation ------------------------------------------
    eng, st, _ = _episode(out / 'isoM', fault=True)   # DAG fault set
    mono_rows_f = jv.run_mono_cell(eng, st, TASKS, 'large', gold_map,
                                   lam, D_abs)
    # the DAG r-fault must not have corrupted any MONO-slot answer
    injected_in_mono = [e for e in _load(out / 'isoM')
                        if e['event'] == 'call' and e.get('injected')
                        and e['stage'].startswith('MONO')]
    checks['T4_mono_untouched_by_dag_fault'] = (
        all(r['Q'] == 1 for r in mono_rows_f) and not injected_in_mono)
    # reverse: mono corruption must not touch a later DAG cell
    eng2, st2, _ = _episode(out / 'isoD')
    jv.run_mono_cell(eng2, st2, TASKS, 'large', gold_map, lam, D_abs,
                     mono_corrupt_uids=(TASKS[0]['uid'],))
    rows2, _, _ = jv.run_dag_cell(eng2, st2, TASKS, PLANNED, 'NONE',
                                  'clean', set(), pred, comp, params,
                                  gold_map, lam, D_abs)
    mono_ev = [e for e in _load(out / 'isoD')
               if e['event'] == 'call' and e.get('injected')
               and e['stage'].startswith('MONO')]
    # the corrupted task hits the fault on BOTH the initial call and the
    # pre-defined same-model fallback (2 injections, Q=0); the registry
    # is cleared afterwards and the subsequent DAG cell is unaffected
    checks['T4_dag_untouched_by_mono_fault'] = (
        len(mono_ev) == 2 and not eng2.server.faults
        and all(r['Q_v21'] == 1 for r in rows2))

    # ---- T5: interruption & ledger ------------------------------------
    # strengthened per the 2026-10-12 ruling: a run that recorded
    # INCOMPLETE can NEVER be marked COMPLETE afterwards
    p = out / 'RESULTS.json'
    jv.write_results(p, 'INCOMPLETE', dict(reason='test-interrupt'))
    assert (out / 'RESULTS_INCOMPLETE.json').exists() and not p.exists()
    guard_ok = True
    try:                              # INCOMPLETE artifact never rewritten
        jv.write_results(p, 'INCOMPLETE', dict(reason='again'))
        guard_ok = False
    except PermissionError:
        pass
    try:                              # never COMPLETE after INCOMPLETE
        jv.write_results(p, 'COMPLETE', dict(x=1))
        guard_ok = False
    except PermissionError:
        pass
    checks['T5_incomplete_guard'] = guard_ok

    # ---- extension round (operator ruling on da3904b): T6-T11 -------
    for name, fn in (('T6_mono_real_prompt', test_T6_mono_real_prompt),
                     ('T7_cache_fairness', test_T7_cache_fairness),
                     ('T8_settlement_refusal', test_T8_settlement_refusal),
                     ('T9_incomplete_blocks_complete',
                      test_T9_incomplete_blocks_complete),
                     ('T10_tier_discrimination',
                      test_T10_tier_discrimination),
                     ('T11_p3_freeze', test_T11_p3_freeze)):
        checks[name] = bool(fn())

    evidence = dict(milestone='joint_verification_zero_call',
                    ruling='operator 2026-10-12 final wiring (baseline da3904b)',
                    checks=checks, detail=detail, zero_model_calls=True,
                    no_gpu_init=True,
                    all_pass=all(checks.values()))
    (HERE / 'evidence' / 'JOINT_VERIFY_ZERO_CALL.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f"\nzero_model_calls=true; "
          f"{'ALL PASS' if evidence['all_pass'] else 'FAIL PRESENT'}")
    return 0 if evidence['all_pass'] else 2


def _load(d):
    return [json.loads(l) for l in
            (d / 'TASK_LEDGER.jsonl').read_text().splitlines()]




# ============ extension: operator ruling round (da3904b) T6-T11 ==========

def _real_server_fake_transport(out):
    """RealServer + fake transport: captures the FINAL prompts sent to
    call_model (request-level assertion per ruling #1)."""
    import deadline_reward_v1.supplementary_runner as sr

    class FakeMod:
        def __init__(self):
            self.prompts = []

        def call_model(self, model, prompt):
            self.prompts.append((model, prompt))
            return dict(status='delivered', answer='{"value": 1.5}',
                        usage=dict(prompt_tokens=10, completion_tokens=5,
                                   total_tokens=15))

    class FakeMgr:
        def __init__(self):
            self.mod = FakeMod()

        def _mod(self):
            return self.mod

        def start(self, m):
            pass

        def stop_current(self):
            pass

    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget
    d = out
    d.mkdir(parents=True, exist_ok=True)
    budget = Budget(d, dict(wall_seconds=600.0, new_request_attempts=50,
                            new_total_tokens=50000,
                            request_token_reservation=2048,
                            max_output_tokens=4096))
    task_map = {t['uid']: t for t in TASKS}
    mgr = FakeMgr()
    server = sr.RealServer({}, mgr, budget, task_map, d)
    server.engine = None
    return server, mgr


def test_T6_mono_real_prompt():
    out = HERE / 'evidence' / 'jv_tests' / 't6'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    server, mgr = _real_server_fake_transport(out)
    task = TASKS[0]
    # minimal engine stub so build_prompt can read (empty) answers
    server.engine = type('E', (), {'tasks': {task['uid']:
                                             type('S', (), {'answers': {}})()}})()
    p = server.build_prompt('v', 'mono', task['uid'])
    want = jv.mono_prompt(task)
    assert p == want, 'mono prompt must be the full-context prompt'
    assert task['ctx_table'] in p and task['ctx_text'] in p
    # request-level: draw() actually sends the mono prompt
    resp = server.draw('v', 'mono', 'large', task['uid'], 1)
    assert resp['answer'] == '{"value": 1.5}'
    sent_model, sent_prompt = mgr.mod.prompts[-1]
    assert sent_prompt == want, 'transport must receive the mono prompt'
    # and the DAG v prompt is NOT the mono prompt
    pv = server.build_prompt('v', 'plain', task['uid'])
    assert pv != want
    return True


def test_T7_cache_fairness():
    out = HERE / 'evidence' / 'jv_tests' / 't7'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    server = StubModelServer(dict(ANS), PRIORS, seed='jv')
    base = StubEngine(out / 'base', server, InjectedClock(), seed='jv')
    snap = jv.run_shared_base(base, TASKS, PLANNED,
                              {TASKS[0]['uid']}, '###D3###')
    assert len(snap) >= 3 * len(TASKS)       # e1,e2,r identities present
    from deadline_reward_v1.scheduler_state import SchedulerState as SS

    def arm(name):
        eng = jv.arm_engine_from_snapshot(out / name, server,
                                          InjectedClock(), snap)
        st = SS(eng.clock, task_deadlines={t['uid']: 100 for t in TASKS},
                token_allocation=1e5)
        st.attach(eng)
        # replay the planned base stages: every identity must HIT the
        # snapshot (0 physical) and the observers rebuild identical
        # node_status — including the D3 corruption on the faulted task
        for uid in {TASKS[0]['uid']}:
            server.set_fault(uid, 'r', PLANNED['r'], '###D3###')
        eng.start_panel(TASKS, PLANNED)
        eng.run_jobs('A', eng.planned_jobs(TASKS, PLANNED, ('e1', 'e2')))
        eng.run_jobs('R1', eng.planned_jobs(TASKS, PLANNED, ('r',)))
        for uid in {TASKS[0]['uid']}:
            server.faults.pop((uid, 'r', PLANNED['r']), None)
        return eng, st

    eng1, st1 = arm('a1')
    phys_base1 = eng1.requests_total
    assert phys_base1 == 0, 'base replay must be pure cache hits'
    assert st1.tasks[TASKS[0]['uid']].node_status['r'] == 'FAILED'
    eng1.run_jobs('V1', [dict(task=TASKS[0], node='v', kind='plain',
                              model=PLANNED['v'])])
    assert eng1.requests_total == 1, 'arm-private v is physical'
    eng2, st2 = arm('a2')
    assert eng2.requests_total == 0
    eng2.run_jobs('V1', [dict(task=TASKS[0], node='v', kind='plain',
                              model=PLANNED['v'])])
    assert eng2.requests_total == 1,         'cross-arm v leakage impossible (separate caches)'
    return True


def test_T8_settlement_refusal():
    from deadline_reward_v1.scheduler_state import SchedulerState as SS
    out = HERE / 'evidence' / 'jv_tests' / 't8'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    server = StubModelServer(dict(ANS), PRIORS, seed='jv')
    eng = StubEngine(out, server, InjectedClock(), seed='jv')
    st = SS(eng.clock, task_deadlines={TASKS[0]['uid']: 100.0},
            token_allocation=1e5)
    st.attach(eng)
    eng.start_panel([TASKS[0]], PLANNED)
    eng.run_jobs('A', eng.planned_jobs([TASKS[0]], PLANNED, ('e1',)))
    # NO task_summary -> no completion_time -> settlement must REFUSE
    sst = st.tasks[TASKS[0]['uid']]
    try:
        jv.realized_row(sst, TASKS[0],
                        {TASKS[0]['uid']: dict(gold=1.5)}, jv.LAM, 1,
                        100.0)
        return False
    except ValueError:
        return True


def test_T9_incomplete_blocks_complete():
    out = HERE / 'evidence' / 'jv_tests' / 't9'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    p = out / 'R.json'
    jv.write_results(p, 'INCOMPLETE', dict(reason='x'))
    try:
        jv.write_results(p, 'COMPLETE', dict(x=1))
        return False
    except PermissionError:
        return True


def test_T10_tier_discrimination():
    """Stub-verify the frozen tier rule actually discriminates (ruling
    #6): with stub priors, a ONE-switch LOCAL recovery (~72 s predicted)
    is infeasible at tight and feasible at medium+; a THREE-switch FULL
    replay (~212 s) is feasible only at wide."""
    fit_binding = {f'{n}|{m}': dict(mean=1.0)
                   for n in ('e1', 'e2') for m in ('medium', 'large', 'coder')}
    fit_binding.update({f'r|{m}': dict(mean=2.0)
                        for m in ('medium', 'large')})
    fit_binding.update({f'v|{m}': dict(mean=1.0)
                        for m in ('coder', 'large')})
    sw = dict(medium=65.0, large=70.0, coder=60.0)
    planned = dict(e1='large', e2='large', r='medium', v='coder')
    Ds = {t: jv.frozen_deadline(planned, t, fit_binding, sw)
          for t in ('tight', 'medium', 'wide')}
    assert Ds['tight'] < Ds['medium'] < Ds['wide']
    from deadline_reward_v1.predictor import e1_on_time
    np_ = PRIORS['node_profiles']
    full_mu = (np_['e1|large']['lat_mean_s']
               + np_['e2|large']['lat_mean_s']
               + np_['r|large']['lat_mean_s']
               + np_['v|coder']['lat_mean_s'])
    full_p90 = (np_['e1|large']['lat_p90_s']
                + np_['e2|large']['lat_p90_s']
                + np_['r|large']['lat_p90_s']
                + np_['v|coder']['lat_p90_s'])
    # LOCAL: retry r on large + v on coder; current model medium ->
    # one stop+start to large: ~71.5 s switch + ~2.8 s service
    local_mu = (np_['r|large']['lat_mean_s']
                + np_['v|coder']['lat_mean_s']) + 71.5
    local_p90 = (np_['r|large']['lat_p90_s']
                 + np_['v|coder']['lat_p90_s']) + 71.5
    # FULL: whole graph on large after medium: cold 70 + 2x(1.5+70)
    full_sw = 70.0 + 2 * 71.5
    feas = dict(
        local={t: e1_on_time(local_mu, local_p90, D)[0] >= 0.90
               for t, D in Ds.items()},
        full={t: e1_on_time(full_mu + full_sw, full_p90 + full_sw, D)[0]
              >= 0.90 for t, D in Ds.items()})
    assert not feas['local']['tight'] and feas['local']['medium'] \
        and feas['local']['wide'], feas
    assert not feas['full']['tight'] and not feas['full']['medium'] \
        and feas['full']['wide'], feas
    return True


def test_T11_p3_freeze():
    f = json.loads((HERE / 'JOINT_VERIFY_P3_FREEZE.json').read_text())
    f2 = jv.build_p3_panel()          # deterministic re-derivation
    assert f['uids'] == f2['uids'] and f['fault_uids'] == f2['fault_uids']
    assert f['uids_sha256'] == f2['uids_sha256']
    assert len(f['uids']) == 60 and len(set(f['uids'])) == 60
    assert len(f['fault_uids']) == 18
    assert set(f['fault_uids']) <= set(f['uids'])
    assert all(f['tiers'][u] in ('tight', 'medium', 'wide')
               for u in f['uids'])
    # isolation: no uid ever used anywhere before
    fz = json.loads((HERE.parent / 'static_dag_v0/frozen200/'
                     'FROZEN200_POLICY.json').read_text())['tasks']
    used = {t['uid'] for t in fz}
    tp = json.loads(
        (HERE.parent / 'collab_scheduler_v1/joint_search_v1/review/'
         'TASK_PANEL_V1.json').read_text())
    for k in ('tasks_search', 'tasks_test', 'reserve'):
        for t in tp.get(k, []):
            used.add(t if isinstance(t, str) else t.get('uid'))
    assert not (set(f['uids']) & used)
    # v2.1 gold availability for every task
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        load_native_answers)
    nat = load_native_answers()
    assert all(u in nat for u in f['uids'])
    return True


if __name__ == '__main__':
    raise SystemExit(main())
