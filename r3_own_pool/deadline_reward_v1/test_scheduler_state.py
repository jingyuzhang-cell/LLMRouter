"""M2 acceptance tests — SchedulerState observation API. Zero real calls.

Covers the operator's M2 requirements: state transitions (PENDING/RUNNING/
DONE/FAILED), time monotonicity under the ruled E2E口径 (release →
termination incl. queue wait), budget conservation (B_remain computed from
real spend), legal observation history (D1–D6 mirrors only), firewall
(LEAK_PROBES), cross-task causality / no-future snapshots (prefix rebuild),
determinism, detection parity vs production, zero-call.

Run: python3 -m deadline_reward_v1.test_scheduler_state  (any CWD)
"""
from __future__ import annotations

import ast
import contextlib
import json
import socket as _socket_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Production reference modules: read-only imports for detection parity
# (sanctioned T3 pattern); loaded before any socket patching.
from collab_scheduler_v1.fault30_protocol import Ledger  # noqa: E402
from static_dag_v0.multidag_dynamic import (  # noqa: E402
    close as prod_close, json_value as prod_json_value,
    value_of as prod_value_of)

from deadline_reward_v1 import detection as det  # noqa: E402
from deadline_reward_v1.scheduler_state import (  # noqa: E402
    DONE, FAILED, PENDING, RUNNING, SchedulerState, make_legal_view)
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'm2_runs'
NODES_MODELS = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
DEADLINES = {f'm1t{i}': 100.0 for i in range(3)}
TOKEN_ALLOC = 4000.0

