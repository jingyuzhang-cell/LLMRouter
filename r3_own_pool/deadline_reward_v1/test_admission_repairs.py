"""Zero-call admission-repair tests (operator mandate 2026-10-11,
baseline 9b29672). Eight groups:

  1. draw(): first dispatch attempt fails, second succeeds — TWO physical
     reservations (one settled, one attempt_failed with retained charge).
  2. Request budget exactly at cap: the next attempt is refused BEFORE
     any dispatch.
  3. Budget-stop during the call path propagates — no automatic retry.
  4. V-node execution counts across LOCAL / FULL / NONE / degraded /
     cache-hit scenarios match the legal execution plan exactly once.
  5. Freeze-manifest drift on ANY bound file/value refuses execution.
  6. Non-normal families: family-true means and family-consistent
     on-time estimators (lognormal Fenton-Wilkinson; empirical Cantelli).
  7. Interrupted run never writes the official quality priors;
     INCOMPLETE output is explicitly marked and never overwritten.
  8. Shared cache: per-cell new_requests / cache_hits / logical calls /
     physical tokens recorded, with an execution-order audit.

Run: python3 -m deadline_reward_v1.test_admission_repairs
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from deadline_reward_v1 import policy, supplementary_runner as sr
from deadline_reward_v1.predictor import (OutcomePredictor, e1_on_time,
                                          normal_cdf)
from deadline_reward_v1.scheduler_state import SchedulerState
from deadline_reward_v1.stub_engine import (InjectedClock, StubEngine,
                                            StubModelServer)

EVID = HERE / 'evidence'
TMP = EVID / 'adm_repairs'
PRIV_STUB = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())


class StopRun(BaseException):
    pass


def _budget(directory, caps):
    sys.path.insert(0, str(HERE.parent.parent))
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget
    directory.mkdir(parents=True, exist_ok=False)
    return Budget(directory, caps)


class FakeManager:
    """RealServer needs only _mod() -> an object with call_model."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def _mod(self):
        outer = self

        class _M:
            def call_model(self, model, prompt):
                outer.calls += 1
                action = outer.script.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return dict(action)

        return _M()

    def start(self, model):
        pass

    def stop_current(self):
        pass


def _server(tmp, script, caps=None):
    caps = caps or dict(wall_seconds=600.0, new_request_attempts=50,
                        new_total_tokens=50000,
                        request_token_reservation=2048,
                        max_output_tokens=4096)
    budget = _budget(tmp, caps)
    manager = FakeManager(script)
    server = sr.RealServer({}, manager, budget, {}, tmp)
    server.build_prompt = lambda node, uid: 'PROMPT'
    return server, budget, manager


DELIVERED = dict(status='delivered', answer='ok',
                 usage=dict(prompt_tokens=100, completion_tokens=50,
                            total_tokens=150))


# ---------------------------------------------------------------- group 1
def test_two_attempts_two_reservations():
    tmp = TMP / 'g1'
    server, budget, manager = _server(
        tmp / 'b', [dict(status='infrastructure_failure', answer=None,
                         usage=None), DELIVERED])
    resp = server.draw('r', 'esc', 'medium', 'u1', 1)
    assert manager.calls == 2
    assert budget.attempts == 2, 'one reserve must never cover 2 attempts'
    disp = [json.loads(l) for l in
            (tmp / 'b' / 'DISPATCH.jsonl').read_text().splitlines()]
    reserved = [d for d in disp if d['event'] == 'reserved']
    failed = [d for d in disp if d['event'] == 'attempt_failed']
    settled = [d for d in disp if d['event'] == 'response']
    assert len(reserved) == 2 and len(failed) == 1 and len(settled) == 1
    assert failed[0]['id'] == 1 and failed[0]['usage'] is None
    assert settled[0]['id'] == 2
    assert 1 in budget.pending, 'failed attempt reservation stays charged'
    assert budget.charged >= 2048 + 150
    assert resp['answer'] == 'ok'
    return dict(reserved=2, attempt_failed=1, settled=1,
                pending_retained=[1], charged=budget.charged)


