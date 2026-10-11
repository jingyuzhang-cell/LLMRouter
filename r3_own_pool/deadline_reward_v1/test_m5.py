"""M5 formal-acceptance suite — dynamic node-level model reassignment.

ZERO M6 imports (no policy / predictor / compensator / reward): this file
exercises ONLY the M5 machinery — `reassign.enumerate_candidates` (legal
(Z, R, pi) generation over frozen menus, M3-adjudicated) and
`reassign.apply_decision` (faithful execution through the M1 engine) —
plus the engine/state from M1–M4.

The decisive scenario (V10-M5) fixes ONE task, ONE fault observation, ONE
node/cache/cost state and varies ONLY the remaining-time regime; a
TEST-LOCAL selection rule (NOT the M6 policy) picks a legal candidate per
regime (loose -> highest-quality models, tight -> fastest models, from
the synthetic priors). M5 must apply and REALLY EXECUTE different legal
pi per regime, with ledger models == pi exactly. The A/B/C quality /
deadline filtering and the final 'choose B' decision are M6 and are
deliberately NOT tested here.

Run: python3 -m deadline_reward_v1.test_m5  (any CWD)
"""
from __future__ import annotations

import ast
import contextlib
import copy
import json
import socket as _socket_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import dag_closure as dc  # noqa: E402
from deadline_reward_v1 import reassign  # noqa: E402
from deadline_reward_v1.scheduler_state import (  # noqa: E402
    DONE, FAILED, PENDING, RUNNING, SchedulerState)
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'm5_runs'
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
    return dict(uid=f'qt{i}', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table=f'TABLE: | val | 1.5 |',
                ctx_text=f'PASSAGES: value is 2.5 ({i})')


