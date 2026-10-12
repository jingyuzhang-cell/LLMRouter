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
            ('mono', 'plain'): 'The answer is 1.5',
            ('mono', 'retry'): '{"value": 1.5}'})
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
    p = out / 'RESULTS.json'
    jv.write_results(p, 'INCOMPLETE', dict(reason='test-interrupt'))
    assert (out / 'RESULTS_INCOMPLETE.json').exists() and not p.exists()
    guard_ok = True
    try:                              # INCOMPLETE artifact never rewritten
        jv.write_results(p, 'INCOMPLETE', dict(reason='again'))
        guard_ok = False
    except PermissionError:
        pass
    jv.write_results(p, 'COMPLETE', dict(x=1))            # fresh official
    try:                              # official never overwritten
        jv.write_results(p, 'COMPLETE', dict(x=2))
        guard_ok = False
    except PermissionError:
        pass
    checks['T5_incomplete_guard'] = guard_ok

    evidence = dict(milestone='joint_verification_zero_call',
                    ruling='operator 2026-10-12 (baseline 83ea096)',
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


if __name__ == '__main__':
    raise SystemExit(main())