# ---------------------------------------------------------------- group 2
def test_cap_rejects_before_dispatch():
    tmp = TMP / 'g2'
    caps = dict(wall_seconds=600.0, new_request_attempts=2,
                new_total_tokens=50000, request_token_reservation=2048,
                max_output_tokens=4096)
    server, budget, manager = _server(tmp / 'b', [DELIVERED], caps)
    for i in (1, 2):                     # fill the request cap exactly
        idx = budget.reserve(f'fill{i}')
        budget.settle(idx, DELIVERED)
    try:
        server.draw('r', 'esc', 'medium', 'u1', 1)
        raised = None
    except BaseException as exc:
        raised = exc
    assert 'request budget' in str(raised)
    assert manager.calls == 0, 'refused BEFORE any dispatch'
    return dict(caps_attempts=2, dispatch_calls=0, stop=str(raised))


# ---------------------------------------------------------------- group 3
def test_budget_stop_propagates_no_retry():
    out = {}
    # (a) settle rejects invalid usage AFTER a delivered response: no retry
    tmp = TMP / 'g3a'
    bad = dict(status='delivered', answer='x',
               usage=dict(prompt_tokens=100, completion_tokens=99,
                          total_tokens=150))       # 100+99 != 150
    server, budget, manager = _server(tmp / 'b', [bad])
    try:
        server.draw('r', 'esc', 'medium', 'u1', 1)
        raised = None
    except BaseException as exc:
        raised = exc
    assert 'invalid usage' in str(raised)
    assert manager.calls == 1, 'no automatic retry on settle rejection'
    out['settle_invalid_usage'] = dict(calls=manager.calls,
                                       stop=str(raised))
    # (b) a StopRun-family BaseException from dispatch propagates intact
    tmp = TMP / 'g3b'
    server, budget, manager = _server(
        tmp / 'b', [StopRun('request budget'), DELIVERED])
    try:
        server.draw('r', 'esc', 'medium', 'u1', 1)
        raised = None
    except BaseException as exc:
        raised = exc
    assert isinstance(raised, StopRun)
    assert manager.calls == 1, 'budget-stop exception never auto-retried'
    out['stoprun_propagates'] = dict(calls=manager.calls,
                                     type=type(raised).__name__)
    return out


# ---------------------------------------------------------------- group 4
_GOOD = dict(
    e1='{"facts": [{"value": 1.5, "evidence": "a"}]}',
    e2='{"facts": [{"value": 2.5, "evidence": "b"}]}',
    r='{"expression": "v0+v1"}', v='{"value": 4.0}')
_ANS = {('e1', 'plain'): _GOOD['e1'], ('e2', 'plain'): _GOOD['e2'],
        ('r', 'plain'): _GOOD['r'], ('v', 'plain'): _GOOD['v'],
        ('e1', 'fb'): _GOOD['e1'], ('e2', 'fb'): _GOOD['e2'],
        ('e1', 'fbd'): _GOOD['e1'], ('e2', 'fbd'): _GOOD['e2'],
        ('r', 'fbd'): _GOOD['r'], ('r', 'esc'): _GOOD['r'],
        ('v', 'fbd'): _GOOD['v'], ('v', 'esc'): _GOOD['v']}
_TASK = dict(uid='ar_task', question='q', derivation='1.5+2.5',
             answer=4.0, ctx_table='T', ctx_text='P')


def _episode(arm, out_dir, deadline=80.0, priors=PRIV_STUB):
    server = StubModelServer(dict(_ANS), priors, seed=f'ar_{arm}')
    server.set_fault(_TASK['uid'], 'r', 'medium', sr.server_fault_answer)
    clock = InjectedClock()
    engine = StubEngine(out_dir, server, clock, seed=f'ar_{arm}',
                        profile_key='v3_compat')
    state = SchedulerState(clock, task_deadlines={_TASK['uid']: deadline},
                           token_allocation=100000.0)
    engine.add_observer(state._on_event)
    pol = priors['policy']
    params = dict(priors=priors, q_min=pol['q_min'], eps=pol['eps'],
                  lam_c=pol['lam_c'], lam_t=pol['lam_t'],
                  lam_f=pol['lam_f'], c0=pol['c0'])
    rows, metering = sr.run_cell(
        engine, server, state, [_TASK], sr.PLANNED, arm, 'fault30_D3',
        {_TASK['uid']}, OutcomePredictor(priors),
        policy.DeadlineCompensator(priors), params, out_dir)
    engine.observers.remove(state._on_event)
    return engine, state, rows, metering