def planned_state(dirname, tasks, *, fault_uid=None):
    """Drive planned A + R1 through a REAL engine/state (M1/M2), then stop
    at the decision point — no M6 orchestration involved."""
    server = StubModelServer(dict(ANSWERS), PRIORS, seed='m5')
    if fault_uid:
        server.set_fault(fault_uid, 'e1', 'large', '{"facts": []}')
    engine = StubEngine(RUNS_DIR / dirname, server, InjectedClock(),
                        seed='m5', profile_key='golden_zero')
    state = SchedulerState(
        InjectedClock(), task_deadlines={t['uid']: 100.0 for t in tasks},
        token_allocation=100000.0)
    state.attach(engine)
    engine.start_panel(tasks, NODES_MODELS)
    engine.run_jobs('A', engine.planned_jobs(tasks, NODES_MODELS,
                                             ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs(tasks, NODES_MODELS, ('r',)))
    return engine, state, server


def time_rule(cands, regime, uid_state):
    """TEST-LOCAL selection rule (explicitly NOT the M6 policy): loose ->
    highest q_success per free node; tight -> lowest lat_mean; ties by
    (q desc / lat asc, then model name). Returns the chosen Candidate."""
    prof = PRIORS['node_profiles']
    best, best_key = None, None
    for c in cands:
        if c.arm != 'LOCAL':
            continue
        score = []
        for node, model in c.pi.items():
            p = prof[f'{node}|{model}']
            score.append((p['q_success'], -p['lat_mean_s'])
                         if regime == 'loose'
                         else (-p['lat_mean_s'], p['q_success']))
        key = (sum(s[0] for s in score), sum(s[1] for s in score),
               tuple(sorted(c.pi.items())))
        if best_key is None or key > best_key:
            best, best_key = c, key
    return best


def execute_plan(engine, state, t, chosen, dec_idx):
    """M5 execution closure: apply non-PENDING retries, then run the
    pending V1 stage under the chosen pi (exactly what the mainline
    prescribes for first executions)."""
    reassign.apply_decision(engine, state, t, NODES_MODELS, chosen)
    v_model = chosen.pi.get('v') or NODES_MODELS['v']
    engine.run_jobs('V1', [dict(task=t, node='v', kind='plain',
                                model=v_model)])
    engine.write_task_summaries([t])
    events, torn = load_ledger(engine.ledger_path)
    return events[dec_idx:], torn


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

    # ============ decisive scenario: ONE fault, TWO time regimes =========
    plans = {}
    for regime in ('loose', 'tight'):
        t = task(0)
        engine, state, server = planned_state(f'v10m5_{regime}', [t],
                                              fault_uid='qt0')
        st = state.tasks['qt0']
        assert st.node_status['e1'] == FAILED and \
            st.node_status['v'] == PENDING
        dec_idx = engine.n_events
        cands = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
        chosen = time_rule(cands, regime, st)
        post, torn = execute_plan(engine, state, t, chosen, dec_idx)
        calls = [e for e in post if e['event'] == 'call']
        plans[regime] = dict(chosen=chosen, calls=calls, post=post,
                             state=state, torn=torn, server=server)

    loose, tight = plans['loose'], plans['tight']
    # different legal pi under different remaining-time regimes
    checks['m5_v10_pi_differs_by_time'] = (
        loose['chosen'].pi != tight['chosen'].pi
        and loose['chosen'].pi['v'] == 'large'
        and tight['chosen'].pi['v'] == 'coder')
    # evidence-consistency guard (errata task 3): the e1 models are
    # TIE-BROKEN by the declared rule (q equal 0.99; coder/medium lat
    # equal 0.8; pi-tuple ordering) — the WINNER is 'medium' in both
    # regimes; the acceptance text previously mis-copied 'coder'.
    checks['m5_v10_pi_matches_rule'] = (
        loose['chosen'].pi['e1'] == 'medium'
        and tight['chosen'].pi['e1'] == 'medium')
    # ledger models == chosen pi EXACTLY (c1: pi reaches physical calls)
    def models_of(regime):
        return {c['node']: c['model'] for c in plans[regime]['calls']}
    ml, mt = models_of('loose'), models_of('tight')
    checks['m5_c1_pi_reaches_physical_calls'] = (
        all(ml[n] == loose['chosen'].pi[n]
            for n in ml if n in loose['chosen'].pi)
        and all(mt[n] == tight['chosen'].pi[n]
                for n in mt if n in tight['chosen'].pi)
        and set(ml) == {'e1', 'r', 'v'}          # e2 correctly REUSED
        and set(mt) == {'e1', 'r', 'v'})
    # closure + cache identity (c7): e1 retry invalidated r and v (new
    # calls), e2's frozen identity unchanged -> NO new e2 call anywhere
    # after the decision
    for regime in ('loose', 'tight'):
        assert not any(c['node'] == 'e2' for c in plans[regime]['calls'])
    checks['m5_c7_closure_and_cache_identity'] = True
    # FAILED real retry (c5): e1 retried as a REAL charged call on the
    # chosen alternative model (fault keyed on large does not re-fire)
    e1_calls = {r: [c for c in plans[r]['calls'] if c['node'] == 'e1'][0]
                for r in ('loose', 'tight')}
    checks['m5_c5_failed_real_retry'] = (
        all(c['physical'] and not c['cached'] and not c['injected']
            for c in e1_calls.values())
        and e1_calls['loose']['model'] == loose['chosen'].pi['e1']
        and e1_calls['tight']['model'] == tight['chosen'].pi['e1'])
    # cost attribution (c8): 3 new calls x 100 tokens post-decision
    checks['m5_c8_ledgers_and_costs'] = all(
        sum(c['usage']['total_tokens'] for c in plans[r]['calls']
            if c['physical']) == 300.0
        and any(e['event'] == 'switch' for e in plans[r]['post'])
        and any(e['event'] == 'task_summary' for e in plans[r]['post'])
        and not plans[r]['torn']
        for r in ('loose', 'tight'))
    det['v10'] = dict(loose_pi=loose['chosen'].pi,
                      tight_pi=tight['chosen'].pi,
                      loose_models=models_of('loose'),
                      tight_models=models_of('tight'))

    # ============ c2: per-task models differ on the same node ===========
    ta, tb = task(1), task(2)
    engine, state, server = planned_state('pertask', [ta, tb],
                                          fault_uid='qt1')
    # fault only qt1 so qt2 has no LOCAL arm; drive qt1 LOOSE (v=large)
    # while qt2's planned v stays coder -> same node v, different models
    # in one batched V1 stage
    cands = reassign.enumerate_candidates(state, 'qt1', NODES_MODELS)
    chosen_t = time_rule(cands, 'loose', state.tasks['qt1'])
    dec_idx = engine.n_events
    reassign.apply_decision(engine, state, ta, NODES_MODELS, chosen_t)
    engine.run_jobs('V1', [dict(task=ta, node='v', kind='plain',
                                model=chosen_t.pi['v']),
                           dict(task=tb, node='v', kind='plain',
                                model=NODES_MODELS['v'])])
    events, _ = load_ledger(engine.ledger_path)
    v_calls = [e for e in events[dec_idx:] if e['event'] == 'call'
               and e['node'] == 'v']
    checks['m5_c2_per_task_models_same_node'] = (
        len(v_calls) == 2
        and {c['task']: c['model'] for c in v_calls}[
            'qt1'] == chosen_t.pi['v']
        and {c['task']: c['model'] for c in v_calls}['qt2']
        == NODES_MODELS['v']
        and chosen_t.pi['v'] != NODES_MODELS['v'])

    # ============ c3/c4/c6: legality via the enumeration path ===========
    engine, state, _ = planned_state('legality', [task(0)],
                                     fault_uid='qt0')
    cands = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
    # c6: menus strictly enforced across every enumerated candidate
    checks['m5_c6_menus_enforced'] = all(
        m in dc.MENUS[n] for c in cands for n, m in c.pi.items())
    # c3: with all nodes DONE except the failed one, no candidate may
    # rebind a DONE node unless it re-executes it
    done_state = state.tasks['qt0']
    checks['m5_c3_done_rebind_needs_reexec'] = all(
        n in dict(c.judgment.execute)
        for c in cands for n in c.pi
        if done_state.node_status.get(n) == DONE)
    # c4: RUNNING nodes never appear in any candidate's execute set
    st4 = state.tasks['qt0']
    st4.node_status['r'] = RUNNING
    cands4 = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
    checks['m5_c4_running_protected'] = all(
        st4.node_status.get(n) != RUNNING or new_call is False
        for c in cands4 for n, new_call in c.judgment.execute) and \
        all('r' not in c.pi or c.judgment.legal is False
            for c in cands4 if not c.judgment.legal) and \
        all(st4.node_status.get(n) != RUNNING
            for c in cands4 if c.judgment.legal
            for n, _ in c.judgment.execute)

    # ============ c9: legal-view isolation (structural + import graph) ==
    dump = json.dumps([{ 'arm': c.arm, 'pi': c.pi, 'kinds': c.kinds}
                       for c in cands])
    checks['m5_c9_no_illegal_payloads'] = (
        'gold' not in dump and 'fault' not in dump
        and GOOD_E1 not in dump and GOOD_V not in dump)
    tree = ast.parse((HERE / 'reassign.py').read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split('.')[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split('.')[0])
    checks['m5_c9_module_isolation'] = imported <= {
        '__future__', 'itertools', 'dataclasses', 'typing',
        'deadline_reward_v1', 'dag_closure'}

    # ============ Task 1: REAL time-state input boundary ================
    # Same task, same fault, same history/costs; only the DEADLINE
    # differs -> state.d_remain differs at the decision point. The M5
    # machinery (enumerate + apply) is deliberately TIME-INVARIANT: it
    # must return/execute the SAME candidate set under both deadlines —
    # filtering/selection by d_remain is M6, and this test local rule is
    # NOT wrapped as a policy (it never reads d_remain).
    cands_by_d = {}
    for deadline in (30.0, 200.0):
        t = task(0)
        server = StubModelServer(dict(ANSWERS), PRIORS, seed='m5')
        server.set_fault('qt0', 'e1', 'large', '{"facts": []}')
        clock = InjectedClock()
        engine = StubEngine(RUNS_DIR / f'dvar_{deadline}', server, clock,
                            seed='m5', profile_key='golden_zero')
        state = SchedulerState(clock,
                               task_deadlines={'qt0': deadline},
                               token_allocation=100000.0)
        state.attach(engine)
        engine.start_panel([t], NODES_MODELS)
        engine.run_jobs('A', engine.planned_jobs([t], NODES_MODELS,
                                                 ('e1', 'e2')))
        engine.run_jobs('R1', engine.planned_jobs([t], NODES_MODELS,
                                                  ('r',)))
        d_rem = state.d_remain('qt0')
        cands = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
        cands_by_d[deadline] = (d_rem, sorted(
            (c.arm, tuple(sorted(c.pi.items())),
             tuple(c.judgment.execute))
            for c in cands))
    (d_tight, sig_t) = cands_by_d[30.0]
    (d_loose, sig_l) = cands_by_d[200.0]
    rule_reads_time = 'd_remain' in time_rule.__code__.co_names or \
        'd_remain' in time_rule.__code__.co_varnames
    checks['m5_t1_deadline_varies_d_remain'] = (
        d_tight < d_loose and abs(d_loose - d_tight - 170.0) < 1e-9)
    checks['m5_t1_machinery_time_invariant'] = sig_t == sig_l
    checks['m5_t1_rule_not_a_policy'] = not rule_reads_time
    det['t1'] = dict(d_remain_tight=d_tight, d_remain_loose=d_loose,
                     n_candidates=len(sig_t))

    # ============ Task 2: static vs dynamic FULL ========================
    engine, state, _ = planned_state('fulldyn', [task(0)],
                                     fault_uid='qt0')
    cands = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
    stat = [c for c in cands if c.arm == 'FULL']
    dyn = [c for c in cands if c.arm == 'FULL_DYNAMIC']
    # static E-arm: NON-TRIGGER nodes (not in the failed set) pinned to
    # PLANNED models; trigger nodes (here e1 AND the cascaded-D3 r) take
    # menu variants exactly as recovery_plans prescribes
    failed_nodes = {n for n in dc.TOPO
                    if state.tasks['qt0'].node_status[n] == FAILED}
    checks['m5_t2_static_full_pins_planned'] = (
        len(stat) > 0
        and all(c.pi[n] == NODES_MODELS[n]
                for c in stat for n in dc.TOPO if n not in failed_nodes)
        and all(c.pi[n] in dc.MENUS[n]
                for c in stat for n in failed_nodes))
    # dynamic FULL: r and v may legally differ from the planned models,
    # everything still menu-legal and judged legal
    alt = [c for c in dyn if c.pi.get('r') != NODES_MODELS['r']
           or c.pi.get('v') != NODES_MODELS['v']]
    checks['m5_t2_dynamic_full_reassigns_downstream'] = (
        len(dyn) > 1 and len(alt) > 0
        and all(c.judgment.legal for c in alt)
        and all(m in dc.MENUS[n] for c in alt for n, m in c.pi.items()))
    # execute one dynamic FULL candidate: ledger models == pi on ALL
    # nodes; changed/fresh nodes are REAL charged calls, while an
    # identity-UNCHANGED node may legally ALIAS (the cost-saving
    # distinction vs the static E-arm's forced re-execution)
    chosen_dyn = alt[0]
    t = task(0)
    dec_idx = engine.n_events
    reassign.apply_whole_plan(engine, state, t, NODES_MODELS, chosen_dyn)
    events, _ = load_ledger(engine.ledger_path)
    post_calls = [e for e in events[dec_idx:] if e['event'] == 'call']
    exec_map = {c['node']: c['model'] for c in post_calls}
    by_node = {c['node']: c for c in post_calls}
    checks['m5_t2_dynamic_full_executes_pi'] = (
        exec_map == {n: chosen_dyn.pi[n] for n in ('e1', 'e2', 'r', 'v')}
        and by_node['e1']['physical'] and by_node['r']['physical']
        and by_node['v']['physical']
        and (by_node['e2']['cached'] or by_node['e2']['physical']))

    # ============ Task 4: unified entry prevents model fallback ========
    engine, state, _ = planned_state('unified', [task(0)],
                                     fault_uid='qt0')
    cands = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
    chosen = time_rule(cands, 'loose', state.tasks['qt0'])
    t = task(0)
    dec_idx = engine.n_events
    used = reassign.apply_whole_plan(engine, state, t, NODES_MODELS,
                                     chosen)
    events, _ = load_ledger(engine.ledger_path)
    post_calls = [e for e in events[dec_idx:] if e['event'] == 'call']
    exec_models = {c['node']: c['model'] for c in post_calls}
    checks['m5_t4_no_fallback_to_planned'] = (
        used['v'] == chosen.pi['v']
        and exec_models.get('v') == chosen.pi['v']
        and exec_models.get('v') != NODES_MODELS['v']
        and exec_models.get('r') == chosen.pi.get(
            'r', NODES_MODELS['r']))

    # ============ final enum-gap fix: DONE non-FAILED nodes are FREE ====
    # Reviewer's decisive state: e1 FAILED, e2 DONE, r DONE, v PENDING
    # (built on a REAL engine run: planned A+R1 clean, then e1 flagged
    # FAILED at state level — M5 tests reassignment, not corruption).
    t = task(0)
    server = StubModelServer(dict(ANSWERS), PRIORS, seed='m5')
    engine = StubEngine(RUNS_DIR / 'gapfix', server, InjectedClock(),
                        seed='m5', profile_key='golden_zero')
    state = SchedulerState(InjectedClock(),
                           task_deadlines={'qt0': 100.0},
                           token_allocation=100000.0)
    state.attach(engine)
    engine.start_panel([t], NODES_MODELS)
    engine.run_jobs('A', engine.planned_jobs([t], NODES_MODELS, ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs([t], NODES_MODELS, ('r',)))
    st_g = state.tasks['qt0']
    st_g.node_status['e1'] = FAILED          # the flagged fault
    st_g.observations.append(dict(code='D1_e_empty', node='e1', t=0.0))
    cands = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
    dyn_r = {c.pi['r'] for c in cands if c.arm == 'FULL_DYNAMIC'}
    stat_r = {c.pi['r'] for c in cands if c.arm == 'FULL'}
    checks['m5_g1_dynamic_covers_done_nodes'] = (
        {'medium', 'large'} <= dyn_r and stat_r == {'medium'})
    # all dynamic candidates still fully menu-legal and judged legal
    checks['m5_g1_all_legal'] = all(
        c.judgment.legal
        and all(m in dc.MENUS[n] for n, m in c.pi.items())
        for c in cands if c.arm == 'FULL_DYNAMIC')
    # RUNNING rejection (no silent rebinding): r RUNNING -> every FULL
    # and FULL_DYNAMIC candidate contains r in R -> judge rejects all;
    # NONE candidates never carry r in pi
    st_g.node_status['r'] = RUNNING
    cands_run = reassign.enumerate_candidates(state, 'qt0', NODES_MODELS)
    checks['m5_g1_running_rejected_not_rebound'] = (
        not any(c.arm in ('FULL', 'FULL_DYNAMIC') for c in cands_run)
        and all('r' not in c.pi for c in cands_run))
    st_g.node_status['r'] = DONE

    # execute a FULL_DYNAMIC candidate with r switched OFF the planned
    # model: ledger r model == pi; new calls cost/latency metered
    # pick a candidate that switches r OFF the planned model; whatever
    # it does with e1/e2/v, the ledger must match ITS pi on every node
    alt_r = next(c for c in cands if c.arm == 'FULL_DYNAMIC'
                 and c.pi['r'] == 'large')
    dec_idx = engine.n_events
    reassign.apply_whole_plan(engine, state, t, NODES_MODELS, alt_r)
    events, _ = load_ledger(engine.ledger_path)
    post = [e for e in events[dec_idx:] if e['event'] == 'call']
    r_call = next(c for c in post if c['node'] == 'r')
    checks['m5_g1_executes_r_reassignment'] = (
        r_call['model'] == 'large' and r_call['physical']
        and not r_call['cached']
        and r_call['usage']['total_tokens'] == 100
        and r_call['latency_s'] >= 0
        and {c['node']: c['model'] for c in post}
        == {n: alt_r.pi[n] for n in ('e1', 'e2', 'r', 'v')})

    # ============ zero-call sentinel =====================================
    # sentinel over the FULL ledgers (planned + post-decision): the
    # server is invoked exactly once per physical call, nothing else
    total_invocations = sum(p['server'].invocations for p in plans.values())
    total_physical = sum(
        1 for r in ('loose', 'tight')
        for e in load_ledger(RUNS_DIR / f'v10m5_{r}' / 'TASK_LEDGER.jsonl')[0]
        if e['event'] == 'call' and e['physical'])
    checks['m5_z1_sentinel'] = total_invocations == total_physical

    all_pass = all(checks.values())
    evidence = dict(milestone='M5-acceptance', checks=checks,
                    all_pass=all_pass, zero_model_calls=True,
                    detail=det,
                    note='decisive scenario uses a TEST-LOCAL time rule; '
                         'M6 scoring/filtering deliberately absent')
    (HERE / 'evidence' / 'M5_EVIDENCE.json').write_text(
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