BASE = {
    ('e1', 'plain'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('e2', 'plain'): '{"facts": [{"value": 2.5, "evidence": "b"}]}',
    ('r', 'plain'): '{"expression": "v0+v1"}',
    ('v', 'plain'): '{"value": 4.0}',
}
# fault script (LEGAL answers — the stub server simply returns them):
BAD = {
    ('m1t1', 'e1', 'plain'): '{"facts": []}',          # D1 + D6
    ('m1t2', 'v', 'plain'): '{"value": null}',         # D5 + D6
}


def make_tasks():
    def t(i, a, b):
        return dict(uid=f'm1t{i}', question=f'What is {a} + {b}?',
                    derivation=f'{a}+{b}', answer=a + b,
                    ctx_table=f'TABLE: | val | {a} |',
                    ctx_text=f'PASSAGES: value is {b}')
    return [t(0, 1.5, 2.5), t(1, 3.0, 4.0), t(2, 2.0, 6.0)]


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


def run_panel(dirname, *, with_faults=True, snapshot_after=None):
    tasks = make_tasks()
    answers = dict(BASE)
    if with_faults:
        answers.update(BAD)
    server = StubModelServer(answers, PRIORS, seed='m2')
    clock = InjectedClock()
    engine = StubEngine(RUNS_DIR / dirname, server, clock, seed='m2',
                        profile_key='v3_compat')
    state = SchedulerState(clock, task_deadlines=DEADLINES,
                           token_allocation=TOKEN_ALLOC)
    state.attach(engine)
    snap = {}
    if snapshot_after is not None:
        n = [0]

        def hook(ev):
            if ev.get('event') == 'call':
                n[0] += 1
                if n[0] == snapshot_after:
                    snap['view'] = state.snapshot(engine, 'mid')
                    snap['at_clock'] = clock.time()
        engine.add_observer(hook)
    summaries = engine.run_panel(tasks, NODES_MODELS)
    events, torn = load_ledger(RUNS_DIR / dirname / 'TASK_LEDGER.jsonl')
    return dict(server=server, clock=clock, engine=engine, state=state,
                summaries=summaries, events=events, torn=torn, snap=snap)


def main():
    import shutil
    shutil.rmtree(RUNS_DIR, ignore_errors=True)  # idempotent re-runs
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    checks = {}
    detail = {}

    run = run_panel('main', snapshot_after=1)  # snapshot after 1st call
    state, events, clock = run['state'], run['events'], run['clock']
    calls = [e for e in events if e['event'] == 'call']

    # --- 1. state transitions --------------------------------------------
    v0 = state.task_view('m1t0')
    checks['clean_task_all_done'] = all(
        v0['node_status'][n] == DONE for n in NODES_MODELS)
    v1 = state.task_view('m1t1')
    checks['faulted_e1_failed'] = v1['node_status']['e1'] == FAILED
    # empty e1 facts ⇒ r's v0 token has no fact ⇒ r unevaluable (D3) —
    # exactly the production cascade semantics — then terminal D6.
    checks['faulted_task_d1_d3_then_d6'] = (
        [o['code'] for o in v1['observations']] == [det.D1, det.D3, det.D6]
        and v1['node_status']['r'] == FAILED)
    v2 = state.task_view('m1t2')
    checks['bad_v_d5_then_d6'] = (
        [o['code'] for o in v2['observations']] == [det.D5, det.D6]
        and v2['node_status']['v'] == FAILED)
    # RUNNING seen mid-flight via prefix replay (r started, not finished)
    r_idx = next(i for i, e in enumerate(events)
                 if e['event'] == 'call' and e['task'] == 'm1t0'
                 and e['node'] == 'r')
    prefix = events[:r_idx]  # includes r's call_start, excludes its call
    pre = SchedulerState.replay(
        prefix, clock=InjectedClock(events[r_idx]['t_start']),
        task_deadlines=DEADLINES, token_allocation=TOKEN_ALLOC)
    pv = pre.task_view('m1t0')
    checks['running_midflight'] = (
        pv['node_status']['e1'] == DONE and pv['node_status']['e2'] == DONE
        and pv['node_status']['r'] == RUNNING
        and pv['node_status']['v'] == PENDING)

    # --- 2. time monotonicity + ruled E2E口径 -----------------------------
    mono_ok, e2e_ok, queue_ok = True, True, True
    for uid in DEADLINES:
        tv = state.task_view(uid)
        mono_ok &= (tv['release_time'] <= tv['first_call_time']
                    <= tv['completion_time'])
        e2e_ok &= tv['e2e_s'] >= tv['service_sum_s'] + tv['switch_sum_s'] \
            + tv['queue_wait_s'] - 1e-9
        queue_ok &= tv['other_wait_s'] is not None and tv['other_wait_s'] >= 0
    checks['time_monotonic'] = mono_ok
    checks['e2e_includes_queue_and_interleave'] = e2e_ok
    checks['other_wait_nonneg'] = queue_ok
    # e2e strictly exceeds service+switch when other tasks interleave
    tv0 = state.task_view('m1t0')
    checks['e2e_gt_ownwork_interleaved'] = (
        tv0['e2e_s'] > tv0['service_sum_s'] + tv0['switch_sum_s']
        + tv0['queue_wait_s'])
    # D_remain computed live, decreases with the clock
    d1 = state.d_remain('m1t0')
    clock.advance(5.0)
    d2 = state.d_remain('m1t0')
    checks['d_remain_live'] = abs((d1 - 5.0) - d2) < 1e-9 and d2 < d1

    # --- 3. budget conservation -------------------------------------------
    sess = next(e for e in events if e['event'] == 'session_summary')
    ledger_tokens = sum(c['usage']['total_tokens'] for c in calls)
    ledger_calls = len(calls)
    per_task_tokens = sum(state.task_view(u)['calls'] for u in DEADLINES)
    checks['budget_tokens_reconcile'] = (
        state.budget()['tokens_spent'] == ledger_tokens
        == sess['tokens_total'])
    checks['budget_requests_reconcile'] = (
        state.budget()['requests_spent'] == ledger_calls == sess['calls']
        == per_task_tokens)
    b = state.budget()
    checks['b_remain_computed'] = (
        b['b_remain_tokens'] == TOKEN_ALLOC - ledger_tokens
        and b['b_remain_tokens'] != 0)

    # --- 4. legal observation history + firewall ---------------------------
    allowed = {det.D1, det.D3, det.D5, det.D6}
    checks['observations_legal_codes_only'] = all(
        o['code'] in allowed for u in DEADLINES
        for o in state.task_view(u)['observations'])
    probes = ['gold', 'answer_gold', 'faults', 'fault_panel', 'states',
              'future_outputs', 'unexecuted', 'row_ok_internals']
    rejected = True
    for p in probes:
        try:
            make_legal_view(**{p: 1})
            rejected = False
        except ValueError:
            pass
    checks['leak_probes_rejected'] = rejected
    view_json = json.dumps(state.legal_view())
    checks['no_node_outputs_in_view'] = (
        'v0+v1' not in view_json and 'PASSAGES' not in view_json
        and 'evidence' not in view_json)

    # --- 5. cross-task causality / no-future snapshot ----------------------
    snap_view = run['snap']['view']
    snap_ev = next(e for e in events if e.get('event') == 'state_snapshot'
                   and e.get('tag') == 'mid')
    mid = SchedulerState.replay(
        events[:snap_ev['n_events_before']],
        clock=InjectedClock(snap_view['panel_clock']),
        task_deadlines=DEADLINES, token_allocation=TOKEN_ALLOC)
    rebuilt = mid.legal_view(tag='mid')
    snap_cmp = json.dumps(snap_view, sort_keys=True)
    reb_cmp = json.dumps(rebuilt, sort_keys=True)
    checks['snapshot_prefix_rebuild_equal'] = snap_cmp == reb_cmp
    # the mid snapshot (taken after call #1) contains no later observations
    snap_json = snap_cmp
    checks['snapshot_has_no_future'] = (
        det.D1 not in snap_json and det.D5 not in snap_json
        and det.D6 not in snap_json
        and snap_view['tasks']['m1t0']['node_status']['r'] == PENDING)

    # --- 6. determinism -----------------------------------------------------
    run_a = run_panel('det_a')
    run_b = run_panel('det_b')
    a = (RUNS_DIR / 'det_a' / 'TASK_LEDGER.jsonl').read_bytes()
    b_ = (RUNS_DIR / 'det_b' / 'TASK_LEDGER.jsonl').read_bytes()
    checks['determinism_bitwise'] = a == b_

    # --- 7. detection parity vs production (probe grids) -------------------
    led = Ledger()
    facts = {'facts': [{'value': 1.5}, {'value': 2.5}]}
    par_ok = True
    for p in ['{"facts": [{"value": 1.5, "evidence": "a"}]}', '{"facts": []}',
              'not json', '{"no_facts": 1}', '{"facts": "x"}', '']:
        prod = led.parse_facts_safe(p)[0].get('facts')
        par_ok &= (not prod) == facts_empty_check(det, p)
    for p in ['{"expression": "v0+v1"}', '{"expression": "v9+v1"}',
              'garbage', '{"no_expression": 1}', '{"expression": "v0 + v1"}',
              '{"expression": [1]}', '{"expression": "v0+v1+v2"}']:
        pv, pe = prod_value_of(p, facts)
        mv, me = det.value_of(p, facts['facts'])
        par_ok &= (pe == me) and (pe or (abs(pv - mv) < 1e-9))
    for p in ['{"value": 4.0}', '{"value": null}', 'garbage',
              '{"no_value": 1}', '{"value": "4"}', '{"value": true}',
              '{"value": "abc"}']:
        par_ok &= (prod_json_value(p) == det.json_value(p))
    for x, y in [(4.0, 4.0), (4.0, 4.1), (4.0, 4.000001), (4.0, 4.0000001),
                 (0.30000000000000004, 0.3), (4.0, -4.0), (None, 4.0)]:
        par_ok &= bool(prod_close(x, y)) == bool(det.close(x, y))
    checks['detection_parity_production'] = par_ok

    # --- 8. zero-call -------------------------------------------------------
    checks['z1_sentinel'] = (run['server'].invocations
                             + run_a['server'].invocations
                             + run_b['server'].invocations
                             == 3 * len(calls))
    allowed_mods = {'__future__', 'json', 'hashlib', 'typing', 'pathlib',
                    'deadline_reward_v1', 'detection'}
    for mod in ('scheduler_state', 'detection'):
        tree = ast.parse((HERE / f'{mod}.py').read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        checks[f'{mod}_stdlib_siblings_only'] = imported <= (
            allowed_mods | {'stdlib'})
    checks['m1_events_untorn'] = not run['torn']

    all_pass = all(checks.values())
    detail['time_reconciliation'] = {
        u: {k: state.task_view(u)[k] for k in
            ('release_time', 'first_call_time', 'completion_time', 'e2e_s',
             'queue_wait_s', 'service_sum_s', 'switch_sum_s', 'other_wait_s')}
        for u in DEADLINES}
    detail['budget_reconciliation'] = state.budget()
    evidence = dict(milestone='M2', checks=checks, all_pass=all_pass,
                    zero_model_calls=True, detail=detail)
    (HERE / 'evidence' / 'M2_EVIDENCE.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'\n{sum(checks.values())}/{len(checks)} checks; '
          f'zero_model_calls=true; '
          f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')
    return 0 if all_pass else 2


def facts_empty_check(det, p):
    return det.facts_empty(p)


if __name__ == '__main__':
    with no_socket():
        raise SystemExit(main())