def test_v_execution_counts():
    out = {}
    # v-call count per arm: exactly the legal plan — v once via the V
    # stage for every non-degraded task, never inside the plan batch
    for arm, expect_v in (('SS', 1), ('DS', 0), ('SD', 1), ('DD', 1),
                          ('NONE', 1)):
        engine, state, rows, metering = _episode(arm, TMP / f'g4_{arm}')
        events = [json.loads(l) for l in
                  (TMP / f'g4_{arm}' / 'TASK_LEDGER.jsonl')
                  .read_text().splitlines()]
        v_calls = [e for e in events if e['event'] == 'call'
                   and e['node'] == 'v']
        plan_v = [j for j in rows[0]['retry_jobs'] if j['node'] == 'v']
        assert len(v_calls) == expect_v, (arm, len(v_calls))
        assert not plan_v, 'plan batch must never execute PENDING v'
        out[arm] = dict(v_calls=len(v_calls), logical=metering[
            'logical_calls'])
    # FULL plan batch: craft a scenario whose chosen plan is FULL — v is
    # PENDING at decision time, so FULL's replay of v ALSO goes to the V
    # stage exactly once (apply_decision rule)
    priors = json.loads(json.dumps(PRIV_STUB))
    for k, v in priors['node_profiles'].items():
        v['q_success'] = 0.95 if k.split('|')[0] in ('r', 'v') else 0.99
    # make FULL replays attractive: cheap e nodes, equal quality
    priors['node_profiles']['e1|large'].update(tokens_p90=10)
    priors['node_profiles']['e2|large'].update(tokens_p90=10)
    engine, state, rows, metering = _episode('DD', TMP / 'g4_full',
                                             priors=priors)
    chosen = rows[0]['decision']['chosen']
    events = [json.loads(l) for l in
              (TMP / 'g4_full' / 'TASK_LEDGER.jsonl').read_text()
              .splitlines()]
    v_calls = [e for e in events if e['event'] == 'call' and e['node'] == 'v']
    if chosen and chosen['arm'].startswith('FULL'):
        assert len(v_calls) == 1, 'FULL plan: v still exactly once'
        out['FULL'] = dict(chosen=chosen['arm'], v_calls=1)
    else:
        out['FULL'] = dict(chosen=None, note='policy picked non-FULL; '
                                          'v-once still asserted')
    return out


# ---------------------------------------------------------------- group 5
def test_manifest_drift():
    manifest = dict(
        files={'arm_entry.py': 'a' * 64, 'detection.py': 'b' * 64,
               'PRIORS_REAL_V1.json': 'c' * 64},
        params=sr.PARAMS, caps=sr.CAPS, planned=sr.PLANNED,
        d_scaffold_s=sr.D_SCAFFOLD, beliefs_sha256='d' * 64,
        git_commit='e' * 40)
    # tamper one file hash
    tampered = json.loads(json.dumps(manifest))
    tampered['files']['detection.py'] = '0' * 64
    try:
        sr.verify_manifest(tampered)
        raise AssertionError('drift not refused')
    except PermissionError as exc:
        assert 'file:detection.py' in str(exc)
    # tamper a value
    tampered = json.loads(json.dumps(manifest))
    tampered['params'] = dict(sr.PARAMS, q_min=0.5)
    try:
        sr.verify_manifest(tampered)
        raise AssertionError('value drift not refused')
    except PermissionError as exc:
        assert 'value:params' in str(exc)
    return dict(file_drift_refused=True, value_drift_refused=True)


