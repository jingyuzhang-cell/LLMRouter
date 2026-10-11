"""Pre-authorization admission check for the supplementary DAG-quality
measurement (~1000 real calls). Implements the operator's five conditions.
ZERO real model calls throughout; reads only frozen artifacts.

  Gate 1  Statistical reproducibility: the COMPLETE frozen protocol from
          CALIBRATION_FREEZE_PREREQUISITES.json — Shapiro-Wilk AND
          D'Agostino K² per cell, Bonferroni WITHIN each (node, model,
          condition) cell across the 2 tests, family selection
          (normal / lognormal / empirical), full statistics + versions +
          raw-data hashes; cross-checked against the Shapiro-only
          DISTRIBUTION_TESTS_V2.
  Gate 2  Execution capability: the five arms driven through arm_entry
          (the frozen entry points) on the stub engine — DS/SD/DD route
          through the SAME policy._score_and_pick over DIFFERENT candidate
          sets; behavioral difference proven on observable call sequences.
  Gate 3  Data isolation: frozen supplementary UID list (Random(42)) with
          SHA-256, intersection checks vs the evaluation panel and the
          1200-call calibration panel, frozen fault assignment.
  Gate 4  Budget/stop: zero-call rehearsal through the REAL Budget class
          (production metering semantics) proving each cap trips and the
          planned worst-case pattern fits.
  Gate 5  Scope statement.

Run: python3 -m deadline_reward_v1.calibration_admission_check
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import random
import shutil
import socket as _socket_mod
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import scipy
from scipy import stats as sps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
LEDGER = HERE / 'calibration_runs' / 'CALIBRATION_LEDGER.jsonl'
EVID = HERE / 'evidence'

ALPHA = 0.01                 # frozen significance level
N_TESTS_PER_CELL = 2         # Shapiro-Wilk + D'Agostino K² (per family)
BONF_THRESHOLD = ALPHA / N_TESTS_PER_CELL   # Bonferroni WITHIN a cell

D3_FAULT_ANSWER = '###SYNTHETIC UNPARSEABLE r-output###'  # = calibration ledger
PLANNED = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha_obj(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     default=str).encode()).hexdigest()


@contextlib.contextmanager
def no_socket():
    def _raise(*_a, **_k):
        raise AssertionError('network access attempted')
    saved = _socket_mod.socket
    _socket_mod.socket = _raise
    try:
        yield
    finally:
        _socket_mod.socket = saved


# ---------------------------------------------------------------- Gate 1
def gate1_statistics():
    """COMPLETE frozen protocol: SW + K² per cell, within-cell Bonferroni
    across the 2 tests, per family (normal on raw, lognormal on log)."""
    calls = [json.loads(l) for l in LEDGER.read_text().splitlines()
             if l.strip()]
    calls = [e for e in calls if e.get('event') == 'call']
    cells = defaultdict(list)
    for c in calls:
        cells[c['cell']].append(c['lat_s'])

    v2 = json.loads((EVID / 'DISTRIBUTION_TESTS_V2.json').read_text())
    v2_results = v2.get('results', {})

    per_cell, binding = {}, {}
    for cell in sorted(cells):
        lats = np.array(cells[cell])
        n = len(lats)
        logs = np.log(lats)

        W_r, p_sw = sps.shapiro(lats)
        K_r, p_k2 = sps.normaltest(lats)
        W_l, p_sw_log = sps.shapiro(logs)
        K_l, p_k2_log = sps.normaltest(logs)

        def adj(p):
            return min(1.0, p * N_TESTS_PER_CELL)

        normal_pass = bool(adj(p_sw) >= ALPHA and adj(p_k2) >= ALPHA)
        lognormal_pass = bool(adj(p_sw_log) >= ALPHA
                              and adj(p_k2_log) >= ALPHA)
        if normal_pass:
            family = 'normal'
        elif lognormal_pass:
            family = 'lognormal'
        else:
            family = 'empirical'

        v2_cell = v2_results.get(cell, {})
        v2_family = ('normal' if v2_cell.get('normal_pass')
                     else 'lognormal' if v2_cell.get('lognormal_pass')
                     else 'empirical')

        row = dict(
            n=n,
            lat_sorted=[round(float(x), 4) for x in sorted(lats)],
            shapiro=dict(W=round(float(W_r), 6), p=round(float(p_sw), 8),
                         p_bonf=round(adj(p_sw), 8)),
            dagostino_k2=dict(stat=round(float(K_r), 4),
                              p=round(float(p_k2), 8),
                              p_bonf=round(adj(p_k2), 8)),
            shapiro_log=dict(W=round(float(W_l), 6),
                             p=round(float(p_sw_log), 8),
                             p_bonf=round(adj(p_sw_log), 8)),
            dagostino_k2_log=dict(stat=round(float(K_l), 4),
                                  p=round(float(p_k2_log), 8),
                                  p_bonf=round(adj(p_k2_log), 8)),
            normal_pass=normal_pass, lognormal_pass=lognormal_pass,
            selected_family=family,
            v2_shapiro_only_family=v2_family,
            changed_vs_v2=(family != v2_family))
        if family == 'lognormal':
            row['lognormal_params'] = dict(
                mu_log=round(float(np.mean(logs)), 6),
                sigma_log=round(float(np.std(logs, ddof=1)), 6))
        per_cell[cell] = row
        binding[cell] = family

    n_norm = sum(1 for f in binding.values() if f == 'normal')
    n_log = sum(1 for f in binding.values() if f == 'lognormal')
    n_emp = sum(1 for f in binding.values() if f == 'empirical')
    changed = {c: dict(complete=r['selected_family'],
                       v2_shapiro_only=r['v2_shapiro_only_family'])
               for c, r in per_cell.items() if r['changed_vs_v2']}

    commit = subprocess.run(
        ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
        capture_output=True, text=True).stdout.strip()

    result = dict(
        protocol_source='CALIBRATION_FREEZE_PREREQUISITES.json '
                        '.distribution_family_validation (frozen '
                        '2026-10-11, before any calibration data viewed)',
        per_cell_tests=['shapiro_wilk (n<5000)', 'dagostino_k2 (any n)'],
        significance_level=ALPHA,
        multiple_testing=f'Bonferroni WITHIN each (node, model, condition) '
                         f'cell across the {N_TESTS_PER_CELL} tests '
                         f'(per-test threshold {BONF_THRESHOLD}); family '
                         'selection prefers normal, then lognormal, else '
                         'empirical (no parametric E1; empirical CDF)',
        n_cells=len(per_cell), n_normal=n_norm, n_lognormal=n_log,
        n_empirical=n_emp,
        changes_vs_shapiro_only_v2=changed,
        versions=dict(python=sys.version.split()[0],
                      numpy=np.__version__, scipy=scipy.__version__,
                      git_commit=commit,
                      script_sha256=_sha(Path(__file__)),
                      ledger_sha256=_sha(LEDGER),
                      prerequisites_sha256=_sha(
                          HERE / 'CALIBRATION_FREEZE_PREREQUISITES.json')),
        per_cell=per_cell)
    return result, binding


# ---------------------------------------------------------------- Gate 2
_NM = PLANNED
_GOOD = dict(
    e1='{"facts": [{"value": 1.5, "evidence": "a"}]}',
    e2='{"facts": [{"value": 2.5, "evidence": "b"}]}',
    r='{"expression": "v0+v1"}',
    v='{"value": 4.0}')
_ANSWERS = {
    ('e1', 'plain'): _GOOD['e1'], ('e2', 'plain'): _GOOD['e2'],
    ('r', 'plain'): _GOOD['r'], ('v', 'plain'): _GOOD['v'],
    ('e1', 'fb'): _GOOD['e1'], ('e2', 'fb'): _GOOD['e2'],
    ('e1', 'fbd'): _GOOD['e1'], ('e2', 'fbd'): _GOOD['e2'],
    ('r', 'fbd'): _GOOD['r'], ('r', 'esc'): _GOOD['r'],
    ('v', 'fbd'): _GOOD['v'], ('v', 'esc'): _GOOD['v']}


def _stub_episode(arm: str, out_dir: Path, deadline: float = 80.0):
    """One (arm) episode on the stub engine through the frozen arm_entry."""
    from deadline_reward_v1 import arm_entry, detection as det, policy
    from deadline_reward_v1.reassign import apply_whole_plan
    from deadline_reward_v1.scheduler_state import SchedulerState
    from deadline_reward_v1.stub_engine import (
        InjectedClock, StubEngine, StubModelServer, load_ledger)

    priors = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
    pol = priors['policy']
    params = dict(priors=priors, q_min=pol['q_min'], eps=pol['eps'],
                  lam_c=pol['lam_c'], lam_t=pol['lam_t'], lam_f=pol['lam_f'],
                  c0=pol['c0'])

    task = dict(uid='adm2_task', question='What is 1.5 + 2.5?',
                derivation='1.5+2.5', answer=4.0,
                ctx_table='TABLE: | val | 1.5 |',
                ctx_text='PASSAGES: value is 2.5')
    uid = task['uid']
    server = StubModelServer(dict(_ANSWERS), priors, seed=f'adm2_{arm}')
    server.set_fault(uid, 'r', 'medium', D3_FAULT_ANSWER)
    clock = InjectedClock()
    engine = StubEngine(out_dir, server, clock, seed=f'adm2_{arm}',
                        profile_key='v3_compat')
    state = SchedulerState(clock, task_deadlines={uid: deadline},
                           token_allocation=100000.0)
    state.attach(engine)
    engine.start_panel([task], _NM)
    engine.run_jobs('A', engine.planned_jobs([task], _NM, ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs([task], _NM, ('r',)))
    st = state.tasks[uid]
    assert st.node_status['r'] == 'FAILED', 'D3 fault not observed'
    assert st.node_status['v'] == 'PENDING'

    cands = arm_entry.enumerate_for(state, uid, _NM)
    rec = arm_entry.decide_arm(
        state, uid, cands, arm, _NM, params,
        policy.OutcomePredictor(priors), policy.DeadlineCompensator(priors),
        lambda: engine.current_model)
    engine._append(dict(
        event='arm_decision', task=uid, arm=arm, mode=rec['mode'],
        degraded=rec['degraded'], pool_size=rec['pool_size'],
        chosen=None if rec['chosen'] is None else dict(
            arm=rec['chosen'].arm, pi=dict(rec['chosen'].pi)),
        violations=rec['violations']))

    if arm == 'NONE':
        engine.run_jobs('V1', engine.planned_jobs([task], _NM, ('v',)))
    elif rec['degraded'] or rec['chosen'] is None:
        st.degraded = True            # D10 EARLY_STOP: zero further calls
        state.release_reservations(uid)
    else:
        if rec['mode'] == 'policy':
            state.reserve(uid, rec['chosen'].row['dcost'])
        state.remaining_work_est[uid] = 0.0
        apply_whole_plan(engine, state, task, _NM, rec['chosen'])
        state.release_reservations(uid)

    engine.write_task_summaries([task])
    engine.write_session_summary(1)
    events, _ = load_ledger(out_dir / 'TASK_LEDGER.jsonl')
    post_calls = [dict(node=e['node'], model=e['model'], kind=e['kind'],
                       injected=e['injected'])
                  for e in events if e['event'] == 'call'
                  and e['stage'] not in ('A', 'R1')]

    vv = det.json_value(st.answers.get('v', ''))
    consistent = not any(o['code'] == det.D6 for o in st.observations)
    q_world = 1.0 if (consistent and vv is not None
                      and det.close(vv, task['answer'])) else 0.0

    table = [dict(arm=r['arm'], pi=r['pi'], q=r['q'], dcost=r['dcost'],
                  score=r['score'], feasible=r['feasible'],
                  deficits=r['deficits'])
             for r in rec.get('table', [])]
    return dict(
        arm=arm, mode=rec['mode'], degraded=rec['degraded'],
        pool_size=rec['pool_size'],
        chosen=None if rec['chosen'] is None else dict(
            arm=rec['chosen'].arm, pi=dict(rec['chosen'].pi)),
        post_decision_calls=post_calls, q_world=q_world,
        requests=engine.requests_total, tokens=engine.tokens_total,
        final_r_failed=(st.node_status.get('r') == 'FAILED'),
        violations=rec['violations'], scored_table=table)


def gate2_capability():
    out_root = EVID / 'adm2_arms'
    shutil.rmtree(out_root, ignore_errors=True)
    out_root.mkdir(parents=True)
    episodes = {}
    for arm in ('SS', 'DS', 'SD', 'DD', 'NONE'):
        episodes[arm] = _stub_episode(arm, out_root / arm)

    # determinism: re-run two arms, behavior must reproduce identically
    rerun = {arm: _stub_episode(arm, out_root / f'{arm}_rerun')
             for arm in ('SS', 'SD')}
    deterministic = all(
        rerun[a]['post_decision_calls'] == episodes[a]['post_decision_calls']
        and rerun[a]['chosen'] == episodes[a]['chosen']
        and rerun[a]['q_world'] == episodes[a]['q_world']
        for a in rerun)

    def differs(a, b):
        return (episodes[a]['post_decision_calls']
                != episodes[b]['post_decision_calls']
                or episodes[a]['degraded'] != episodes[b]['degraded'])

    checks = dict(
        DS_vs_SS=differs('DS', 'SS'), SD_vs_SS=differs('SD', 'SS'),
        DD_vs_SS=differs('DD', 'SS'), NONE_vs_SS=differs('NONE', 'SS'),
        SD_vs_DS=differs('SD', 'DS'),
        DD_vs_SD=differs('DD', 'SD'))   # informational; may coincide

    ss, ds, sd, dd = (episodes[a] for a in ('SS', 'DS', 'SD', 'DD'))
    expectations = dict(
        SS_static_local_planned=(
            ss['chosen'] is not None and ss['chosen']['arm'] == 'LOCAL'
            and ss['chosen']['pi'] == {'r': 'medium', 'v': 'coder'}),
        SS_executes_despite_infeasible_quality=(
            ss['degraded'] is False and len(ss['post_decision_calls']) == 2),
        DS_degrades_all_planned_pi_infeasible=(
            ds['degraded']
            and all(any(d['constraint'] == 'q_min'
                        for d in v['deficits'])
                    for v in ds['violations'])
            and {v['arm'].replace('_DYNAMIC', '')
                 for v in ds['violations']} >= {'NONE', 'LOCAL', 'FULL'}),
        DS_pool_covers_three_scopes_note=(
            'pool_size may be 4: FULL_DYNAMIC with planned pi is the SAME '
            'action as the FULL-planned candidate (duplicate enumeration '
            'family), equally infeasible on q_min'),
        DS_zero_calls_after_decision=(len(ds['post_decision_calls']) == 0),
        SD_reassigns_r_to_large=(
            sd['chosen'] is not None
            and sd['chosen']['pi'].get('r') == 'large'),
        SD_correct=(sd['q_world'] == 1.0),
        DD_differs_from_SS_choice=(dd['chosen'] != ss['chosen']),
        NONE_floor_one_call_no_recovery=(
            len(episodes['NONE']['post_decision_calls']) == 1
            and episodes['NONE']['post_decision_calls'][0]['node'] == 'v'
            and episodes['NONE']['q_world'] == 0.0))

    core_pass = (checks['DS_vs_SS'] and checks['SD_vs_SS']
                 and checks['DD_vs_SS'] and deterministic
                 and all(expectations.values()))
    return dict(
        scenario=dict(
            fault=dict(node='r', model='medium', kind='D3_unparseable',
                       answer=D3_FAULT_ANSWER),
            planned=_NM, deadline_s=80.0,
            engine_profile='v3_compat (deterministic 0.2s/100tok)',
            priors='PRIORS_STUB_V1.json (declared synthetic node_profiles: '
                   'r|medium q=0.60, r|large q=0.95, v|coder q=0.85, '
                   'v|large q=0.95, e|* q=0.99; q_min=0.80)'),
        entry_points='deadline_reward_v1/arm_entry.py (frozen): DS/SD/DD '
                     'all route through policy._score_and_pick over '
                     'arm-specific candidate sets; SS is the fixed recipe '
                     'with NO policy scoring and NO constraint filter; '
                     'NONE accepts the failure',
        episodes=episodes,
        determinism_rerun=deterministic,
        behavioral_diffs=checks,
        expectations=expectations,
        DD_vs_SD=('coincide' if not checks['DD_vs_SD'] else 'differ'),
        DD_vs_SD_reason=(
            'SD candidate set (LOCAL pi variants) is a SUBSET of the DD '
            'set (all arms). In the stub prior world DONE nodes carry '
            'observed quality 1.0, so FULL/FULL_DYNAMIC replays never win '
            'the argmax and the DD choice coincides with SD on this '
            'scenario. The candidate sets and scored tables still differ '
            '(DD evaluated the full pool incl. FULL_DYNAMIC); with real '
            'quality priors the argmax can diverge — the supplementary '
            'measurement measures exactly this.'),
        gate_pass=core_pass), core_pass


# ---------------------------------------------------------------- Gate 3
def gate3_isolation():
    tp = json.loads(
        (ROOT / 'collab_scheduler_v1/joint_search_v1/review/'
         'TASK_PANEL_V1.json').read_text())
    eval_uids = set()
    split_counts = {}
    for k in ('tasks_search', 'tasks_test', 'reserve'):
        items = tp.get(k, [])
        split_counts[k] = len(items)
        eval_uids.update(t if isinstance(t, str) else t.get('uid')
                         for t in items)

    fz = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json').read_text())
    all_uids = sorted(t['uid'] for t in fz['tasks'])
    by_uid = {t['uid']: t for t in fz['tasks']}

    led_calls = [json.loads(l) for l in LEDGER.read_text().splitlines()
                 if l.strip()]
    cal_uids = sorted({c['uid'] for c in led_calls
                       if c.get('event') == 'call'})

    available = sorted(set(all_uids) - eval_uids - set(cal_uids))
    supplementary = sorted(random.Random(42).sample(available, 20))
    fault_tasks = sorted(random.Random(20261011).sample(supplementary, 6))

    # determinism: independent re-derivation must match exactly
    assert supplementary == sorted(
        random.Random(42).sample(available, 20))
    assert fault_tasks == sorted(
        random.Random(20261011).sample(supplementary, 6))

    task_snapshot = [dict(uid=u, answer=by_uid[u]['answer'],
                          derivation=by_uid[u]['derivation'])
                     for u in supplementary]

    freeze = dict(
        version='SUPPLEMENTARY_PANEL_FREEZE_v1',
        purpose='DAG task-correctness calibration (DAG_QUALITY_CALIBRATION_'
                'PROTOCOL_v1); INITIAL quality calibration ONLY',
        source=dict(
            frozen200_sha256=_sha(ROOT / 'static_dag_v0/frozen200/'
                                  'FROZEN200_POLICY.json'),
            n_frozen200=len(all_uids),
            evaluation_panel=dict(
                path='collab_scheduler_v1/joint_search_v1/review/'
                     'TASK_PANEL_V1.json',
                sha256=_sha(ROOT / 'collab_scheduler_v1/joint_search_v1/'
                            'review/TASK_PANEL_V1.json'),
                splits=split_counts, n_total=len(eval_uids),
                subset_of_frozen200=eval_uids <= set(all_uids)),
            calibration_panel=dict(
                ledger_sha256=_sha(LEDGER), n_uids=len(cal_uids))),
        exclusion=dict(
            rule='frozen200 MINUS evaluation panel MINUS 1200-call '
                 'calibration panel',
            n_available=len(available)),
        selection=dict(rule='random.Random(42).sample(available, 20), '
                            'sorted; same 20 tasks across all 5 configs '
                            'and both conditions for within-task pairing',
                       n_tasks=20),
        supplementary_uids=supplementary,
        supplementary_sha256=_sha_obj(supplementary),
        fault_assignment=dict(
            rule='random.Random(20261011).sample(supplementary, 6), '
                 'sorted; rate 0.30, node r, type D3_r_unparseable',
            fault_rate=0.3, fault_node='r',
            fault_answer=D3_FAULT_ANSWER,
            seed=20261011, fault_task_uids=fault_tasks),
        task_snapshot=task_snapshot,
        task_snapshot_sha256=_sha_obj(task_snapshot),
        intersection_checks=dict(
            supplementary_vs_evaluation=sorted(
                set(supplementary) & eval_uids),
            supplementary_vs_calibration=sorted(
                set(supplementary) & set(cal_uids)),
            fault_tasks_subset_of_supplementary=set(fault_tasks) <= set(
                supplementary),
            supplementary_subset_of_frozen200=set(supplementary) <= set(
                all_uids)),
        seed_note='Both seeds re-derived independently and asserted equal '
                  'before writing this file.')
    ok = (not freeze['intersection_checks']['supplementary_vs_evaluation']
          and not freeze['intersection_checks']['supplementary_vs_calibration']
          and freeze['intersection_checks']['fault_tasks_subset_of_supplementary']
          and freeze['intersection_checks']['supplementary_subset_of_frozen200'])
    freeze['intersection_test'] = 'PASS' if ok else 'FAIL'
    return freeze


# ---------------------------------------------------------------- Gate 4
def gate4_budget_drill():
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget, StopRun

    caps = dict(wall_seconds=7200.0, new_request_attempts=1200,
                new_total_tokens=800000, request_token_reservation=1700,
                max_output_tokens=4096)
    drill_root = EVID / 'adm4_drill'
    shutil.rmtree(drill_root, ignore_errors=True)
    drill_root.mkdir(parents=True)

    class FakeClock:
        def __init__(self, start=1000.0):
            self.now = start

        def __call__(self):
            return self.now

    def settle(budget, idx, total, out=120):
        budget.settle(idx, dict(
            status='delivered', answer='synthetic',
            usage=dict(prompt_tokens=total - out,
                       completion_tokens=out, total_tokens=total)))

    def fresh(name, clock=None):
        d = drill_root / name
        d.mkdir(parents=True, exist_ok=False)
        return Budget(d, caps, clock=clock or FakeClock())

    drills = {}

    # (a) request cap: 1200 reserves+settles at small actuals, #1201 trips
    b = fresh('a_request_cap')
    trips = None
    try:
        for i in range(1, 1202):
            idx = b.reserve(f'a:{i}')
            settle(b, idx, 200)
    except StopRun as exc:
        trips = str(exc)
    drills['request_cap'] = dict(
        attempts=b.attempts, charged=b.charged, trip=trips,
        expected_trip='request budget',
        pass_=trips == 'request budget' and b.attempts == 1200)

    # (b) token cap: settles at full reservation until the token cap trips
    b = fresh('b_token_cap')
    trips = None
    i = 0
    try:
        while True:
            i += 1
            idx = b.reserve(f'b:{i}')
            settle(b, idx, 1700)
    except StopRun as exc:
        trips = str(exc)
    drills['token_cap'] = dict(
        attempts=b.attempts, charged=b.charged, trip=trips,
        expected_trip='token budget',
        pass_=trips == 'token budget' and b.attempts == 470)

    # (c) wall cap: clock advanced past start+7200
    clk = FakeClock()
    b = fresh('c_wall_cap', clock=clk)
    idx = b.reserve('c:1')
    settle(b, idx, 100, out=40)
    clk.now = 1000.0 + 7200.0 + 0.5
    trips = None
    try:
        b.check()
    except StopRun as exc:
        trips = str(exc)
    drills['wall_cap'] = dict(
        elapsed_s=clk.now - b.start, trip=trips,
        expected_trip='wall budget', pass_=trips == 'wall budget')

    # (d) invalid usage: settlement rejects, FULL reservation retained
    b = fresh('d_invalid_usage')
    idx = b.reserve('d:1')
    charged_before = b.charged
    trips = None
    try:
        b.settle(idx, dict(status='delivered', answer='x'))
    except StopRun as exc:
        trips = str(exc)
    drills['invalid_usage_guard'] = dict(
        trip=trips,
        expected_trip='Missing/invalid usage; full reservation retained',
        charged_before=charged_before, charged_after=b.charged,
        pending_retained=b.pending.get(idx),
        pass_=trips is not None and 'invalid usage' in trips
        and b.charged == charged_before and idx in b.pending)

    # (e) full-plan rehearsal at DECLARED WORST CASE (zero real calls):
    # 800 base calls at per-node p95 token costs + 300 recovery calls
    # (protocol worst case) at r|medium p95 tokens.
    b = fresh('e_plan_rehearsal')
    base_pattern = [826, 1602, 198, 177]   # e1|large e2|large r|medium v|coder
    seq = []
    for _ in range(200):                   # 5 configs x 2 cond x 20 tasks
        seq.extend(base_pattern)
    seq.extend([198] * 300)                # worst-case recovery (r|medium p95)
    status = None
    try:
        for i, tok in enumerate(seq, 1):
            idx = b.reserve(f'e:{i}')
            settle(b, idx, tok)
        status = 'COMPLETED_WITHIN_CAPS'
    except StopRun as exc:
        status = f'STOPPED: {exc}'
    drills['plan_rehearsal_worst_case'] = dict(
        calls_planned=len(seq),
        requests=b.attempts, actual_tokens=b.actual_tokens,
        charged=b.charged, caps=dict(requests=1200, tokens=800000,
                                     wall_s=7200),
        headroom_requests=1200 - b.attempts,
        headroom_tokens=800000 - b.actual_tokens,
        status=status,
        pass_=status == 'COMPLETED_WITHIN_CAPS')

    # (f) resume refusal: a partially-spent ledger must never silently resume
    d = drill_root / 'a_request_cap'
    try:
        Budget(d, caps, clock=FakeClock())
        refused = False
    except ValueError as exc:
        refused = 'explicit reconciliation' in str(exc)
    drills['resume_refusal'] = dict(pass_=refused)

    all_pass = all(v['pass_'] for v in drills.values())
    return dict(
        mechanism='PRODUCTION Budget class '
                  '(collab_scheduler_v1/joint_search_smoke/proposal_v2/'
                  'smoke_runner.py): reserve-then-settle with per-request '
                  'token reservation, charged-token accounting, wall clock, '
                  'append-only DISPATCH ledger',
        caps=caps,
        reservation_note='reservation 1700 >= max single-call p95 tokens '
                         '(e2|large tok_p95=1602) so every legal settle '
                         'fits; settle adjusts the charge to actual',
        drills=drills, artifacts_dir=str(drill_root),
        zero_model_calls=True, gate_pass=all_pass), all_pass


# ---------------------------------------------------------------- Gate 5
def gate5_scope():
    return dict(
        statement=(
            'The supplementary measurement (~1000 real model calls) is '
            'INITIAL QUALITY CALIBRATION ONLY. It estimates P(task correct '
            '| config, condition) under v2.1 scoring for the five frozen '
            'configs, to validate that Q_min=0.80 is a reasonable '
            'feasibility threshold and to bind per-cell quality priors. '
            'It is NOT: (1) strategy selection — the best static arm for '
            'the SS contrast is selected on independent data per Protocol '
            'V2.3 §3, never on this panel; (2) a policy-superiority claim '
            '— no hypothesis test on this panel supports H1-H4/S1; (3) an '
            'on-time probability validation — node latency distributions '
            'were measured separately and path aggregation needs its own '
            'validation. With 20 tasks per cell the binomial CI is wide '
            '(17/20 -> 64-95%): overlapping CIs are expected and '
            'uninterpretable as superiority. Q_min=0.80, eps=0.10, reward '
            'weights and every frozen formula remain UNCHANGED by '
            'construction; no result of this measurement may be used to '
            'retune them (any change would be a new frozen version with '
            'explicit rationale).'),
        forbidden_uses=[
            'selecting the SS static recipe on this panel',
            'claiming DD > SS / joint-policy superiority',
            'adjusting Q_min, eps, lambda weights, or reward formulas',
            'treating node-format rates as task correctness'],
        allowed_uses=[
            'per-(node, model) quality prior binding for the predictor',
            'sanity check that Q_min=0.80 is not vacuous or impossible',
            'diagnostic node format-rate reporting (secondary)'])


# ---------------------------------------------------------------- main
def main():
    with no_socket():
        g1, families = gate1_statistics()
        g2, g2_pass = gate2_capability()
        g3 = gate3_isolation()
        g4, g4_pass = gate4_budget_drill()
        g5 = gate5_scope()

        (HERE / 'PRIORS_REAL_V1_families.json').write_text(json.dumps(dict(
            version='PRIORS_REAL_V1_families_v1',
            klass='distribution_family_binding',
            note='Companion binding for PRIORS_REAL_V1.json per '
                 'CALIBRATION_FREEZE_PREREQUISITES.json estimator_binding. '
                 'PRIORS_REAL_V1.json itself is NOT modified. Binding is '
                 'frozen before confirmation data; changes require a new '
                 'version with explicit rationale.',
            ledger_sha256=_sha(LEDGER),
            computed_by='deadline_reward_v1/calibration_admission_check.py '
                        'gate1',
            script_sha256=_sha(Path(__file__)),
            protocol=f'Shapiro-Wilk + D Agostino K2, Bonferroni within '
                     f'cell (2 tests), alpha={ALPHA}',
            counts=dict(normal=g1['n_normal'], lognormal=g1['n_lognormal'],
                        empirical=g1['n_empirical']),
            families=families,
            estimator_rule='LOGNORM -> lognormal params (see '
                           'ADMISSION_CHECK.json gate1.per_cell); '
                           'EMPIRICAL -> empirical CDF (latencies saved); '
                           'NORM -> unused (0 cells); E1 normal estimator '
                           'NOT supported by the data',
        ), indent=1, ensure_ascii=False))

        (EVID / 'SUPPLEMENTARY_PANEL_FREEZE.json').write_text(
            json.dumps(g3, indent=1, ensure_ascii=False))

        report = dict(
            admission_check='calibration_supplementary_pre_authorization',
            zero_model_calls=True,
            socket_blocked=True,
            gate1_statistics=g1, gate2_capability=g2, gate3_isolation=g3,
            gate4_budget_drill=g4, gate5_scope=g5,
            summary=dict(
                gate1=f"{g1['n_normal']} normal / {g1['n_lognormal']} "
                      f"lognormal / {g1['n_empirical']} empirical "
                      f"({len(g1['changes_vs_shapiro_only_v2'])} changed "
                      'vs Shapiro-only V2)',
                gate2='PASS' if g2_pass else 'FAIL',
                gate3=g3['intersection_test'],
                gate4='PASS' if g4_pass else 'FAIL',
                gate5='stated',
                overall='ALL GATES PASS' if (
                    g2_pass and g3['intersection_test'] == 'PASS'
                    and g4_pass) else 'GATES PENDING'))
        (EVID / 'ADMISSION_CHECK.json').write_text(
            json.dumps(report, indent=1, ensure_ascii=False))

    print('=== GATE 1 statistics (complete frozen protocol) ===')
    print(f"  {g1['n_normal']} normal / {g1['n_lognormal']} lognormal / "
          f"{g1['n_empirical']} empirical of {g1['n_cells']} cells")
    for c, ch in g1['changes_vs_shapiro_only_v2'].items():
        print(f"  changed vs V2: {c}: {ch['v2_shapiro_only']} -> "
              f"{ch['complete']}")
    print('=== GATE 2 five-arm capability (stub, frozen entry points) ===')
    for arm in ('SS', 'DS', 'SD', 'DD', 'NONE'):
        e = g2['episodes'][arm]
        ch = e['chosen']
        print(f"  {arm:4s} mode={e['mode']:13s} "
              f"degraded={str(e['degraded']):5s} "
              f"chosen={ch['arm'] + ':' + str(ch['pi']) if ch else None}")
        print(f"       calls={e['post_decision_calls']} "
              f"q_world={e['q_world']}")
    print(f"  diffs: {g2['behavioral_diffs']} (DD vs SD: {g2['DD_vs_SD']})")
    print(f"  gate2: {'PASS' if g2_pass else 'FAIL'}")
    print('=== GATE 3 isolation ===')
    print(f"  {g3['intersection_test']}: 20 tasks from "
          f"{g3['exclusion']['n_available']} available; fault tasks "
          f"{len(g3['fault_assignment']['fault_task_uids'])}")
    print('=== GATE 4 budget drill (real Budget class, zero calls) ===')
    for name, d in g4['drills'].items():
        detail = d.get('trip') or d.get('status') or ''
        print(f"  {name}: {'PASS' if d['pass_'] else 'FAIL'}"
              f"{f' ({detail})' if detail else ''}")
    print('=== GATE 5 scope: stated ===')
    print(f"OVERALL: {report['summary']['overall']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
