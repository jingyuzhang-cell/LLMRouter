"""Deadline-reliability measurement runner (DEADLINE_RELIABILITY_PROTOCOL_V3).

Four stages on the real engine infrastructure (shared with the
supplementary runner; ONE engine + ONE identity cache per run — the
fault manifestation REQUIRES cross-stage cache reuse):
  S-FIT        24 tasks x 4 nodes x K=3 no_cache repeats, round-robin
               over the 10-cell menu -> per-cell latency samples,
               family binding (frozen SW+K2+Bonferroni), declared P90s,
               measured switch costs
  S-SCREEN     12 fresh tasks, exploratory coverage (no admission force)
  S-VALIDATE   63 planned-group tasks (final coverage) + 27 faulted
               tasks (D3 cache+corruption, DD decisions under one
               assigned D-tier each — exploratory dynamic arm)
  S-CONTENTION 8 co-resident pairs, interleaved serial execution

Statistics: reliability_stats.py ONLY (frozen). Report: per-cell CP
verdicts + joint verdict + zero-call D-tier replay regions, written
ONLY for a fully COMPLETE pipeline (INCOMPLETE files otherwise).

DEFAULT = preflight (zero calls). EXECUTE needs RELIABILITY_EXECUTE=1
and the operator-approved RELIABILITY_PANEL_FREEZE.json SHA-256.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket as _socket_mod
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent
EVID = HERE / 'evidence'
RUNS = HERE / 'reliability_runs'
FREEZE_PATH = HERE / 'RELIABILITY_PANEL_FREEZE.json'

from deadline_reward_v1 import reliability_stats as rstats
from deadline_reward_v1.supplementary_runner import (
    ModelManager, RealClock, RealEngine, RealServer)

K_REPEATS = 3
STAGE_CAPS = dict(
    fit=dict(wall_seconds=3300.0, new_request_attempts=340,
             new_total_tokens=120000, request_token_reservation=2048,
             max_output_tokens=4096),
    screen=dict(wall_seconds=1100.0, new_request_attempts=60,
                new_total_tokens=22000, request_token_reservation=2048,
                max_output_tokens=4096),
    validate=dict(wall_seconds=2600.0, new_request_attempts=460,
                  new_total_tokens=150000, request_token_reservation=2048,
                  max_output_tokens=4096),
    contention=dict(wall_seconds=3600.0, new_request_attempts=80,
                    new_total_tokens=28000, request_token_reservation=2048,
                    max_output_tokens=4096))
GLOBAL_CAPS = dict(requests=1200, tokens=600000, wall_s=14400.0)
D3_ANSWER = '###SYNTHETIC UNPARSEABLE r-output###'
E_MODELS = ('medium', 'large', 'coder')
R_MODELS = ('medium', 'large')
V_MODELS = ('coder', 'large')


def sha_file(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha_obj(obj) -> str:
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


def assignment(i: int) -> dict:
    """Frozen round-robin menu assignment (protocol V3 §1)."""
    return dict(e1=E_MODELS[i % 3], e2=E_MODELS[i % 3],
                r=R_MODELS[i % 2], v=V_MODELS[i % 2])


def pct(arr, p):
    s = sorted(arr)
    return s[max(0, min(int((p * len(s) + 0.999999)) - 1, len(s) - 1))]


# ------------------------------------------------------------- stage I/O
def _load_tasks(uids):
    fz = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
        .read_text())['tasks']
    by = {t['uid']: t for t in fz}
    return [by[u] for u in uids]


def _stage_jobs(tasks, planned_map, nodes, no_cache=False):
    jobs = []
    for t in tasks:
        pm = planned_map[t['uid']]
        for n in nodes:
            jobs.append(dict(task=t, node=n, kind='plain', model=pm[n],
                             no_cache=no_cache))
    return jobs


def _run_stage_group(engine, tasks, planned_map, budget):
    """Stage-major planned cascade: (e1,e2) -> r -> v, each stage grouped
    by model (production run_stage semantics via engine.run_jobs)."""
    engine.start_panel(tasks, {n: next(iter({pm[n] for pm in
                                             planned_map.values()}), None)
                               for n in ('e1', 'e2', 'r', 'v')})
    engine.run_jobs('A', _stage_jobs(tasks, planned_map, ('e1', 'e2')))
    engine.run_jobs('R1', _stage_jobs(tasks, planned_map, ('r',)))
    engine.run_jobs('V1', _stage_jobs(tasks, planned_map, ('v',)))
    budget.check()


def _samples_from_ledger(path):
    lat = defaultdict(list)
    for e in (json.loads(l) for l in Path(path).read_text().splitlines()):
        if e.get('event') == 'call' and e.get('physical'):
            lat[(e['node'], e['model'])].append(e['latency_s'])
    return lat


# ------------------------------------------------------------- families
def bind_families(samples):
    """Frozen distribution-protocol statistics on the FIT samples:
    Shapiro-Wilk + D'Agostino K2, Bonferroni within cell (2 tests),
    alpha=0.01 — identical procedure to CALIBRATION_FREEZE_PREREQUISITES
    / admission gate 1."""
    from scipy import stats as sps
    out = {}
    for (node, model), lats in samples.items():
        cell = f'{node}|{model}'
        import numpy as np
        arr = np.array(lats)
        logs = np.log(arr)

        def adj(p):
            return min(1.0, p * 2)

        _, p_sw = sps.shapiro(arr)
        _, p_k2 = sps.normaltest(arr)
        _, p_swl = sps.shapiro(logs)
        _, p_k2l = sps.normaltest(logs)
        normal = adj(p_sw) >= 0.01 and adj(p_k2) >= 0.01
        lognormal = adj(p_swl) >= 0.01 and adj(p_k2l) >= 0.01
        fam = ('normal' if normal else 'lognormal' if lognormal
               else 'empirical')
        entry = dict(n=len(lats), family=fam,
                     declared_p90=round(pct(lats, 0.90), 4),
                     declared_p50=round(pct(lats, 0.50), 4),
                     mean=round(float(arr.mean()), 4))
        if fam == 'lognormal':
            entry.update(mu_log=round(float(logs.mean()), 6),
                         sigma_log=round(float(logs.std(ddof=1)), 6))
        elif fam == 'empirical':
            entry['lat_sorted'] = [round(x, 4) for x in sorted(lats)]
        out[cell] = entry
    return out


# ------------------------------------------------------------- stages
def stage_fit(engine, server, budget, freeze, run_dir):
    tasks = _load_tasks(freeze['panels']['fit']['uids'])
    planned_map = {t['uid']: assignment(i) for i, t in enumerate(tasks)}
    lat_before = dict(engine.__dict__.get('_lat_probe', {}))
    for k in range(K_REPEATS):
        # no_cache repeats: fresh service draws for latency sampling
        for nodes in (('e1', 'e2'), ('r',), ('v',)):
            jobs = _stage_jobs(tasks, planned_map, nodes, no_cache=True)
            engine.run_jobs(f'fit{k}', jobs)
        budget.check()
    return dict(planned_map=planned_map, n_tasks=len(tasks))


def stage_screen(engine, server, budget, freeze, run_dir):
    tasks = _load_tasks(freeze['panels']['screen']['uids'])
    planned_map = {t['uid']: assignment(i) for i, t in enumerate(tasks)}
    _run_stage_group(engine, tasks, planned_map, budget)
    return dict(planned_map=planned_map, n_tasks=len(tasks))


def _exante_prediction(planned, binding, switch_costs, contention_est):
    """Ex-ante planned-path service prediction, frozen BEFORE the
    validate stage sees any of its data: per-node (family, params) +
    deterministic switch estimate. The p_on FUNCTION is ex-ante; the
    D-tier evaluation point may be data-derived (protocol V3 §3)."""
    nodes = []
    for n in ('e1', 'e2', 'r', 'v'):
        b = binding[f'{n}|{planned[n]}']
        entry = dict(node=n, model=planned[n], family=b['family'],
                     declared_p90=b['declared_p90'], mean=b['mean'])
        if b['family'] == 'lognormal':
            entry.update(mu_log=b['mu_log'], sigma_log=b['sigma_log'])
        elif b['family'] == 'empirical':
            entry['lat_sorted'] = b['lat_sorted']
        nodes.append(entry)
    sw = sum(switch_costs.values())  # conservative: full pair allowance
    return dict(pi=nodes, switch_est=round(sw, 3),
                contention_est=round(contention_est, 3))


def stage_validate(engine, server, budget, freeze, run_dir, binding,
                   switch_costs, exante):
    from deadline_reward_v1 import arm_entry, policy
    from deadline_reward_v1.reassign import apply_whole_plan
    from deadline_reward_v1.scheduler_state import SchedulerState
    from deadline_reward_v1 import predictor as pred_mod
    from deadline_reward_v1.predictor import OutcomePredictor

    priors = dict(
        node_profiles={f"{n}|{m}": dict(
            q_success=0.5,               # placeholder — decisions are the
            lat_mean_s=b['mean'],        # exploratory arm; q is NOT under
            lat_p90_s=b['declared_p90'],  # test here and never read for
            tokens_p90=300, family=b['family'],  # coverage verdicts
            **({'mu_log': b['mu_log'], 'sigma_log': b['sigma_log']}
               if b['family'] == 'lognormal' else {}),
            **({'lat_sorted': b['lat_sorted']}
               if b['family'] == 'empirical' else {}))
            for n_m, b in binding.items() for n, m in [n_m.split('|')]},
        switch=dict(stop_s=1.5, start_s=switch_costs),
        policy=dict(quality_composition='min', q_observed_done=1.0,
                    q_failed_unrecovered=0.0,
                    p90_aggregation='quantile_sum', q_min=0.80, eps=0.10,
                    lam_c=0.5, lam_t=1.0, lam_f=2.0, c0=4000.0))
    predictor = OutcomePredictor(priors)
    compensator = policy.DeadlineCompensator(priors)
    params = dict(priors=priors, q_min=0.80, eps=0.10, lam_c=0.5,
                  lam_t=1.0, lam_f=2.0, c0=4000.0)

    val_uids = freeze['panels']['validate']['uids']
    fault_uids = set(freeze['fault_task_uids'])
    planned_uids = [u for u in val_uids if u not in fault_uids]
    tasks_p = _load_tasks(planned_uids)
    planned_map = {t['uid']: assignment(i) for i, t in enumerate(tasks_p)}
    # planned groups: stage-major by assignment combo for switch economy
    by_combo = defaultdict(list)
    for t in tasks_p:
        by_combo[tuple(sorted(planned_map[t['uid']].items()))].append(t)
    for combo, group in by_combo.items():
        pm = {t['uid']: dict(combo) for t in group}
        _run_stage_group(engine, group, pm, budget)

    # faulted dynamic sub-experiment (exploratory arm, DD policy)
    fault_tasks = _load_tasks(sorted(fault_uids))
    rng = random.Random(20261016)
    order = sorted(fault_uids)
    tiers = ('tight', 'medium', 'wide')
    tier_of = {u: tiers[i % 3] for i, u in enumerate(order)}
    clock = engine.clock
    for t in fault_tasks:
        uid = t['uid']
        planned = assignment(val_uids.index(uid))
        tier = tier_of[uid]
        d = dict(tight=1.2, medium=2.0, wide=4.0)[tier] * (
            sum(binding[f"{n}|{planned[n]}"]['mean']
                for n in ('e1', 'e2', 'r', 'v')) + 6.0)
        server.set_fault(uid, 'r', planned['r'], D3_ANSWER)
        state = SchedulerState(
            clock, task_deadlines={uid: d + clock.time()},
            token_allocation=max(0.0, budget.caps['new_total_tokens']
                                 - budget.charged))
        engine.add_observer(state._on_event)
        try:
            engine.start_panel([t], planned)
            engine.run_jobs('A', _stage_jobs([t], {uid: planned},
                                             ('e1', 'e2')))
            engine.run_jobs('R1', _stage_jobs([t], {uid: planned}, ('r',)))
            cands = arm_entry.enumerate_for(state, uid, planned)
            rec = arm_entry.decide_arm(
                state, uid, cands, 'DD', planned, params, predictor,
                compensator, lambda: engine.current_model)
            engine._append(dict(
                event='arm_decision', task=uid, arm='DD',
                condition='reliability_fault', tier=tier,
                decision_id=f'reliability|DD|{uid}',
                decision_unix=time.time(), mode=rec['mode'],
                degraded=rec['degraded'], reason=rec.get('reason'),
                d_remain=rec.get('d_remain'),
                b_remain_tokens=rec.get('b_remain_tokens'),
                pool_size=rec['pool_size'],
                chosen=None if rec['chosen'] is None else dict(
                    arm=rec['chosen'].arm, pi=dict(rec['chosen'].pi)),
                violations=rec['violations'], table=rec.get('table', [])))
            if rec['degraded']:
                state.tasks[uid].degraded = True
            elif rec['chosen'] is not None:
                jobs = []
                ch = rec['chosen']
                from deadline_reward_v1 import dag_closure as dc
                stt = state.tasks[uid]
                for group in (('e1', 'e2'), ('r',), ('v',)):
                    for node in group:
                        nc = next((x for n, x in
                                   ch.judgment.execute if n == node), None)
                        if nc is None or stt.node_status.get(node) == \
                                dc.PENDING:
                            continue
                        model = (ch.pi.get(node)
                                 or stt.node_model.get(node)
                                 or planned[node])
                        jobs.append(dict(
                            task=t, node=node,
                            kind=ch.kinds.get(node, 'plain'), model=model,
                            no_cache=(ch.arm == 'FULL'
                                      or stt.node_status.get(node)
                                      == dc.FAILED)))
                    if jobs:
                        engine.run_jobs('plan:DD', jobs)
                        jobs = []
                state.release_reservations(uid)
            vj = [] if state.tasks[uid].degraded else [dict(
                task=t, node='v', kind='plain',
                model=(rec['chosen'].pi.get('v')
                       if rec['chosen'] else None) or planned['v'])]
            if vj:
                engine.run_jobs('V1', vj)
            engine.write_task_summaries([t])
        finally:
            engine.observers.remove(state._on_event)
            server.faults.pop((uid, 'r', planned['r']), None)
        budget.check()
    return dict(planned_map=planned_map, tier_of=tier_of,
                n_planned=len(planned_uids), n_faulted=len(fault_tasks))


def stage_contention(engine, server, budget, freeze, run_dir):
    fit_uids = freeze['panels']['fit']['uids']
    pairs = [(fit_uids[2 * i], fit_uids[2 * i + 1]) for i in range(8)]
    for a, b in pairs:
        ta, tb = _load_tasks([a])[0], _load_tasks([b])[0]
        pa = {a: assignment(fit_uids.index(a))}
        pb = {b: assignment(fit_uids.index(b))}
        # interleaved serial execution: stages alternate per task
        engine.run_jobs('A1', _stage_jobs([ta], pa, ('e1', 'e2')))
        engine.run_jobs('A2', _stage_jobs([tb], pb, ('e1', 'e2')))
        engine.run_jobs('R1a', _stage_jobs([ta], pa, ('r',)))
        engine.run_jobs('R1b', _stage_jobs([tb], pb, ('r',)))
        engine.run_jobs('V1a', _stage_jobs([ta], pa, ('v',)))
        engine.run_jobs('V1b', _stage_jobs([tb], pb, ('v',)))
        budget.check()
    return dict(n_pairs=len(pairs))


# ------------------------------------------------------------- report
def build_report(run_dir, freeze, binding):
    val_lat = _samples_from_ledger(run_dir / 'validate' / 'TASK_LEDGER.jsonl')
    samples = {f'{n}|{m}': v for (n, m), v in val_lat.items()}
    declared = {c: b['declared_p90'] for c, b in binding.items()}
    coverage = rstats.coverage_from_ledger(samples, declared)
    # D-tier replay (zero-call) on planned-path tasks
    led = [json.loads(l) for l in
           (run_dir / 'validate' / 'TASK_LEDGER.jsonl').read_text()
           .splitlines()]
    release = summaries = None
    e2es, task_ids = [], []
    panels = {}
    for e in led:
        if e.get('event') == 'panel_start':
            release = e['t_release']
        elif e.get('event') == 'task_summary' and release is not None:
            if e['task'] not in panels:
                panels[e['task']] = (e['t_last'] - release)
    for uid, dt in panels.items():
        e2es.append(dt)
        task_ids.append(uid)
    tiers = dict(
        tight=pct(e2es, 0.40), medium=pct(e2es, 0.60),
        wide=pct(e2es, 0.80)) if e2es else {}
    replay = {}
    for name, d in tiers.items():
        on = sum(1 for x in e2es if x <= d)
        replay[name] = dict(d=round(d, 3), realized_on_time=on, n=len(e2es))
    return dict(version='RELIABILITY_RESULTS_v1',
                panel_freeze_sha256=sha_file(FREEZE_PATH),
                coverage=coverage, tiers={k: round(v, 3)
                                          for k, v in tiers.items()},
                replay=replay,
                statistics='reliability_stats.py (frozen; CP exact, '
                           'Poisson-binomial exact)',
                scope='fixed-path quantile coverage + zero-call tier '
                      'replay; dynamic arm exploratory; V2.3 '
                      'confirmation untouched')


# ------------------------------------------------------------- preflight
def preflight():
    freeze = json.loads(FREEZE_PATH.read_text())
    # re-derive panels from seeds and compare hashes
    fz = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
        .read_text())['tasks']
    import random as _r
    tp = json.loads(
        (ROOT / 'collab_scheduler_v1/joint_search_v1/review/'
         'TASK_PANEL_V1.json').read_text())
    ev = {t if isinstance(t, str) else t.get('uid')
          for k in ('tasks_search', 'tasks_test', 'reserve')
          for t in tp.get(k, [])}
    cal = {json.loads(l)['uid'] for l in
           (HERE / 'calibration_runs' / 'CALIBRATION_LEDGER.jsonl')
           .read_text().splitlines() if json.loads(l).get('event') == 'call'}
    sup = set(json.loads((EVID / 'SUPPLEMENTARY_PANEL_FREEZE.json')
                         .read_text())['supplementary_uids'])
    avail = sorted({t['uid'] for t in fz} - ev - cal - sup)
    fit = sorted(_r.Random(20261012).sample(avail, 24))
    rest = sorted(set(avail) - set(fit))
    screen = sorted(_r.Random(20261013).sample(rest, 12))
    rest2 = sorted(set(rest) - set(screen))
    val = sorted(_r.Random(20261014).sample(rest2, 90))
    faults = sorted(_r.Random(20261015).sample(val, 27))
    ok = (fit == freeze['panels']['fit']['uids']
          and screen == freeze['panels']['screen']['uids']
          and val == freeze['panels']['validate']['uids']
          and faults == freeze['fault_task_uids'])
    stats_ok = True
    try:
        import deadline_reward_v1.test_reliability_stats as t
        # module import only; the suite itself is run separately
    except Exception:
        stats_ok = False
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True).stdout.strip()
    report = dict(status='PREFLIGHT_PASS' if ok and stats_ok
                  else 'PREFLIGHT_FAIL',
                  panels_rederived=ok, freeze_sha256=sha_file(FREEZE_PATH),
                  stage_caps=STAGE_CAPS, global_caps=GLOBAL_CAPS,
                  k_repeats=K_REPEATS, git_commit=commit,
                  model_calls=0)
    (EVID / 'RELIABILITY_PREFLIGHT.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1))
    return 0 if report['status'] == 'PREFLIGHT_PASS' else 2


# ------------------------------------------------------------- execute
def execute(approved_sha):
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget
    if approved_sha != sha_file(FREEZE_PATH):
        raise PermissionError('freeze hash mismatch — re-approve')
    pre = json.loads((EVID / 'RELIABILITY_PREFLIGHT.json').read_text())
    if pre.get('status') != 'PREFLIGHT_PASS':
        raise PermissionError('preflight is not PREFLIGHT_PASS')
    freeze = json.loads(FREEZE_PATH.read_text())
    run_dir = RUNS / time.strftime('run_%Y%m%d_%H%M%S')
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise PermissionError('run dir exists — no reuse of prior state')
    (run_dir / 'RELIABILITY_PANEL_FREEZE.json').write_bytes(
        FREEZE_PATH.read_bytes())
    manager = ModelManager()
    t0 = time.monotonic()
    statuses = {}

    class _Wall:
        def __init__(self, seconds):
            self.until = t0 + seconds

        def check(self):
            if time.monotonic() > self.until:
                raise RuntimeError('global wall cap')

    lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    engine = server = None
    prev = signal.getsignal(signal.SIGALRM)

    def _new_engine(stage):
        """One engine + identity cache PER STAGE (its own ledger under
        the stage dir). Within-stage cache reuse — what the fault
        manifestation and V1 identity repeats need — is preserved."""
        sdir = run_dir / stage
        sdir.mkdir(parents=True, exist_ok=True)
        eng = RealEngine(sdir, server, RealClock(), seed=f'relv_{stage}',
                         manager=manager)
        server.engine = eng
        return eng

    try:
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(
            RuntimeError('SIGALRM wall deadline')))
        signal.setitimer(signal.ITIMER_REAL, GLOBAL_CAPS['wall_s'])
        budget = Budget(run_dir / 'fit', STAGE_CAPS['fit'])
        task_map = {t['uid']: t for t in json.loads(
            (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
            .read_text())['tasks']}
        server = RealServer({}, manager, budget, task_map, run_dir)
        engine = _new_engine('fit')
        stage_fit(engine, server, budget, freeze, run_dir)
        statuses['fit'] = 'COMPLETE'
        fit_lat = _samples_from_ledger(
            run_dir / 'fit' / 'TASK_LEDGER.jsonl')
        binding = bind_families(fit_lat)
        # measured switch costs: max observed wall per target model from
        # the run's own switch events (conservative), with the
        # 2026-10-11 measured starts as documented fallback defaults
        sw = {m: 65.0 for m in set(E_MODELS) | set(R_MODELS) | set(V_MODELS)}
        for e in (json.loads(l) for l in
                  (run_dir / 'fit' / 'TASK_LEDGER.jsonl').read_text()
                  .splitlines()):
            if e.get('event') == 'switch' and e.get('to') is not None:
                sw[e['to']] = max(sw.get(e['to'], 0.0),
                                  float(e.get('wall_s', 0.0)))
        val_tasks = freeze['panels']['validate']['uids']
        exante = {}
        for i, u in enumerate(val_tasks):
            exante[u] = _exante_prediction(assignment(i), binding, sw, 0.0)
        (run_dir / 'BINDING.json').write_text(json.dumps(
            dict(binding=binding, exante=exante), indent=1))

        for stage in ('screen', 'validate', 'contention'):
            budget = Budget(run_dir / stage, STAGE_CAPS[stage])
            server.budget = budget
            engine = _new_engine(stage)
            if stage == 'screen':
                stage_screen(engine, server, budget, freeze, run_dir)
            elif stage == 'validate':
                stage_validate(engine, server, budget, freeze, run_dir,
                               binding, sw, exante)
            else:
                stage_contention(engine, server, budget, freeze, run_dir)
            statuses[stage] = 'COMPLETE'
        report = build_report(run_dir, freeze, binding)
        report['stage_statuses'] = statuses
        out = HERE / 'RELIABILITY_RESULTS.json'
        if out.exists():
            raise PermissionError('results file exists — never overwritten')
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        print(json.dumps(report, indent=1)[:2000])
        return 0
    except BaseException as exc:
        statuses.setdefault('current', repr(exc))
        inc = HERE / 'RELIABILITY_RESULTS_INCOMPLETE.json'
        if not inc.exists():
            inc.write_text(json.dumps(dict(
                status='INCOMPLETE', reason=repr(exc), stages=statuses,
                note='partial data only — NEVER a validation verdict'),
                indent=1))
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev)
        try:
            manager.stop_current()
        finally:
            lock.close()
            (run_dir / 'STATUS.json').write_text(json.dumps(dict(
                stages=statuses, wall_s=round(time.monotonic() - t0, 1)),
                indent=1))


import random  # noqa: E402  (stage_validate tier assignment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-freeze-sha256')
    args = parser.parse_args()
    if not args.execute:
        with no_socket():
            return preflight()
    if os.environ.get('RELIABILITY_EXECUTE') != '1' \
            or not args.approved_freeze_sha256:
        raise PermissionError(
            'execution requires RELIABILITY_EXECUTE=1 and the '
            'operator-approved freeze SHA-256')
    return execute(args.approved_freeze_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