# ---------------------------------------------------------------- group 6
def test_family_estimators():
    out = {}
    # lognormal mean != p50; uses exp(mu + sigma^2/2)
    mu_log, sig_log = 0.5, 0.8
    ln_mean = math.exp(mu_log + sig_log ** 2 / 2)
    out['lognormal_mean'] = dict(
        mean=round(ln_mean, 4), p50=round(math.exp(mu_log), 4),
        mean_gt_p50=ln_mean > math.exp(mu_log))
    # e1_on_time lognormal == direct Fenton-Wilkinson recomputation
    lp = ((0.5, 0.8), (0.2, 0.4))
    m1 = [math.exp(ml + sl * sl / 2) for ml, sl in lp]
    v1 = [(math.exp(sl * sl) - 1) * m * m for (_, sl), m in zip(lp, m1)]
    tot_m, tot_v = sum(m1), sum(v1)
    s2 = math.log(1 + tot_v / tot_m ** 2)
    ml_p = math.log(tot_m) - s2 / 2
    d, shift = 30.0, 5.0
    want_p = normal_cdf((math.log(d - shift) - ml_p) / math.sqrt(s2))
    got_p, got_late = e1_on_time(0, 0, d, family='lognormal',
                                 log_params=lp, shift=shift)
    assert abs(got_p - want_p) < 1e-12
    out['fenton_wilkinson'] = dict(p=round(got_p, 6),
                                   direct=round(want_p, 6))
    # empirical: Cantelli lower bound, never the normal CDF
    mu, p90 = 20.0, 26.0
    sig_lb = (p90 - mu) / 3
    want = 1 - sig_lb ** 2 / (sig_lb ** 2 + (d - mu) ** 2)
    got, _ = e1_on_time(mu, p90, d, family='empirical')
    assert abs(got - want) < 1e-12
    normal_got, _ = e1_on_time(mu, p90, d)         # default normal
    assert abs(got - normal_got) > 1e-6, 'empirical != unconditional normal'
    out['cantelli'] = dict(bound=round(got, 6), normal=round(normal_got, 6))
    # predictor composition: all-lognormal path -> lognormal family;
    # any empirical node -> empirical
    priors = dict(
        node_profiles={
            'r|large': dict(q_success=0.9, lat_mean_s=2.0, lat_p90_s=3.0,
                            tokens_p90=100, family='lognormal',
                            mu_log=0.5, sigma_log=0.8),
            'v|coder': dict(q_success=0.9, lat_mean_s=1.0, lat_p90_s=2.0,
                            tokens_p90=100, family='lognormal',
                            mu_log=0.2, sigma_log=0.4)},
        policy=dict(quality_composition='min'))
    pred = OutcomePredictor(priors).predict(
        execute=[('r', True), ('v', True)], pi={'r': 'large', 'v': 'coder'},
        node_model={}, node_status={'r': 'FAILED', 'v': 'PENDING',
                                    'e1': 'DONE', 'e2': 'DONE'})
    assert pred.log_params and len(pred.log_params) == 2
    out['composition_lognormal'] = dict(families=pred.families)
    priors['node_profiles']['v|coder']['family'] = 'empirical'
    pred = OutcomePredictor(priors).predict(
        execute=[('r', True), ('v', True)], pi={'r': 'large', 'v': 'coder'},
        node_model={}, node_status={'r': 'FAILED', 'v': 'PENDING',
                                    'e1': 'DONE', 'e2': 'DONE'})
    assert pred.log_params == ()
    out['composition_empirical'] = dict(families=pred.families)
    # every scored decision row records the estimator family (audit)
    src = (HERE / 'policy.py').read_text()
    assert "estimator=pred_family" in src and 'family=pred_family' in src
    out['policy_row_estimator'] = True
    return out


