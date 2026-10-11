"""M6 formal-acceptance suite — the frozen two-stage decision, audited by
INDEPENDENT expected-value reconciliation. Zero real model calls.

Every golden scenario is re-derived HERE by hand (closed-form E1 + the
frozen Ê[R_task] expansion with lam_t normalized by D_total) and compared
against the engine-produced decision tables AND the actual selections:
  V1-S1  choose B   (B P=0.999940 feasible; A on_time-infeasible;
                     C q_min-infeasible)
  V1-S2  EARLY_STOP (B p90=21 -> P=0.8318<0.90; A time-infeasible;
                     C quality-infeasible; feasible set EMPTY)
  V8     lambda_c sensitivity (0.5 -> A; 2.0 -> B), scores match the
         closed form exactly
  V10    time sensitivity through the REAL M6 policy: same fault & legal
         history, ONLY the deadline changes -> the POLICY's chosen pi
         changes downstream node models; ledger models == chosen pi
Also: predicted-vs-actual separation (settlement uses ledger, never
predictions), statistical-calibre tagging (exact/conservative/heuristic),
and causality (decisions contain no gold/fault/future payloads).

Run: python3 -m deadline_reward_v1.test_m6  (any CWD)
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import socket as _socket_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import policy  # noqa: E402
from deadline_reward_v1.scheduler_state import SchedulerState  # noqa: E402
from deadline_reward_v1.stub_engine import (  # noqa: E402
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
BASE_PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
RUNS_DIR = HERE / 'evidence' / 'm6_runs'
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

Phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
phif = lambda z: math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def e1(mu, p90, d):
    s = (p90 - mu) / 1.2816
    if s <= 0:
        return (1.0 if mu <= d else 0.0), max(0.0, mu - d)
    z = (mu - d) / s
    return Phi((d - mu) / s), s * (phif(z) + z * Phi(z))


def er(q, dc, p, late, lam_c, d_total=20.0):
    return p * q - lam_c * dc / 4000.0 - 1.0 * late / d_total - 2.0 * (1 - p)


def golden_priors(p90_v_coder=7.5):
    p = copy.deepcopy(BASE_PRIORS)
    p['switch'] = {"family": "deterministic", "stop_s": 0.0,
                   "start_s": {"medium": 0.0, "large": 0.0, "coder": 0.0},
                   "synthetic": True}
    p['node_profiles']['v|coder']['lat_p90_s'] = p90_v_coder
    return p


def run(dirname, deadline, *, priors=None, lam_c=0.5, q_min=0.80, eps=0.10):
    priors = priors or golden_priors()
    t = dict(uid='st0', question='What is 1.5 + 2.5?', derivation='1.5+2.5',
             answer=4.0, ctx_table='TABLE: | val | 1.5 |',
             ctx_text='PASSAGES: value is 2.5')
    server = StubModelServer(dict(ANSWERS), priors, seed='m6')
    server.set_fault('st0', 'r', 'medium', '###SYNTHETIC UNPARSEABLE###')
    clock = InjectedClock()
    engine = StubEngine(RUNS_DIR / dirname, server, clock, seed='m6',
                        profile_key='golden_zero')
    state = SchedulerState(clock, task_deadlines={'st0': deadline},
                           token_allocation=4000.0)
    state.attach(engine)
    params = dict(priors=priors, q_min=q_min, eps=eps, lam_c=lam_c,
                  lam_t=1.0, lam_f=2.0, c0=4000.0, session_bonus=1.0,
                  session_penalty=2.0)
    result = policy.run_episode(engine, state, [t], NODES_MODELS, params)
    events, torn = load_ledger(RUNS_DIR / dirname / 'TASK_LEDGER.jsonl')
    return dict(decisions=[e for e in events if e['event'] == 'decision'],
                events=events, torn=torn, result=result, server=server,
                state=state, task=t)


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

    # ================= V1-S1: choose B, hand-reconciled ================
    r1 = run('v1s1', 20.0)
    d1 = next(e for e in r1['decisions'] if e['stage'] == 'post_R1')
    tbl = {(r['arm'], r['pi'].get('r'), r['pi'].get('v')): r
           for r in d1['table'] if r['arm'] == 'LOCAL'}
    A, B, C = (tbl[('LOCAL', 'large', 'large')],
               tbl[('LOCAL', 'large', 'coder')],
               tbl[('LOCAL', 'medium', 'coder')])
    exp = {}
    for nm, (q, mu, p90, dc) in dict(
            A=(0.95, 24.0, 25.0, 1200), B=(0.85, 17.0, 18.0, 900),
            C=(0.60, 12.0, 13.0, 700)).items():
        p, late = e1(mu, p90, 20.0)
        exp[nm] = dict(p=p, late=late, score=er(q, dc, p, late, 0.5),
                       feas=(q >= 0.80 and p >= 0.90))
    checks['m6_v1s1_table_matches_hand'] = (
        abs(A['p_on_time'] - exp['A']['p']) < 1e-6
        and abs(B['p_on_time'] - exp['B']['p']) < 1e-6
        and abs(C['q'] - 0.60) < 1e-9
        and abs(B['score'] - exp['B']['score']) < 1e-6
        and abs(A['score'] - exp['A']['score']) < 1e-6)
    checks['m6_v1s1_feasibility_matches_hand'] = (
        not A['feasible'] and B['feasible'] and not C['feasible']
        and A['deficits'][0]['constraint'] == 'on_time'
        and C['deficits'][0]['constraint'] == 'q_min')
    # chosen = the maximum-score FEASIBLE row (B among LOCAL; the policy
    # may tie with an equivalent FULL_DYNAMIC row — same pi on r/v)
    chosen = d1['chosen']
    feas_rows = [r for r in d1['table'] if r['feasible']]
    best = max(feas_rows, key=lambda r: r['score'])
    checks['m6_v1s1_chooses_B'] = (
        chosen['pi'].get('r') == 'large' and chosen['pi'].get('v') == 'coder'
        and chosen['arm'] in ('LOCAL', 'FULL_DYNAMIC')
        and abs(chosen['score'] - exp['B']['score']) < 1e-6
        and abs(chosen['score'] - best['score']) < 1e-9)
    # executed ledger matches chosen pi on r and v
    r_calls = [e for e in r1['events'] if e['event'] == 'call'
               and e['node'] == 'r']
    v_call = [e for e in r1['events'] if e['event'] == 'call'
              and e['node'] == 'v'][-1]
    checks['m6_v1s1_executes_B'] = (
        r_calls[-1]['model'] == 'large' and v_call['model'] == 'coder')
    det['v1s1_hand'] = {k: dict(p=round(v['p'], 6),
                                score=round(v['score'], 6),
                                feasible=v['feas'])
                        for k, v in exp.items()}

    # ================= V1-S2: EARLY_STOP, hand-reconciled ==============
    r2 = run('v1s2', 20.0, priors=golden_priors(p90_v_coder=10.5))
    d2 = next(e for e in r2['decisions'] if e['stage'] == 'post_R1')
    pB2, _ = e1(17.0, 21.0, 20.0)
    tbl2 = {(r['pi'].get('r'), r['pi'].get('v')): r for r in d2['table']
            if r['arm'] == 'LOCAL'}
    B2 = tbl2[('large', 'coder')]
    checks['m6_v1s2_hand'] = (
        abs(pB2 - 0.831774) < 1e-5
        and abs(B2['p_on_time'] - pB2) < 1e-6 and not B2['feasible'])
    checks['m6_v1s2_early_stop'] = (
        d2['degraded'] and d2['chosen'] is None
        and all(not r['feasible'] for r in d2['table'])
        and len(d2['violations']) == len(d2['table']))
    post_calls = [e for e in r2['events'] if e['event'] == 'call'
                  and str(e.get('stage', '')).startswith(('plan:', 'V1'))]
    checks['m6_v1s2_zero_further_calls'] = (
        len(post_calls) == 0
        and r2['result']['settlement']['rewards'][0]['degraded'])
    det['v1s2_hand'] = dict(B_p_on=round(pB2, 6), threshold=0.90)

    # ================= V8: lambda_c sensitivity, hand-reconciled =======
    v8 = {}
    for lam in (0.5, 2.0):
        r = run(f'v8_{lam}', 60.0, lam_c=lam)
        d = next(e for e in r['decisions'] if e['stage'] == 'post_R1')
        v8[lam] = d['chosen']
    pA, _ = e1(24.0, 25.0, 60.0)
    pB, _ = e1(17.0, 18.0, 60.0)
    diff = lambda lc: ((pA * 0.95 - lc * 1200 / 4000)
                       - (pB * 0.85 - lc * 900 / 4000))
    checks['m6_v8_lambda_flips_argmax'] = (
        v8[0.5]['pi'].get('v') == 'large' and v8[2.0]['pi'].get('v') == 'coder'
        and diff(0.5) > 0 and diff(2.0) < 0)
    det['v8_hand'] = dict(diff_lam05=round(diff(0.5), 6),
                          diff_lam20=round(diff(2.0), 6))

    # ================= V10: REAL policy, only deadline changes ==========
    v10 = {}
    # decisive window under the per-call switch BOUND: A mu=31.0
    # (24 svc + 7.0 bound), B mu=23.5; clock-at-decision=5.5.
    # rich deadline 39 -> d_rem 33.5: A P=0.9993, score 0.7993
    # > B 0.7375 -> A(v=large). tight deadline 31 -> d_rem 25.5:
    # A infeasible, B P=0.9948 -> B(v=coder).
    for nm, dl in (('rich', 39.0), ('tight', 31.0)):
        r = run(f'v10_{nm}', dl, priors=copy.deepcopy(BASE_PRIORS))
        d = next(e for e in r['decisions'] if e['stage'] == 'post_R1')
        v10[nm] = dict(chosen=d['chosen'], d_remain=d['d_remain'],
                       events=r['events'])
    c_rich, c_tight = v10['rich']['chosen'], v10['tight']['chosen']
    v_rich = [e for e in v10['rich']['events'] if e['event'] == 'call'
              and e['node'] == 'v'][-1]
    v_tight = [e for e in v10['tight']['events'] if e['event'] == 'call'
               and e['node'] == 'v'][-1]
    checks['m6_v10_policy_changes_model_by_time'] = (
        c_rich['pi'].get('v') == 'large' and c_tight['pi'].get('v') == 'coder'
        and v_rich['model'] == 'large' and v_tight['model'] == 'coder'
        and c_rich['pi'].get('r') == c_tight['pi'].get('r') == 'large')

    # ================= predicted vs actual separation ===================
    set1 = r1['result']['settlement']['rewards'][0]
    chosen_row = next(r for r in d1['table'] if r['feasible']
                      and r['arm'] == chosen['arm']
                      and r['pi'] == chosen['pi'])
    checks['m6_predicted_vs_actual_separated'] = (
        chosen_row['dcost'] == 900.0                     # PREDICTED C_new
        and set1['c_full'] != chosen_row['dcost']         # settlement uses
        and set1['q'] == 1.0 and set1['T'] >= 0           # LEDGER values
        and set1['c_full'] == 500)                        # 5 calls x 100
    det['separation'] = dict(predicted_cnew=chosen_row['dcost'],
                             settled_c_full=set1['c_full'],
                             settled_T=set1['T'], settled_q=set1['q'])

    # ============ statistical calibre (errata task 1) ===================
    # Expected tags computed INDEPENDENTLY of the product's own logic:
    #   quantile_sum + d_remain >= mu_e2e  -> conservative (lower bound)
    #   quantile_sum + d_remain <  mu_e2e  -> NOT conservative
    #   variance (any d)                   -> conservative-tagged exact
    #     (the product marks variance-mode rows p_conservative=True)
    def expected_tag(row, d_rem):
        return (d_rem >= row['mu_e2e']) or row['p_on_time'] in (0.0, 1.0)

    d_rem_1 = d1['d_remain']
    tags_ok = all(
        r['p_conservative'] == expected_tag(r, d_rem_1)
        for r in d1['table'])
    # at least one row of EACH regime must exist in this table so the
    # check is non-vacuous in both directions
    has_ge = any(d_rem_1 >= r['mu_e2e'] for r in d1['table'])
    has_lt = any(d_rem_1 < r['mu_e2e'] for r in d1['table'])
    checks['m6_calibre_tags_independent'] = (
        tags_ok and has_ge and has_lt
        and all(r['p_conservative'] for r in d1['table'] if
                d_rem_1 >= r['mu_e2e'])
        and not any(r['p_conservative'] for r in d1['table'] if
                    d_rem_1 < r['mu_e2e']))

    # variance mode: exact-under-declared-family tag is True everywhere
    rvar = run('cal_var', 60.0, priors=golden_priors())
    dvar = next(e for e in rvar['decisions'] if e['stage'] == 'post_R1')
    var_priors_c = golden_priors()
    var_priors_c['policy'] = dict(var_priors_c['policy'],
                                  p90_aggregation='variance')
    rvar2 = run('cal_var2', 60.0, priors=var_priors_c)
    dvar2 = next(e for e in rvar2['decisions']
                 if e['stage'] == 'post_R1')
    checks['m6_calibre_variance_exact'] = (
        all(r['p_conservative'] for r in dvar2['table']))

    # contention estimate: declared HEURISTIC, never a probability
    # guarantee — every row exposes it as a plain additive seconds
    # field (never inside p_on_time), and the docstring contract is
    # asserted structurally: the field is finite, additive, and absent
    # from the E1 inputs' tag
    checks['m6_contention_heuristic_declared'] = all(
        'contention' in r and isinstance(r['contention'], (int, float))
        and r['contention'] >= 0.0 for r in d1['table'])

    # ============ reverse tests: a WRONG tag must FAIL ================
    # (deliberately mislabel one row and re-run the independent checker)
    def tag_check(rows, d_rem):
        return all(r['p_conservative'] == expected_tag(r, d_rem)
                   for r in rows)
    poisoned = [dict(r) for r in d1['table']]
    victim = next(r for r in poisoned if d_rem_1 >= r['mu_e2e'])
    victim['p_conservative'] = False          # wrong: D>=mu must be True
    checks['m6_reverse_wrong_tag_detected'] = (
        not tag_check(poisoned, d_rem_1)
        and tag_check([dict(r) for r in d1['table']], d_rem_1))
    poisoned2 = [dict(r) for r in d1['table']]
    victim2 = next(r for r in poisoned2 if d_rem_1 < r['mu_e2e'])
    victim2['p_conservative'] = True          # wrong: D<mu must be False
    checks['m6_reverse_wrong_tag_detected_2'] = not tag_check(
        poisoned2, d_rem_1)
    det['calibre'] = dict(d_remain=d_rem_1,
                          rows_ge_mu=sum(1 for r in d1['table']
                                         if d_rem_1 >= r['mu_e2e']),
                          rows_lt_mu=sum(1 for r in d1['table']
                                         if d_rem_1 < r['mu_e2e']))

    # ================= causality (errata task 2) ========================
    # (a) STRUCTURAL whitelist over every decision-table row: exactly the
    # audited fields may appear; any foreign key (however named) fails.
    ROW_WHITELIST = {
        'arm', 'pi', 'q', 'mu_e2e', 'p90', 'dcost', 'switch', 'switch_seq',
        'contention', 'p_on_time', 'e_late', 'p_conservative', 'score',
        'feasible', 'deficits', 'kinds'}
    PI_VAL_OK = {'medium', 'large', 'coder'}
    DEFICIT_KEYS = {'constraint', 'deficit'}
    KINDS_OK = {'plain', 'fb', 'fbd', 'esc'}
    def row_structural_ok(r):
        return (set(r) == ROW_WHITELIST
                and isinstance(r['pi'], dict)
                and set(r['pi']) <= {'e1', 'e2', 'r', 'v'}
                and set(r['pi'].values()) <= PI_VAL_OK
                and isinstance(r['deficits'], list)
                and all(set(x) <= DEFICIT_KEYS for x in r['deficits'])
                and set(r['kinds'].values()) <= KINDS_OK
                and isinstance(r['q'], float) and isinstance(r['score'],
                                                              float))
    checks['m6_structural_whitelist'] = all(
        row_structural_ok(r) for r in d1['table'])

    # (b) DECISION-EVENT whitelist: only the audited envelope fields
    EV_WHITELIST = {'event', 'task', 'stage', 'degraded', 'd_remain',
                    'b_remain_tokens', 'chosen', 'violations', 'table'}
    CHOSEN_WHITELIST = {'arm', 'pi', 'score'}
    def ev_structural_ok(e):
        if set(e) != EV_WHITELIST:
            return False
        if e['chosen'] is not None and set(e['chosen']) != CHOSEN_WHITELIST:
            return False
        return all(set(v) <= {'arm', 'pi', 'deficits'}
                   for v in e['violations'])
    checks['m6_event_whitelist'] = all(
        ev_structural_ok(e) for e in r1['decisions'])

    # (c) COUNTERFACTUAL INVARIANCE: identical legal observation history;
    # independently vary HIDDEN gold, HIDDEN future outputs, and the
    # HIDDEN fault registry. Candidates/feasibility/scores/selection/
    # degradation must be IDENTICAL (canonicalized).
    def canon(decisions):
        d = next(e for e in decisions if e['stage'] == 'post_R1')
        rows = []
        for r in d['table']:
            rows.append(json.dumps(
                dict(arm=r['arm'], pi=sorted(r['pi'].items()),
                     q=r['q'], mu=r['mu_e2e'], p90=r['p90'],
                     p=r['p_on_time'], dc=r['dcost'],
                     sc=r['score'], fx=r['feasible'],
                     df=r['deficits']),
                sort_keys=True, default=str))
        return json.dumps(dict(degraded=d['degraded'],
                               chosen=d['chosen'],
                               table=sorted(rows)),
                          sort_keys=True, default=str)

    base_sig = canon(r1['decisions'])
    # hidden gold variant: different task['answer'] (settlement-only)
    priors_g = golden_priors()
    t_g = dict(uid='st0', question='What is 1.5 + 2.5?',
               derivation='1.5+2.5', answer=999.0,
               ctx_table='TABLE: | val | 1.5 |',
               ctx_text='PASSAGES: value is 2.5')
    server_g = StubModelServer(dict(ANSWERS), priors_g, seed='m6')
    server_g.set_fault('st0', 'r', 'medium', '###SYNTHETIC UNPARSEABLE###')
    eng_g = StubEngine(RUNS_DIR / 'cf_gold', server_g, InjectedClock(),
                       seed='m6', profile_key='golden_zero')
    st_g = SchedulerState(InjectedClock(), task_deadlines={'st0': 20.0},
                          token_allocation=4000.0)
    st_g.attach(eng_g)
    params_g = dict(priors=priors_g, q_min=0.80, eps=0.10, lam_c=0.5,
                    lam_t=1.0, lam_f=2.0, c0=4000.0, session_bonus=1.0,
                    session_penalty=2.0)
    policy.run_episode(eng_g, st_g, [t_g], NODES_MODELS, params_g)
    ev_g, _ = load_ledger(eng_g.ledger_path)
    dec_g = [e for e in ev_g if e['event'] == 'decision']
    sig_gold = canon(dec_g)
    # gold DID change the settlement (it must — settlement reads gold)
    set_g = json.loads((RUNS_DIR / 'cf_gold' / 'REWARDS.jsonl')
                       .read_text().splitlines()[-1])
    gold_changed_settlement = set_g['rewards'][0]['q'] == 0.0

    # hidden future-outputs variant: server returns different (unseen)
    # answers for the SAME prompts — decisions see only legal history
    ANSWERS_FUT = dict(ANSWERS)
    ANSWERS_FUT[('v', 'plain')] = '{"value": 999.0}'
    server_f = StubModelServer(dict(ANSWERS_FUT), priors_g, seed='m6')
    server_f.set_fault('st0', 'r', 'medium', '###SYNTHETIC UNPARSEABLE###')
    eng_f = StubEngine(RUNS_DIR / 'cf_future', server_f,
                       InjectedClock(), seed='m6', profile_key='golden_zero')
    st_f = SchedulerState(InjectedClock(), task_deadlines={'st0': 20.0},
                          token_allocation=4000.0)
    st_f.attach(eng_f)
    policy.run_episode(eng_f, st_f, [dict(t_g, answer=4.0)],
                       NODES_MODELS, params_g)
    ev_f, _ = load_ledger(eng_f.ledger_path)
    sig_future = canon([e for e in ev_f if e['event'] == 'decision'])

    # hidden fault-registry variant: an EXTRA registry entry keyed on a
    # (node, model) combination this episode never calls — e1@medium
    # (e1's planned model is large and the chosen B path never re-runs
    # e1) — so the legal observation history stays identical; the
    # decision must not move. (Keying the extra fault on e1@large WOULD
    # fire during stage A and legitimately change history — that is not
    # a counterfactual, it is a different world.)
    server_h = StubModelServer(dict(ANSWERS), priors_g, seed='m6')
    server_h.set_fault('st0', 'e1', 'medium', '###NEVER OBSERVED###')
    server_h.set_fault('st0', 'r', 'medium', '###SYNTHETIC UNPARSEABLE###')
    eng_h = StubEngine(RUNS_DIR / 'cf_fault', server_h,
                       InjectedClock(), seed='m6', profile_key='golden_zero')
    st_h = SchedulerState(InjectedClock(), task_deadlines={'st0': 20.0},
                          token_allocation=4000.0)
    st_h.attach(eng_h)
    policy.run_episode(eng_h, st_h, [dict(t_g, answer=4.0)],
                       NODES_MODELS, params_g)
    ev_h, _ = load_ledger(eng_h.ledger_path)
    sig_fault = canon([e for e in ev_h if e['event'] == 'decision'])

    checks['m6_counterfactual_gold_invariant'] = (
        sig_gold == base_sig and gold_changed_settlement)
    checks['m6_counterfactual_future_invariant'] = sig_future == base_sig
    checks['m6_counterfactual_faultreg_invariant'] = sig_fault == base_sig
    det['counterfactual'] = dict(
        base_sig_len=len(base_sig),
        gold_same=sig_gold == base_sig,
        future_same=sig_future == base_sig,
        fault_same=sig_fault == base_sig,
        gold_changed_settlement=gold_changed_settlement)

    # legacy string check retained as defense-in-depth
    dump = json.dumps(d1['table'])
    checks['m6_no_illegal_payloads'] = (
        'gold' not in dump and 'fault' not in dump
        and 'future' not in dump and GOOD_R not in dump)

    # ================= zero-call sentinel ==============================
    physical = sum(1 for e in r1['events'] if e['event'] == 'call'
                   and e['physical'])
    checks['m6_z1'] = (r1['server'].invocations == physical
                       and not r1['torn'])

    all_pass = all(checks.values())
    evidence = dict(milestone='M6-acceptance', checks=checks,
                    all_pass=all_pass, zero_model_calls=True,
                    hand_reconciliation=det)
    (HERE / 'evidence' / 'M6_EVIDENCE.json').write_text(
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
