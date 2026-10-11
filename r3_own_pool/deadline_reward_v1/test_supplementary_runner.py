"""Zero-call plumbing smoke for supplementary_runner.run_cell: drives the
cell executor (decision round, batched plan application, V stage, terminal
v2.1 scoring) on the STUB engine with the admission-check D3 scenario.
Validates the runner's cell logic end-to-end BEFORE any real execution;
RealServer/RealEngine hardware specifics are deliberately not covered here.

Run: python3 -m deadline_reward_v1.test_supplementary_runner
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from deadline_reward_v1 import policy
from deadline_reward_v1 import supplementary_runner as sr
from deadline_reward_v1.scheduler_state import SchedulerState
from deadline_reward_v1.stub_engine import InjectedClock, StubEngine, \
    StubModelServer

PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
PLANNED = sr.PLANNED
_GOOD = dict(
    e1='{"facts": [{"value": 1.5, "evidence": "a"}]}',
    e2='{"facts": [{"value": 2.5, "evidence": "b"}]}',
    r='{"expression": "v0+v1"}',
    v='{"value": 4.0}')
ANSWERS = {
    ('e1', 'plain'): _GOOD['e1'], ('e2', 'plain'): _GOOD['e2'],
    ('r', 'plain'): _GOOD['r'], ('v', 'plain'): _GOOD['v'],
    ('e1', 'fb'): _GOOD['e1'], ('e2', 'fb'): _GOOD['e2'],
    ('e1', 'fbd'): _GOOD['e1'], ('e2', 'fbd'): _GOOD['e2'],
    ('r', 'fbd'): _GOOD['r'], ('r', 'esc'): _GOOD['r'],
    ('v', 'fbd'): _GOOD['v'], ('v', 'esc'): _GOOD['v']}
TASK = dict(uid='adm2_task', question='What is 1.5 + 2.5?',
            derivation='1.5+2.5', answer=4.0,
            ctx_table='TABLE: | val | 1.5 |', ctx_text='PASSAGES: value is 2.5')


def run_arm(arm, out_dir):
    server = StubModelServer(dict(ANSWERS), PRIORS, seed=f'smk_{arm}')
    server.set_fault(TASK['uid'], 'r', 'medium', sr.server_fault_answer)
    clock = InjectedClock()
    engine = StubEngine(out_dir, server, clock, seed=f'smk_{arm}',
                        profile_key='v3_compat')
    state = SchedulerState(clock, task_deadlines={TASK['uid']: 80.0},
                           token_allocation=100000.0)
    engine.add_observer(state._on_event)
    pol = PRIORS['policy']
    params = dict(priors=PRIORS, q_min=pol['q_min'], eps=pol['eps'],
                  lam_c=pol['lam_c'], lam_t=pol['lam_t'], lam_f=pol['lam_f'],
                  c0=pol['c0'])
    rows, metering = sr.run_cell(
        engine, server, state, [TASK], PLANNED, arm, 'fault30_D3',
        {TASK['uid']}, policy.OutcomePredictor(PRIORS),
        policy.DeadlineCompensator(PRIORS), params, out_dir)
    engine.observers.remove(state._on_event)
    return rows, metering


def main():
    out = HERE / 'evidence' / 'smk_supp_runner'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    checks = {}
    # STUB-WORLD caveat: canned answers ignore upstream garbage, so the
    # final v VALUE parses correct even after an unrecovered r failure —
    # v2.1 therefore scores SS/NONE correct HERE (on real models v
    # computes from the corrupted expr and the value differentiates). The
    # failure state itself is asserted via node_status.
    expect_q = dict(SS=1, DS=0, SD=1, DD=1, NONE=1)
    expect_degraded = dict(SS=False, DS=True, SD=False, DD=False, NONE=False)
    expect_r_final = dict(SS='FAILED', DS='FAILED', SD='DONE', DD='DONE',
                          NONE='FAILED')
    meterings = {}
    for arm in ('SS', 'DS', 'SD', 'DD', 'NONE'):
        rows, metering = run_arm(arm, out / arm)
        meterings[arm] = metering
        r = rows[0]
        checks[f'{arm}_single_row'] = len(rows) == 1
        checks[f'{arm}_q_world'] = r['Q_v21'] == expect_q[arm]
        checks[f'{arm}_degraded'] = r['degraded'] == expect_degraded[arm]
        checks[f'{arm}_faulted_flag'] = r['faulted'] is True
        checks[f'{arm}_gold_fallback'] = abs(r['gold'] - 4.0) < 1e-9
        checks[f'{arm}_node_status_r_final'] = (
            r['node_status']['r'] == expect_r_final[arm])
        if arm == 'SS':
            checks['SS_retry_jobs_planned'] = r['retry_jobs'] == [
                dict(node='r', model='medium', kind='esc', no_cache=True,
                     pending=False)]
            # v runs ONCE (V stage), never duplicated in the plan batch —
            # the double-execution bug the metering smoke caught
            checks['SS_no_duplicate_v'] = (r['logical_calls'] == 5)
        if arm == 'SD':
            checks['SD_retry_jobs_reassigned'] = any(
                j['node'] == 'r' and j['model'] == 'large'
                for j in r['retry_jobs'])
        if arm == 'DS':
            checks['DS_no_retry_jobs'] = r['retry_jobs'] == []
            checks['DS_decision_violations'] = bool(
                r['decision']['violations'])
        if arm == 'NONE':
            checks['NONE_no_retry_jobs'] = r['retry_jobs'] == []
            # NONE completes the DAG: e1, e2, r (faulted), v = 4 calls
            checks['NONE_completes_dag'] = (r['logical_calls'] == 4)

    # per-cell metering separation (operator boundary 3). Fresh engine per
    # arm in this smoke: every call is physical. SS: e1,e2,r,R1-inj,
    # r-retry-inj, v = 5; DS degrades: 3; SD/DD: 5 (retry un-injected);
    # NONE: 4.
    checks['metering_consistent'] = all(
        m['logical_calls'] == m['new_requests'] + m['cache_hits']
        for m in meterings.values())
    checks['SS_metering'] = (meterings['SS']['new_requests'] == 5
                             and meterings['SS']['cache_hits'] == 0
                             and meterings['SS']['injected_faults'] == 2)
    checks['DS_metering_zero_recovery'] = (
        meterings['DS']['new_requests'] == 3
        and meterings['DS']['injected_faults'] == 1)
    checks['NONE_metering'] = (meterings['NONE']['new_requests'] == 4)
    checks['SD_metering_retry_not_injected'] = (
        meterings['SD']['new_requests'] == 5
        and meterings['SD']['injected_faults'] == 1)

    all_pass = all(checks.values())
    evidence = dict(milestone='supplementary_runner_smoke', checks=checks,
                    all_pass=all_pass, zero_model_calls=True,
                    note='run_cell driven on the STUB engine; real hardware '
                         'paths (RealServer/RealEngine/ModelManager) are '
                         'NOT covered here')
    (HERE / 'evidence' / 'SUPP_RUNNER_SMOKE.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{sum(checks.values())}/{len(checks)}; zero_model_calls=true; '
          f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')
    return 0 if all_pass else 2


if __name__ == '__main__':
    raise SystemExit(main())
