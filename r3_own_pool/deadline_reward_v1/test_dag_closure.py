"""M3 acceptance tests — DAG closure & cache-reuse adjudication. Zero calls.

Covers the operator's eight M3 acceptance scenarios plus: production
CLOSURE parity, text-sameness ≠ identity (no reuse by answer text), the two
M3 hardening groups (server override key-existence incl. '' / malformed /
null; deep legal-view isolation), and determinism. M1/M2 suites unaffected.

Run: python3 -m deadline_reward_v1.test_dag_closure  (any CWD)
"""
from __future__ import annotations

import contextlib
import json
import socket as _socket_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from static_dag_v0.multidag_dynamic import CLOSURE as PROD_CLOSURE  # noqa: E402

from deadline_reward_v1 import dag_closure as dc  # noqa: E402
from deadline_reward_v1 import detection as det  # noqa: E402
from deadline_reward_v1.scheduler_state import (  # noqa: E402
    DONE, FAILED, PENDING, RUNNING, SchedulerState, make_legal_view)
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'm3_runs'
NODES_MODELS = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}

BASE = {
    ('e1', 'plain'): '{"facts": [{"value": 1.5, "evidence": "a"}]}',
    ('e2', 'plain'): '{"facts": [{"value": 2.5, "evidence": "b"}]}',
    ('r', 'plain'): '{"expression": "v0+v1"}',
    ('v', 'plain'): '{"value": 4.0}',
}


def make_tasks():
    def t(i, a, b):
        return dict(uid=f'm1t{i}', question=f'What is {a} + {b}?',
                    derivation=f'{a}+{b}', answer=a + b,
                    ctx_table=f'TABLE: | val | {a} |',
                    ctx_text=f'PASSAGES: value is {b}')
    return [t(0, 1.5, 2.5), t(1, 3.0, 4.0)]


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


def run_state(dirname, overrides=None):
    tasks = make_tasks()
    answers = dict(BASE)
    answers.update(overrides or {})
    server = StubModelServer(answers, PRIORS, seed='m3')
    clock = InjectedClock()
    engine = StubEngine(RUNS_DIR / dirname, server, clock, seed='m3',
                        profile_key='v3_compat')
    state = SchedulerState(clock, task_deadlines={t['uid']: 100.0
                                                  for t in tasks},
                           token_allocation=4000.0)
    state.attach(engine)
    engine.run_panel(tasks, NODES_MODELS)
    return state, server