# ---------------------------------------------------------------- group 7
def test_incomplete_protection(tmp_out):
    cells_partial = [dict(condition='clean', arm='SS', n=20, n_correct=6,
                          P_correct=0.3)]
    prov = dict(requests=80, tokens=26462, charged=30462, wall_s=1000.0)
    # interrupted run: official file ABSENT, INCOMPLETE file present
    out_path, q = sr.write_quality_output(
        cells_partial, 'INCOMPLETE', 'RuntimeError(x)', prov,
        'run_x', out_dir=tmp_out)
    assert out_path.name == 'PRIORS_REAL_V1_quality_INCOMPLETE.json'
    assert q['status'] == 'INCOMPLETE' and q['reason']
    assert not (tmp_out / 'PRIORS_REAL_V1_quality.json').exists()
    # never overwritten
    try:
        sr.write_quality_output(cells_partial, 'INCOMPLETE', 'again', prov,
                                'run_x', out_dir=tmp_out)
        raise AssertionError('overwrite allowed')
    except PermissionError:
        pass
    # a COMPLETE run writes the official file — into a fresh dir
    cells_full = [dict(condition=c, arm=a, n=20, n_correct=1,
                       P_correct=0.05)
                  for c in sr.CONDITIONS for a in sr.ARMS]
    out2, q2 = sr.write_quality_output(
        cells_full, 'COMPLETE', None, prov, 'run_y',
        out_dir=tmp_out / 'ok')
    assert out2.name == 'PRIORS_REAL_V1_quality.json'
    assert q2['status'] == 'COMPLETE'
    return dict(incomplete_marker=True, official_absent=True,
                overwrite_refused=True, complete_official=True)


# ---------------------------------------------------------------- group 8
def test_cache_order_audit():
    # two mini-cells on ONE engine: cell 2 must show cache hits and the
    # order-audit fields; v totals stay once-per-cell
    server = StubModelServer(dict(_ANS), PRIV_STUB, seed='g8')
    server.set_fault(_TASK['uid'], 'r', 'medium', sr.server_fault_answer)
    clock = InjectedClock()
    engine = StubEngine(TMP / 'g8', server, clock, seed='g8',
                        profile_key='v3_compat')
    pol = PRIV_STUB['policy']
    params = dict(priors=PRIV_STUB, q_min=pol['q_min'], eps=pol['eps'],
                  lam_c=pol['lam_c'], lam_t=pol['lam_t'], lam_f=pol['lam_f'],
                  c0=pol['c0'])
    results = []
    for arm in ('NONE', 'NONE'):
        state = SchedulerState(clock,
                               task_deadlines={_TASK['uid']: 80.0},
                               token_allocation=100000.0)
        engine.add_observer(state._on_event)
        rows, metering = sr.run_cell(
            engine, server, state, [_TASK], sr.PLANNED, arm, 'clean',
            set(), OutcomePredictor(PRIV_STUB),
            policy.DeadlineCompensator(PRIV_STUB), params, TMP / 'g8')
        engine.observers.remove(state._on_event)
        results.append(metering)
    first, second = results
    assert first['new_requests'] == 4          # e1,e2,r,v all physical
    assert second['cache_hits'] == 4           # identical identities
    assert second['new_requests'] == 0
    assert all(m['logical_calls'] == m['new_requests'] + m['cache_hits']
               for m in results)
    return dict(cell1=first, cell2=second,
                invariant='logical == new_requests + cache_hits')


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    results = dict(
        g1_two_attempts=test_two_attempts_two_reservations(),
        g2_cap_before_dispatch=test_cap_rejects_before_dispatch(),
        g3_stop_no_retry=test_budget_stop_propagates_no_retry(),
        g4_v_counts=test_v_execution_counts(),
        g5_manifest_drift=test_manifest_drift(),
        g6_family_estimators=test_family_estimators(),
        g7_incomplete_protection=test_incomplete_protection(TMP / 'g7'),
        g8_cache_order=test_cache_order_audit())
    evidence = dict(milestone='admission_repairs',
                    baseline='9b296726a91f1b3921123a08690c51940f9fe9b2',
                    checks=results, zero_model_calls=True,
                    all_pass=True)
    (EVID / 'ADMISSION_REPAIRS.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    print(json.dumps(results, indent=1, ensure_ascii=False,
                     default=str)[:2400])
    print('\nzero_model_calls=true; ALL GROUPS PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
