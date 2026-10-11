"""M5+M6 acceptance tests — the joint dynamic policy. Zero real calls.

The operator's four acceptance classes, made executable:
  V1  time-tight golden (A/B/C): D_remain=20, Q_min=0.80, eps=0.10 —
      B(17s, p90 18, q .85) chosen; with B p90=21 (P_on=0.832<0.9) the
      feasible set is EMPTY -> EARLY_STOP, zero further calls, violations
      recorded (never a forced B).
  V8  time-rich tradeoff: both lambda_c regimes pinned — the winner
      follows the E[R_task] arithmetic exactly, no fixed preference.
  V9  budget-insufficient: all quality-passing candidates over budget ->
      EARLY_STOP with budget deficits; looser budget -> the affordable
      quality-passing candidate chosen.
  V10 M5 decisive: SAME fault, different remaining time -> pi differs
      exactly (same Z and R) — falsifies recovery-mode-only systems.

Plus E1 closed-form goldens, settlement goldens (C_new vs C_full
separation), determinism, zero-call sentinel, socket-blocked suite.

Run: python3 -m deadline_reward_v1.test_policy  (any CWD)
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
from deadline_reward_v1.predictor import e1_on_time  # noqa: E402
from deadline_reward_v1.reward import realized_rtask  # noqa: E402
from deadline_reward_v1.scheduler_state import SchedulerState  # noqa: E402
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
BASE_PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'm56_runs'
NODES_MODELS = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}

GOOD_E1 = '{"facts": [{"value": 1.5, "evidence": "a"}]}'
GOOD_E2 = '{"facts": [{"value": 2.5, "evidence": "b"}]}'
GOOD_R = '{"expression": "v0+v1"}'
GOOD_V = '{"value": 4.0}'
BASE_ANSWERS = {('e1', 'plain'): GOOD_E1, ('e2', 'plain'): GOOD_E2,
                ('r', 'plain'): GOOD_R, ('v', 'plain'): GOOD_V,
                ('e1', 'fb'): GOOD_E1, ('e2', 'fb'): GOOD_E2,
                ('r', 'fbd'): GOOD_R, ('r', 'esc'): GOOD_R,
                ('v', 'fbd'): GOOD_V, ('v', 'esc'): GOOD_V}
R_FAULT = '###SYNTHETIC UNPARSEABLE r-output###'


def golden_priors(p90_v_coder=7.5):
    priors = copy.deepcopy(BASE_PRIORS)
    # decision-golden world: resident models (zero switch), zero service
    # on the injected clock so d_remain == the configured deadline
    priors['switch'] = {"family": "deterministic", "stop_s": 0.0,
                        "start_s": {"medium": 0.0, "large": 0.0,
                                    "coder": 0.0}, "synthetic": True}
    priors['node_profiles']['v|coder']['lat_p90_s'] = p90_v_coder
    return priors


def run_golden(dirname, *, deadline, q_min=0.80, eps=0.10, lam_c=0.5,
               token_alloc=4000.0, priors=None, engine_profile='golden_zero',
               fault=True):
    priors = priors or golden_priors()
    task = dict(uid='gt0', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')
    tasks = [task]
    server = StubModelServer(dict(BASE_ANSWERS), priors, seed='m56')
    if fault:
        server.set_fault('gt0', 'r', 'medium', R_FAULT)
    clock = InjectedClock()
    engine = StubEngine(RUNS_DIR / dirname, server, clock, seed='m56',
                        profile_key=engine_profile)
    state = SchedulerState(clock, task_deadlines={'gt0': deadline},
                           token_allocation=token_alloc)
    state.attach(engine)
    params = dict(priors=priors, q_min=q_min, eps=eps, lam_c=lam_c,
                  lam_t=1.0, lam_f=2.0, c0=4000.0, session_bonus=1.0,
                  session_penalty=2.0)
    result = policy.run_episode(engine, state, tasks, NODES_MODELS, params)
    events, torn = load_ledger(RUNS_DIR / dirname / 'TASK_LEDGER.jsonl')
    decisions = [e for e in events if e['event'] == 'decision']
    return dict(engine=engine, state=state, events=events, decisions=decisions,
                torn=torn, result=result, server=server, tasks=tasks)


def chosen_row(run):
    d = next(e for e in run['decisions'] if e['stage'] == 'post_R1')
    return d


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

    # --- V1 scenario 1: B chosen -----------------------------------------
    r1 = run_golden('v1s1', deadline=20.0)
    d1 = chosen_row(r1)
    checks['v1s1_chooses_B'] = (
        not d1['degraded']
        and d1['chosen']['pi'] == {'r': 'large', 'v': 'coder'}
        and d1['chosen']['arm'] == 'LOCAL')
    rows = {(r['arm'], tuple(sorted(r['pi'].items()))): r
            for r in d1['table']}
    a = rows.get(('LOCAL', (('r', 'large'), ('v', 'large'))))
    b = rows.get(('LOCAL', (('r', 'large'), ('v', 'coder'))))
    c = rows.get(('LOCAL', (('r', 'medium'), ('v', 'coder'))))
    checks['v1s1_arithmetic'] = (
        a is not None and b is not None and c is not None
        and abs(a['mu_e2e'] - 24.0) < 1e-9
        and abs(b['mu_e2e'] - 17.0) < 1e-9
        and abs(c['mu_e2e'] - 12.0) < 1e-9
        and abs(a['q'] - 0.95) < 1e-9 and abs(b['q'] - 0.85) < 1e-9
        and abs(c['q'] - 0.60) < 1e-9
        and not a['feasible'] and b['feasible'] and not c['feasible']
        and a['deficits'][0]['constraint'] == 'on_time'
        and c['deficits'][0]['constraint'] == 'q_min')
    # executed: r retried on large; v ran on coder (chosen pi)
    v_call = [e for e in r1['events'] if e['event'] == 'call'
              and e['node'] == 'v'][0]
    r_calls = [e for e in r1['events'] if e['event'] == 'call'
               and e['node'] == 'r']
    checks['v1s1_executed_plan'] = (
        r_calls[-1]['model'] == 'large' and r_calls[-1]['kind'] == 'esc'
        and v_call['model'] == 'coder')
    set1 = r1['result']['settlement']['rewards'][0]
    checks['v1s1_settles_correct'] = (set1['q'] == 1.0
                                      and set1['c_full'] > 0
                                      and not set1['degraded'])

    # --- V1 scenario 2: B p90=21 -> excluded -> EARLY_STOP ----------------
    r2 = run_golden('v1s2', deadline=20.0, priors=golden_priors(p90_v_coder=10.5))
    d2 = chosen_row(r2)
    b2 = next(r for r in d2['table']
              if r['arm'] == 'LOCAL' and r['pi'] == {'r': 'large',
                                                     'v': 'coder'})
    checks['v1s2_mean_not_enough'] = (
        abs(b2['mu_e2e'] - 17.0) < 1e-9 and abs(b2['p90'] - 21.0) < 1e-9
        and not b2['feasible']
        and b2['deficits'][0]['constraint'] == 'on_time')
    checks['v1s2_early_stop'] = (
        d2['degraded'] and d2['chosen'] is None
        and len(d2['violations']) == len(d2['table'])
        and all(not r['feasible'] for r in d2['table']))
    post_calls = [e for e in r2['events'] if e['event'] == 'call'
                  and e.get('stage') in ('plan:LOCAL', 'plan:FULL', 'V1')]
    checks['v1s2_zero_further_calls'] = (
        len(post_calls) == 0
        and r2['state'].tasks['gt0'].degraded
        and r2['result']['settlement']['rewards'][0]['degraded'] is True)

    # --- V8: time-rich, both lambda_c regimes pinned ----------------------
    r8a = run_golden('v8_lam_small', deadline=60.0, lam_c=0.5)
    r8b = run_golden('v8_lam_large', deadline=60.0, lam_c=2.0)
    c8a = chosen_row(r8a)['chosen']
    c8b = chosen_row(r8b)['chosen']
    checks['v8_time_rich_tradeoff'] = (
        c8a['pi'] == {'r': 'large', 'v': 'large'}
        and c8b['pi'] == {'r': 'large', 'v': 'coder'})
    t8 = chosen_row(r8a)['table']
    a8 = next(r for r in t8 if r['pi'] == {'r': 'large', 'v': 'large'})
    b8 = next(r for r in t8 if r['pi'] == {'r': 'large', 'v': 'coder'})
    diff = (a8['score'] - b8['score'])
    checks['v8_arithmetic_matches'] = (
        abs(diff - (0.10 - 0.5 * (a8['dcost'] - b8['dcost']) / 4000.0))
        < 1e-6
        and (diff > 0) != (chosen_row(r8b)['chosen']['pi'] ==
                           {'r': 'large', 'v': 'large'}))

    # --- V9: budget-insufficient ------------------------------------------
    # spent by decision = 3 calls x 100 tokens (golden_zero) -> 300
    r9a = run_golden('v9a_tight', deadline=60.0, token_alloc=1000.0)
    d9a = chosen_row(r9a)
    qpass = [r for r in d9a['table'] if r['q'] >= 0.80]
    checks['v9a_early_stop_budget'] = (
        d9a['degraded']
        and all(r['deficits'] and
                any(x['constraint'] == 'budget' for x in r['deficits'])
                for r in qpass)
        and any(v['constraint'] == 'budget'
                for vv in d9a['violations'] for v in vv['deficits']))
    r9b = run_golden('v9b_loose', deadline=60.0, token_alloc=1350.0)
    d9b = chosen_row(r9b)
    unaffordable = next(r for r in d9b['table']
                        if r['pi'] == {'r': 'large', 'v': 'large'})
    checks['v9b_affordable_chosen'] = (
        not d9b['degraded']
        and not unaffordable['feasible']
        and any(x['constraint'] == 'budget' for x in unaffordable['deficits'])
        and d9b['chosen']['pi'] == {'r': 'large', 'v': 'coder'})

    # --- V10: same fault, different remaining time -> pi differs ----------
    real = copy.deepcopy(BASE_PRIORS)   # nonzero switch costs
    real['node_profiles'] = dict(BASE_PRIORS['node_profiles'])
    r10a = run_golden('v10_rich', deadline=60.0, priors=real,
                      engine_profile='v3_compat')
    r10b = run_golden('v10_tight', deadline=32.0, priors=real,
                      engine_profile='v3_compat')
    ca, cb = chosen_row(r10a)['chosen'], chosen_row(r10b)['chosen']
    checks['v10_pi_differs_by_remaining_time'] = (
        ca['arm'] == cb['arm'] == 'LOCAL'
        and ca['pi']['r'] == cb['pi']['r'] == 'large'
        and ca['pi']['v'] == 'large' and cb['pi']['v'] == 'coder')

    # --- E1 closed-form goldens -------------------------------------------
    p, late = e1_on_time(17.0, 18.0, 20.0)
    sigma = 1.0 / 1.2816
    import math
    phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    z = (17.0 - 20.0) / sigma
    checks['e1_goldens'] = (
        abs(p - phi(3.0 / sigma)) < 1e-12
        and abs(late - sigma * (math.exp(-0.5 * z * z)
                                / math.sqrt(2 * math.pi)
                                + z * phi(z))) < 1e-12
        and e1_on_time(17.0, 17.0, 20.0) == (1.0, 0.0)
        and e1_on_time(24.0, 24.0, 20.0) == (0.0, 4.0)
        and abs(e1_on_time(17.0, 21.0, 20.0)[0] - 0.8316) < 2e-3)

    # --- settlement golden + C_new/C_full separation ----------------------
    checks['settlement_golden'] = (
        abs(realized_rtask(q=0.85, c_full=1000, T=18, D=20, lam_c=0.5,
                           lam_t=1.0, lam_f=2.0, c0=4000) - 0.725) < 1e-12
        and abs(realized_rtask(q=0.85, c_full=1000, T=22, D=20, lam_c=0.5,
                               lam_t=1.0, lam_f=2.0, c0=4000)
                - (0 - 0.125 - 0.1 - 2.0)) < 1e-12
        and abs(realized_rtask(q=1.0, c_full=0, T=20, D=20, lam_c=0.5,
                               lam_t=1.0, lam_f=2.0, c0=4000) - 1.0) < 1e-12)
    b_row = next(r for r in d1['table']
                 if r['pi'] == {'r': 'large', 'v': 'coder'})
    checks['cnew_cfull_separated'] = (
        b_row['dcost'] == 900.0
        and set1['c_full'] == 500      # 3 planned + r-retry + v calls, 100 tok each
        and set1['c_full'] != b_row['dcost'])

    # --- determinism + zero-call ------------------------------------------
    r1b = run_golden('v1s1_det', deadline=20.0)
    a = (RUNS_DIR / 'v1s1' / 'TASK_LEDGER.jsonl').read_bytes()
    b = (RUNS_DIR / 'v1s1_det' / 'TASK_LEDGER.jsonl').read_bytes()
    checks['determinism'] = a == b
    calls = [e for e in r1['events'] if e['event'] == 'call']
    physical = [e for e in calls if e['physical']]
    checks['z1_sentinel'] = (r1['server'].invocations == len(physical))
    checks['not_torn'] = not r1['torn']

    all_pass = all(checks.values())
    evidence = dict(milestone='M5+M6', checks=checks, all_pass=all_pass,
                    zero_model_calls=True,
                    v1_table=chosen_row(r1)['table'],
                    v10=dict(rich=chosen_row(r10a)['chosen'],
                             tight=chosen_row(r10b)['chosen']))
    (HERE / 'evidence' / 'M56_EVIDENCE.json').write_text(
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