def main():
    import shutil
    shutil.rmtree(RUNS_DIR, ignore_errors=True)  # idempotent re-runs
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    checks = {}
    samples = {}

    # --- structure parity vs production ----------------------------------
    checks['closure_parity_production'] = (
        dc.CLOSURE == {k: tuple(v) for k, v in PROD_CLOSURE.items()})
    checks['topo_valid'] = all(
        p in dc.TOPO[:dc.TOPO.index(n)] for n in dc.TOPO
        for p in dc.PARENTS[n])
    checks['descendants_transitive'] = (
        dc.descendants(['e1']) == {'r', 'v'}
        and dc.descendants(['r']) == {'v'} and dc.descendants(['v']) == set())

    state, server = run_state('main')
    # m1t0 completed cleanly: all DONE with frozen exec identities
    checks['state_all_done'] = all(
        state.task_view('m1t0')['node_status'][n] == DONE for n in dc.NODES)

    # --- S1: e1 re-exec with model change, r/v DONE ⇒ both invalidated ----
    j_rej = state.judge('m1t0', R=['e1'], pi={'e1': 'coder'})
    checks['s1_reject_incomplete'] = (
        not j_rej.legal and j_rej.invalidated == ('r', 'v')
        and any('incomplete_closure_missing:r,v' == r for r in j_rej.reasons))
    j_com = state.judge('m1t0', R=['e1'], pi={'e1': 'coder'},
                        on_incomplete='complete')
    checks['s1_complete_closure'] = (
        j_com.legal
        and j_com.execute == (('e1', True), ('r', True), ('v', True))
        and j_com.reuse == ('e2',)  # the unaffected branch stays reusable
        and any(r.startswith('closure_completed:r,v') for r in j_com.reasons))

    # --- S2: e1 re-exec, identity unchanged ⇒ cache hit, downstream reuse --
    j2 = state.judge('m1t0', R=['e1'], pi={})
    checks['s2_identity_unchanged_reuse'] = (
        j2.legal and j2.execute == (('e1', False),)
        and j2.reuse == ('e2', 'r', 'v')
        and any('reexec_identity_unchanged_cache_hit:e1' in r
                for r in j2.reasons))

    # --- S3: r re-exec with model change ⇒ v invalidated -------------------
    j3 = state.judge('m1t0', R=['r'], pi={'r': 'large'})
    checks['s3_v_invalidated'] = (
        not j3.legal and j3.invalidated == ('v',)
        and any('incomplete_closure_missing:v' == r for r in j3.reasons))
    # transitive: e1 change invalidates r AND v (complete mode executes all)
    j3b = state.judge('m1t0', R=['e1'], pi={'e1': 'medium'},
                      on_incomplete='complete')
    checks['s3_transitive_invalidation'] = (
        j3b.legal and ('r', True) in j3b.execute and ('v', True) in j3b.execute)

    # --- S4: only v model change (PENDING) ⇒ e1/e2/r reused ----------------
    # build a state where v is still PENDING: replay prefix before v calls
    events, _ = load_ledger(RUNS_DIR / 'main' / 'TASK_LEDGER.jsonl')
    pre_idx = max(i for i, e in enumerate(events)
                  if e.get('event') == 'call' and e['task'] == 'm1t0'
                  and e['node'] == 'r') + 1
    pre = SchedulerState.replay(
        events[:pre_idx], clock=InjectedClock(50.0),
        task_deadlines={'m1t0': 100.0, 'm1t1': 100.0}, token_allocation=4000.0)
    j4 = pre.judge('m1t0', R=[], pi={'v': 'large'})
    checks['s4_downstream_only_reuse'] = (
        j4.legal and j4.execute == (('v', True),)
        and j4.reuse == ('e1', 'e2', 'r'))

    # --- S5: DONE node model change without re-exec ⇒ reject ---------------
    j5 = state.judge('m1t0', R=[], pi={'e1': 'coder'})
    checks['s5_done_immutable'] = (
        not j5.legal
        and j5.reasons == ('done_node_model_change_without_reexec:e1',))

    # --- S6: RUNNING node touched by R or π ⇒ reject ------------------------
    r_start = next(i for i, e in enumerate(events)
                   if e.get('event') == 'call_start' and e['task'] == 'm1t0'
                   and e['node'] == 'r')
    mid = SchedulerState.replay(
        events[:r_start + 1], clock=InjectedClock(50.0),
        task_deadlines={'m1t0': 100.0, 'm1t1': 100.0}, token_allocation=4000.0)
    j6a = mid.judge('m1t0', R=['r'], pi={})
    j6b = mid.judge('m1t0', R=[], pi={'r': 'large'})
    checks['s6_running_immutable'] = (
        not j6a.legal and j6a.reasons == ('running_in_R:r',)
        and not j6b.legal
        and j6b.reasons == ('running_node_immutable:r',))

    # --- S7: text-same ≠ identity (no reuse by answer text) ----------------
    # same answer TEXT would come back, but a different model means a
    # different frozen cache identity ⇒ still a change, still invalidation.
    j7 = state.judge('m1t0', R=['e1'], pi={'e1': 'medium'})
    checks['s7_text_same_not_identity'] = (
        not j7.legal and j7.invalidated == ('r', 'v')
        and any('model_change:e1' in r for r in j7.reasons))

    # --- S8: determinism -----------------------------------------------------
    checks['s8_deterministic'] = (
        state.judge('m1t0', R=['e1'], pi={'e1': 'coder'})
        == state.judge('m1t0', R=['e1'], pi={'e1': 'coder'}))

    # unknown model / node rejections
    checks['unknown_model_rejected'] = not state.judge(
        'm1t0', R=['e1'], pi={'e1': 'gpt-9'}).legal
    checks['unknown_node_rejected'] = not dc.evaluate_plan(
        node_status={n: DONE for n in dc.NODES},
        node_model=NODES_MODELS, exec_identity={}, R=['e9'], pi={}).legal

    # --- M3 errata (operator review): four boundary fixes + hardening ---
    def hc(status_over, ident_builder):
        ns = {'e1': DONE, 'e2': DONE, 'r': DONE, 'v': DONE}
        ns.update(status_over)
        ei = ident_builder(ns)
        return ns, ei

    ctx_a = dc.ctx_signatures({'ctx_table': 'TABLE A', 'ctx_text': 'TXT A'})
    ctx_b = dc.ctx_signatures({'ctx_table': 'TABLE B', 'ctx_text': 'TXT A'})
    base_ans = {'e1': BASE[('e1', 'plain')], 'e2': BASE[('e2', 'plain')],
                'r': BASE[('r', 'plain')], 'v': BASE[('v', 'plain')]}

    def ident_all(uid, ctx, answers):
        return {n: (NODES_MODELS[n], dc.input_signature(uid, n, ctx,
                                                        answers))
                for n in dc.NODES}

    NM = dict(NODES_MODELS)

    # F1: FAILED e1, same model + same inputs requested as recovery —
    # must NOT be a success cache hit; retry = a real new attempt.
    ns1, ei1 = hc({'e1': FAILED}, lambda ns: ident_all('u', ctx_a, base_ans))
    jf1 = dc.evaluate_plan(node_status=ns1, node_model=NM, exec_identity=ei1,
                           R=['e1'], pi={}, on_incomplete='complete',
                           uid='u', current_ctx_sha=ctx_a,
                           parent_answers=base_ans)
    checks['f1_failed_retry_not_cache_hit'] = (
        jf1.legal and ('e1', True) in jf1.execute
        and ('e1', False) not in jf1.execute
        and 'failed_retry_new_call:e1' in jf1.reasons)
    jf1d = dc.evaluate_plan(node_status=ns1, node_model=NM, exec_identity=ei1,
                            R=['e1'], pi={}, uid='u',
                            current_ctx_sha=ctx_a, parent_answers=base_ans)
    checks['f1_failed_retry_invalidates_downstream'] = (
        not jf1d.legal and jf1d.invalidated == ('r', 'v'))

    # F2: FAILED r, same-model retry — never reuse the failed result.
    ns2, ei2 = hc({'r': FAILED}, lambda ns: ident_all('u', ctx_a, base_ans))
    jf2 = dc.evaluate_plan(node_status=ns2, node_model=NM, exec_identity=ei2,
                           R=['r'], pi={}, on_incomplete='complete',
                           uid='u', current_ctx_sha=ctx_a,
                           parent_answers=base_ans)
    checks['f2_failed_r_not_reused'] = (
        jf2.legal and ('r', True) in jf2.execute
        and 'failed_retry_new_call:r' in jf2.reasons
        and 'r' not in jf2.reuse
        and 'failed_node_not_recovered' not in ','.join(jf2.reasons))

    # F3: r RUNNING while e1 changes model ⇒ whole plan rejected.
    ns3, ei3 = hc({'r': RUNNING, 'v': PENDING},
                  lambda ns: ident_all('u', ctx_a, base_ans))
    jf3 = dc.evaluate_plan(node_status=ns3, node_model=NM, exec_identity=ei3,
                           R=['e1'], pi={'e1': 'coder'}, uid='u',
                           current_ctx_sha=ctx_a, parent_answers=base_ans)
    checks['f3_running_r_invalidated_rejected'] = (
        not jf3.legal
        and jf3.reasons[-1] == 'running_downstream_invalidated:r')
    jf3c = dc.evaluate_plan(node_status=ns3, node_model=NM, exec_identity=ei3,
                            R=[], pi={'v': 'large'}, uid='u',
                            current_ctx_sha=ctx_a, parent_answers=base_ans)
    checks['f3_control_unrelated_plan_legal'] = jf3c.legal

    # F4: v RUNNING while r changes model ⇒ rejected.
    ns4, ei4 = hc({'v': RUNNING}, lambda ns: ident_all('u', ctx_a, base_ans))
    jf4 = dc.evaluate_plan(node_status=ns4, node_model=NM, exec_identity=ei4,
                           R=['r'], pi={'r': 'large'}, uid='u',
                           current_ctx_sha=ctx_a, parent_answers=base_ans)
    checks['f4_running_v_invalidated_rejected'] = (
        not jf4.legal
        and jf4.reasons[-1] == 'running_downstream_invalidated:v')

    # F5/F6: frozen per-node model menus.
    ns5, ei5 = hc({}, lambda ns: ident_all('u', ctx_a, base_ans))
    jf5 = dc.evaluate_plan(node_status=ns5, node_model=NM, exec_identity=ei5,
                           R=['r'], pi={'r': 'coder'}, uid='u',
                           current_ctx_sha=ctx_a, parent_answers=base_ans)
    jf6 = dc.evaluate_plan(node_status=ns5, node_model=NM, exec_identity=ei5,
                           R=['v'], pi={'v': 'medium'}, uid='u',
                           current_ctx_sha=ctx_a, parent_answers=base_ans)
    checks['f5_r_coder_off_menu'] = (
        not jf5.legal and jf5.reasons == ('model_off_menu:r:coder',))
    checks['f6_v_medium_off_menu'] = (
        not jf6.legal and jf6.reasons == ('model_off_menu:v:medium',))

    # F7: same uid, different static context ⇒ identity changes; same
    # context ⇒ genuine cache hit.
    jf7b = dc.evaluate_plan(node_status=ns5, node_model=NM, exec_identity=ei5,
                            R=['e1'], pi={}, uid='u',
                            current_ctx_sha=ctx_b, parent_answers=base_ans)
    jf7b_c = dc.evaluate_plan(node_status=ns5, node_model=NM,
                              exec_identity=ei5, R=['e1'], pi={},
                              on_incomplete='complete', uid='u',
                              current_ctx_sha=ctx_b, parent_answers=base_ans)
    jf7a = dc.evaluate_plan(node_status=ns5, node_model=NM, exec_identity=ei5,
                            R=['e1'], pi={}, uid='u',
                            current_ctx_sha=ctx_a, parent_answers=base_ans)
    checks['f7_ctx_change_breaks_identity'] = (
        not jf7b.legal and jf7b.invalidated == ('r', 'v')
        and 'input_identity_changed:e1' in jf7b.reasons
        and jf7b_c.legal and ('e1', True) in jf7b_c.execute)
    checks['f7_same_ctx_cache_hit'] = (
        jf7a.legal and ('e1', False) in jf7a.execute)

    # F8: signature determinism under identical context + history.
    checks['f8_signature_deterministic'] = (
        dc.input_signature('u', 'r', ctx_a, base_ans)
        == dc.input_signature('u', 'r', ctx_a, dict(base_ans)))

    # F9: illegal on_incomplete rejected AT ENTRY (even without any
    # invalidation to trigger the old late check).
    try:
        dc.evaluate_plan(node_status=ns5, node_model=NM, exec_identity=ei5,
                         R=[], pi={}, on_incomplete='sometimes', uid='u',
                         current_ctx_sha=ctx_a, parent_answers=base_ans)
        checks['f9_on_incomplete_entry_validated'] = False
    except ValueError:
        checks['f9_on_incomplete_entry_validated'] = True

    # --- M3 errata 2: ctx drift on REUSED (non-executed) DONE nodes -------
    # Same uid, ctx A->B, R=[]: the stale e1 cache must NOT be reusable.
    # (The check exists at HEAD; the reviewer's baseline 4937789 predated
    # it — these tests pin it permanently.)
    ns_d = {n: DONE for n in dc.NODES}
    ei_d = {n: (NODES_MODELS[n], dc.input_signature('u', n, ctx_a,
                                                    base_ans))
            for n in dc.NODES}
    jd_rej = dc.evaluate_plan(node_status=ns_d, node_model=dict(NODES_MODELS),
                              exec_identity=ei_d, R=[], pi={}, uid='u',
                              current_ctx_sha=ctx_b,
                              parent_answers=base_ans)
    checks['f10_ctx_drift_r_empty_rejects_old_cache'] = (
        not jd_rej.legal
        and jd_rej.invalidated == ('e1', 'r', 'v')
        and 'input_identity_changed:e1' in jd_rej.reasons
        and jd_rej.reuse == ())
    jd_com = dc.evaluate_plan(node_status=ns_d, node_model=dict(NODES_MODELS),
                              exec_identity=ei_d, R=[], pi={}, uid='u',
                              current_ctx_sha=ctx_b,
                              parent_answers=base_ans,
                              on_incomplete='complete')
    checks['f11_ctx_drift_r_empty_complete_repairs'] = (
        jd_com.legal
        and jd_com.execute == (('e1', True), ('r', True), ('v', True))
        and jd_com.reuse == ('e2',)
        and any(r.startswith('closure_completed:e1,r,v')
                for r in jd_com.reasons))

    # --- M3 final boundary (reviewer re-flag from baseline 4937789;
    # fix landed at 645258c): judge-level R=[] drift through REAL engine
    # state — all four nodes DONE, static ctx mutated, R=[] must REJECT
    # the stale e1 (and cascade r/v), complete-mode must repair ---
    from deadline_reward_v1.stub_engine import (InjectedClock as IC2,
                                                StubEngine as SE2,
                                                StubModelServer as SS2)
    t12 = dict(uid='jt0', question='q', derivation='d', answer=4.0,
               ctx_table='TABLE ORIGINAL', ctx_text='P')
    srv12 = SS2(dict(BASE), PRIORS, seed='jd')
    eng12 = SE2(RUNS_DIR / 'judge_drift_final', srv12, IC2(), seed='jd',
                profile_key='v3_compat')
    st12 = SchedulerState(IC2(), task_deadlines={'jt0': 100.0},
                          token_allocation=100000.0)
    st12.attach(eng12)
    NM12 = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
    eng12.start_panel([t12], NM12)
    eng12.run_jobs('A', eng12.planned_jobs([t12], NM12, ('e1', 'e2')))
    eng12.run_jobs('R1', eng12.planned_jobs([t12], NM12, ('r',)))
    eng12.run_jobs('V1', eng12.planned_jobs([t12], NM12, ('v',)))
    st12.tasks['jt0'].ctx_sha = dc.ctx_signatures(
        dict(t12, ctx_table='TABLE MUTATED'))
    j12r = st12.judge('jt0', R=[], pi={})
    j12c = st12.judge('jt0', R=[], pi={}, on_incomplete='complete')
    checks['f12_judge_level_r_empty_drift_rejected'] = (
        not j12r.legal and j12r.invalidated == ('e1', 'r', 'v')
        and 'input_identity_changed:e1' in j12r.reasons
        and j12r.reuse == ())
    checks['f13_judge_level_complete_repairs'] = (
        j12c.legal and j12c.execute == (('e1', True), ('r', True),
                                        ('v', True))
        and j12c.reuse == ('e2',))

    # --- hardening 1: server override key-existence ------------------------
    st_h, srv_h = run_state('hard_empty', {('m1t1', 'e1', 'plain'): ''})
    obs_empty = [o['code'] for o in st_h.task_view('m1t1')['observations']]
    checks['override_empty_string_respected'] = (
        obs_empty[:1] == [det.D1]
        and st_h.task_view('m1t1')['node_status']['e1'] == FAILED)
    st_m, srv_m = run_state('hard_malformed',
                            {('m1t1', 'r', 'plain'): 'not json'})
    obs_mal = [o['code'] for o in st_m.task_view('m1t1')['observations']]
    checks['override_malformed_json_d3'] = det.D3 in obs_mal
    st_n, srv_n = run_state('hard_null', {('m1t1', 'v', 'plain'):
                                          '{"value": null}'})
    obs_null = [o['code'] for o in st_n.task_view('m1t1')['observations']]
    checks['override_null_value_d5'] = det.D5 in obs_null

    # --- hardening 2: deep legal-view isolation ----------------------------
    deep_probes = [
        ('observations_nested_gold', dict(observations=[
            {'code': det.D1, 'node': 'e1', 't': 1.0, 'gold': 4.0}])),
        ('session_nested_future', dict(session={
            'switch_indices': [1], 'future_outputs': ['x']})),
        ('budget_nested_gold', dict(budget={'tokens_spent': 1, 'gold': 2})),
        ('observations_extra_key', dict(observations=[
            {'code': det.D1, 'node': 'e1', 't': 1.0, 'answer': 'leak'}])),
        ('observations_unknown_code', dict(observations=[
            {'code': 'D9_oracle', 'node': 'e1', 't': 1.0}])),
        ('node_status_bad_value', dict(node_status={'e1': 'GOLD'})),
        ('node_model_bad_key', dict(node_model={'e9': 'large'})),
    ]
    rejected = True
    for name, kw in deep_probes:
        try:
            make_legal_view(**kw)
            rejected = False
            print(f'  (deep probe NOT rejected: {name})')
        except ValueError:
            pass
    checks['deep_injection_rejected'] = rejected
    # a WELL-FORMED observation still passes the deep validator
    try:
        make_legal_view(observations=[
            {'code': det.D1, 'node': 'e1', 't': 1.0}])
        well_formed_ok = True
    except ValueError:
        well_formed_ok = False
    checks['well_formed_view_accepted'] = well_formed_ok
    # real constructed views still pass the deep validator
    checks['real_views_pass_deep_check'] = all(
        isinstance(state.task_view(u), dict) for u in ('m1t0', 'm1t1'))

    # --- zero-call ----------------------------------------------------------
    total_invocations = (server.invocations + srv_h.invocations
                         + srv_m.invocations + srv_n.invocations)
    checks['z1_counts'] = total_invocations == 4 * 8  # 4 runs x 8 calls

    all_pass = all(checks.values())
    samples['s1_complete'] = dict(
        legal=j_com.legal, execute=list(j_com.execute),
        reuse=list(j_com.reuse), reasons=list(j_com.reasons))
    samples['s2_cache_hit'] = dict(
        legal=j2.legal, execute=list(j2.execute), reuse=list(j2.reuse),
        reasons=list(j2.reasons))
    evidence = dict(milestone='M3', checks=checks, all_pass=all_pass,
                    zero_model_calls=True, judgment_samples=samples)
    (HERE / 'evidence' / 'M3_EVIDENCE.json').write_text(
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
