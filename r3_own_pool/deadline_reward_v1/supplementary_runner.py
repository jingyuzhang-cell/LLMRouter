"""Supplementary DAG-quality measurement runner (~1000 real calls).

Executes DAG_QUALITY_CALIBRATION_PROTOCOL_v1: 5 configs (SS/DS/SD/DD/NONE
via the frozen arm_entry.py selection layer) x 2 conditions (clean,
fault30_D3 on the frozen 6-task fault set) x 20 frozen tasks, full real
4-node cascade (e1->e2->r->v), v2.1 terminal scoring ONLY.

DEFAULT = PREFLIGHT: zero real model calls. Verifies every frozen hash,
rebuilds the decision beliefs from the 18k real formal-campaign trajectory
records (production-parity parse rates; mirror-vs-production divergence
must be NONE), validates profiles, and prints the execution plan +
budget arithmetic. Writes evidence/SUPPLEMENTARY_PREFLIGHT.json.

EXECUTE requires: SUPPLEMENTARY_EXECUTE=1, --approved-freeze-sha256 (the
operator-approved SUPPLEMENTARY_PANEL_FREEZE.json hash), the GPU lock, and
the production Budget caps (1200 requests / 800K tokens / 7200 s wall).

Declared scaffolding (NOT measured quantities):
  - D = 3600.0 s per task: deadlines are inert by design. Real switch
    costs (~60-71 s/start) under the frozen per-call switch bound make any
    smaller D infeasible for every multi-call plan; timeliness is outside
    this measurement's scope (ADMISSION_CHECK gate 5).
  - Decision beliefs: production-parity parse rates from the formal
    trajectories (parse-success proxy, NOT task correctness; PRIORS_REAL
    _V1 q_success stays INVALID and unused). Latency/tokens from the real
    1200-call calibration (clean cells).
Execution semantics: one engine + one cache for the whole run (M3 identity
reuse across cells is the deployment semantics); stage-batched real calls;
metered corruption faults (answer replaced AFTER the charged call);
SchedulerState per cell (attach/detach); batched plan application mirrors
reassign.apply_whole_plan job construction exactly (per-task job tuples
recorded for audit).

Run: python3 -m deadline_reward_v1.supplementary_runner [--execute ...]
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
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
EVID = HERE / 'evidence'
FREEZE_PATH = EVID / 'SUPPLEMENTARY_PANEL_FREEZE.json'
PROTOCOL_PATH = HERE / 'DAG_QUALITY_CALIBRATION_PROTOCOL.json'
RUNS = HERE / 'supplementary_runs'

PLANNED = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}
ARMS = ('SS', 'DS', 'SD', 'DD', 'NONE')
CONDITIONS = ('clean', 'fault30_D3')
D_SCAFFOLD = 3600.0
PARAMS = dict(q_min=0.80, eps=0.10, lam_c=0.5, lam_t=1.0, lam_f=2.0,
              c0=4000.0)
CAPS = dict(wall_seconds=7200.0, new_request_attempts=1200,
            new_total_tokens=800000, request_token_reservation=2048,
            max_output_tokens=4096)
TRAJ_GLOB = 'collab_scheduler_v1/joint_search_v1/formal_campaign_v2*/' \
            '**/TRAJECTORY.jsonl'


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


# ---------------------------------------------------------------- beliefs
def build_beliefs():
    """Decision beliefs from the real formal-campaign trajectories (zero
    calls): per-(node, model) production-parity parse rates. The
    deadline_reward_v1.detection mirror must agree with production on
    EVERY record (fence + exec_calc parity fixes)."""
    from static_dag_v0.multidag_dynamic import (json_value, parse_facts_safe,
                                                value_of)
    from deadline_reward_v1 import detection as det

    files = sorted(ROOT.glob(TRAJ_GLOB))
    ctx_answers, records = {}, {}
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            r = e.get('response')
            if not isinstance(r, dict) or r.get('status') != 'delivered' \
                    or r.get('injected_fault'):
                continue
            parts = e['key'].split(':')
            sc = e['event_id'].split(':')[0]
            node, uid, label = parts[3], parts[4], parts[2]
            ctx_answers.setdefault((sc, label, uid, node),
                                   (e['model'], e['prompt_sha256'],
                                    r['answer']))
            records.setdefault((node, e['model'], e['prompt_sha256']),
                               (sc, label, uid, r['answer']))
    rate = defaultdict(lambda: [0, 0])
    diverge = []
    for (node, model, _sha), (sc, label, uid, ans) in records.items():
        if node == 'r':
            a1 = ctx_answers.get((sc, label, uid, 'e1'))
            a2 = ctx_answers.get((sc, label, uid, 'e2'))
            if a1 is None or a2 is None:
                continue
            f1, _ = parse_facts_safe(a1[2])
            f2, _ = parse_facts_safe(a2[2])
            fl = f1['facts'] + f2['facts']
            _, ep = value_of(ans, dict(facts=fl))
            _, em = det.value_of(ans, fl)
            if int(not ep) != int(not em):
                diverge.append(dict(node=node, model=model, uid=uid))
            rate[(node, model)][0] += int(not ep)
            rate[(node, model)][1] += 1
        elif node == 'v':
            rate[(node, model)][0] += int(json_value(ans) is not None)
            rate[(node, model)][1] += 1
        elif node in ('e1', 'e2'):
            rate[(node, model)][0] += int(bool(det.parse_facts(ans)))
            rate[(node, model)][1] += 1
    beliefs = {f'{k[0]}|{k[1]}': dict(q_parse=round(v[0] / v[1], 4),
                                      n=v[1])
               for k, v in sorted(rate.items())}
    return beliefs, diverge, len(files)


def build_priors(beliefs):
    """Decision priors over the FROZEN per-node menus only: q̂ from
    trajectory parse rates; latency/tokens from the real calibration
    (clean cells); REAL switch costs. Off-menu observations in the
    trajectories (e.g. r|coder) are recorded in beliefs but never
    assignable by the policy (dag_closure.MENUS governs candidates)."""
    from deadline_reward_v1.dag_closure import MENUS
    real = json.loads((HERE / 'PRIORS_REAL_V1.json').read_text())
    node_profiles = {}
    for node, models in MENUS.items():
        for model in sorted(models):
            cell = f'{node}|{model}'
            if cell not in beliefs:
                raise ValueError(f'no belief for menu cell {cell}')
            src = real['profiles'].get(f'{node}|{model}|clean')
            if src is None:
                raise ValueError(f'no real latency profile for {cell}')
            node_profiles[cell] = dict(
                q_success=beliefs[cell]['q_parse'],  # parse proxy, declared
                lat_mean_s=src['lat_p50'], lat_p90_s=src['lat_p90'],
                tokens_p90=src['tok_p90'],
                family='normal', synthetic=False,
                q_source='formal_trajectory_parse_rate',
                q_n=beliefs[cell]['n'])
    switch = dict(
        stop_s=max(v['stop_s'] for v in real['switch_costs'].values()),
        start_s={m: v['start_s']
                 for m, v in real['switch_costs'].items()},
        measured=True)
    return dict(
        node_profiles=node_profiles,
        switch=switch,
        policy=dict(quality_composition='min', q_observed_done=1.0,
                    q_failed_unrecovered=0.0,
                    p90_aggregation='quantile_sum',
                    **PARAMS),
        priors_source=dict(
            q='production-parity parse rates over deduped real formal '
              'trajectory records (proxy, NOT task correctness)',
            lat_tokens='PRIORS_REAL_V1.json clean cells (1200-call '
                       'calibration)'))


# ---------------------------------------------------------------- engine
class RealClock:
    """Real monotonic clock; advance() is a no-op assertion (real time
    already elapsed in dispatches and model switches)."""

    def time(self):
        return time.monotonic()

    def advance(self, dt):
        if dt < 0:
            raise ValueError('clock must not go backwards')


class ModelManager:
    """Real GPU model server lifecycle (static_dag_v0.run), lazily bound."""

    def __init__(self):
        self.state = dict(proc=None, log=None, model=None)
        self.run_mod = None

    def _mod(self):
        if self.run_mod is None:
            from static_dag_v0 import run
            self.run_mod = run
        return self.run_mod

    def stop_current(self):
        if self.state['proc'] is not None:
            self._mod().stop_model(self.state['proc'], self.state['log'])
            self.state.update(proc=None, log=None, model=None)

    def start(self, model):
        proc, log, _ = self._mod().start_model(model)
        self.state.update(proc=proc, log=log, model=model)


class RealServer:
    """StubModelServer-compatible facade over real models. draw() builds
    the CASCADE prompt from the engine's upstream answers (production
    builders), dispatches through the production Budget, and returns the
    metered response. Faults are applied by the engine AFTER metering."""

    def __init__(self, priors, manager, budget, task_map, ledger_dir):
        self.priors = priors
        self.faults = {}
        self.manager = manager
        self.budget = budget
        self.task_map = task_map
        self.ledger_dir = Path(ledger_dir)
        self.engine = None     # backref set by RealEngine.__init__
        self._builders = None

    def _b(self):
        if self._builders is None:
            from static_dag_v0 import tool_aware_v1 as tav
            from static_dag_v0.multidag_dynamic import (VPROMPT,
                                                        parse_facts_safe)
            self._builders = (tav, VPROMPT, parse_facts_safe)
        return self._builders

    def set_fault(self, uid, node, model, failing):
        self.faults[(uid, node, model)] = failing

    def fault_for(self, uid, node, model):
        return self.faults.get((uid, node, model))

    def build_prompt(self, node, uid):
        tav, VPROMPT, parse_facts_safe = self._b()
        task = self.task_map[uid]
        answers = self.engine.tasks[uid].answers
        if node in ('e1', 'e2'):
            ctx = task['ctx_table'] if node == 'e1' else task['ctx_text']
            return tav.eprompt(dict(question=task['question'], context=ctx))
        f1, _ = parse_facts_safe(answers.get('e1', ''))
        f2, _ = parse_facts_safe(answers.get('e2', ''))
        facts = f1['facts'] + f2['facts']
        if node == 'r':
            return tav.sprompt(dict(question=task['question']),
                               dict(facts=facts))
        # v: embeds merged facts + the decoded r expression (expr_of mirror)
        try:
            expr = tav.decode(answers.get('r', ''))['expression']
        except Exception:
            expr = 'UNPARSEABLE'
        return VPROMPT.format(q=task['question'], facts=json.dumps(facts),
                              expr=expr)

    def draw(self, node, kind, model, uid, attempt, profile_key=None):
        prompt = self.build_prompt(node, uid)
        self.budget.check()
        idx = self.budget.reserve(f'{node}|{model}|{uid}')
        mod = self.manager._mod()
        resp, err = None, None

        def _log(attempt_no, why):
            with (self.ledger_dir / 'ERRORS.jsonl').open('a') as fh:
                fh.write(json.dumps(dict(id=idx, attempt=attempt_no,
                                         node=node, model=model, uid=uid,
                                         error=str(why))) + '\n')

        # protocol: retry once, then fail. call_model signals failures as
        # RETURNED status='infrastructure_failure'/empty-usage dicts (not
        # exceptions) — both paths retry, the Budget reservation settles
        # only on the delivered response.
        for _attempt in (1, 2):
            t0 = time.monotonic()
            try:
                got = mod.call_model(model, prompt)
            except BaseException as exc:
                err = exc
                _log(_attempt, repr(exc))
                continue
            if got.get('status') == 'delivered' and got.get('usage'):
                resp = dict(got)
                resp['latency_s'] = time.monotonic() - t0
                break
            err = RuntimeError(
                f"status={got.get('status')} "
                f"finish={got.get('finish_reason')}")
            _log(_attempt, str(err))
        if resp is None:
            raise RuntimeError(
                f'model dispatch failed twice ({node}|{model}|{uid}): '
                f'{err!r}')
        self.budget.settle(idx, resp)
        answer = resp.get('answer')
        if not isinstance(answer, str) or not answer:
            raise RuntimeError('empty/malformed answer')
        return dict(status='delivered', answer=answer,
                    usage=resp['usage'],
                    latency_s=resp['latency_s'])


class RealEngine:
    """Construction shim: StubEngine with a RealClock and a real _switch.
    Kept as a factory (not a subclass statement) because StubEngine.__init__
    must run with the real server/clock instances directly."""

    def __new__(cls, directory, server, clock, *, seed, manager):
        from deadline_reward_v1.stub_engine import StubEngine

        class _Real(StubEngine):
            def _switch(self, to_model, uid, key):
                if to_model == self.current_model:
                    return None
                t0 = self.clock.time()
                if self.current_model is None:
                    kind = 'cold_start'
                    server.manager.start(to_model)
                else:
                    kind = 'switch'
                    server.manager.stop_current()
                    server.manager.start(to_model)
                wall = self.clock.time() - t0
                self.clock.advance(wall)
                self.switch_idx += 1
                rec = dict(event='switch', idx=self.switch_idx, kind=kind,
                           **{'from': self.current_model, 'to': to_model,
                              'task': uid, 'key_ref': key, 't_start': t0,
                              't_end': self.clock.time(), 'wall_s': wall})
                self._append(rec)
                self.current_model = to_model
                self._switch_indices.append(self.switch_idx)
                if kind == 'cold_start':
                    self._cold_start_indices.append(self.switch_idx)
                st = self.tasks[uid]
                st.switch_sum += wall
                st.switch_count += 1
                self._last_switch_idx = self.switch_idx
                self._last_switch_t0 = t0
                return self.switch_idx

        eng = _Real(directory, server, clock, seed=seed)
        return eng


# ---------------------------------------------------------------- cells
def _apply_plans_batched(engine, state, tasks, planned, chosens, arm):
    """Stage-batched application of the chosen plans across tasks. Mirrors
    reassign.apply_whole_plan's job construction EXACTLY (retries incl.
    no_cache/kinds + PENDING nodes under the chosen pi); only the batching
    granularity across tasks differs (real model switches are ~60 s).
    Per-task job tuples are returned for the audit record."""
    from deadline_reward_v1 import dag_closure as dc
    audit = {}
    for group in (('e1', 'e2'), ('r',), ('v',)):
        jobs = []
        for t in tasks:
            uid = t['uid']
            chosen = chosens.get(uid)
            if chosen is None:
                continue
            st = state.tasks[uid]
            pi, kinds = chosen.pi, chosen.kinds
            replay = chosen.arm == 'FULL'
            for node in group:
                new_call = next((nc for n, nc in chosen.judgment.execute
                                 if n == node), None)
                if new_call is None:
                    continue
                if st.node_status.get(node) == dc.PENDING:
                    continue   # apply_decision rule: first executions run
                    # ONCE in their planned stage (the V stage below) with
                    # the chosen pi — never duplicated inside the plan
                    # application (double-execution bug caught by the
                    # metering smoke 2026-10-11)
                model = (pi.get(node) or st.node_model.get(node)
                         or planned[node])
                failed = st.node_status.get(node) == dc.FAILED
                jobs.append(dict(task=t, node=node,
                                 kind=kinds.get(node, 'plain'), model=model,
                                 no_cache=replay or failed))
                audit.setdefault(uid, []).append(
                    dict(node=node, model=model,
                         kind=kinds.get(node, 'plain'),
                         no_cache=bool(replay or failed), pending=False))
        if jobs:
            engine.run_jobs(f'plan:{arm}', jobs)
    return audit


def run_cell(engine, server, state, tasks, planned, arm, condition,
             fault_uids, predictor, compensator, params, cell_dir):
    """One (config, condition) cell. Returns the per-task records."""
    from deadline_reward_v1 import arm_entry, policy
    from deadline_reward_v1 import dag_closure as dc

    # per-cell physical accounting (operator boundary 3: cache-hit savings
    # must be separable from scheduling benefit in any analysis)
    before = dict(requests=engine.requests_total,
                  cached=engine.cached_calls,
                  injected=engine.injected_calls,
                  tokens=engine.tokens_total)
    for uid in fault_uids:
        server.set_fault(uid, 'r', planned['r'],
                         server_fault_answer)
    engine.start_panel(tasks, planned)
    engine.run_jobs('A', engine.planned_jobs(tasks, planned, ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs(tasks, planned, ('r',)))

    # boundary-task-3 convention: baseline remaining work for all tasks
    v_default = (params['priors']['node_profiles'][
        f"v|{planned['v']}"]['lat_mean_s']
        + params['priors']['switch']['stop_s']
        + params['priors']['switch']['start_s'][planned['v']])
    for t in tasks:
        state.remaining_work_est.setdefault(t['uid'], v_default)

    chosens, decisions = {}, {}
    for t in tasks:
        uid = t['uid']
        st = state.tasks[uid]
        if not any(st.node_status[n] == dc.FAILED for n in dc.TOPO):
            continue                      # no failure -> no decision point
        cands = arm_entry.enumerate_for(state, uid, planned)
        rec = arm_entry.decide_arm(
            state, uid, cands, arm, planned, params, predictor, compensator,
            lambda: engine.current_model)
        engine._append(dict(
            event='arm_decision', task=uid, arm=arm, condition=condition,
            mode=rec['mode'], degraded=rec['degraded'],
            pool_size=rec['pool_size'],
            chosen=None if rec['chosen'] is None else dict(
                arm=rec['chosen'].arm, pi=dict(rec['chosen'].pi)),
            violations=rec['violations']))
        decisions[uid] = dict(
            mode=rec['mode'], degraded=rec['degraded'],
            pool_size=rec['pool_size'],
            chosen=None if rec['chosen'] is None else dict(
                arm=rec['chosen'].arm, pi=dict(rec['chosen'].pi)),
            violations=rec['violations'],
            table=[dict(arm=r['arm'], pi=r['pi'], q=r['q'],
                        dcost=r['dcost'], score=r['score'],
                        feasible=r['feasible'])
                   for r in rec.get('table', [])])
        if rec['degraded']:
            st.degraded = True
            state.release_reservations(uid)
            state.remaining_work_est.pop(uid, None)
        elif rec['chosen'] is not None:
            if rec['mode'] == 'policy':
                state.reserve(uid, rec['chosen'].row['dcost'])
                state.remaining_work_est[uid] = (
                    rec['chosen'].row['mu_e2e']
                    - rec['chosen'].row['contention'])
            chosens[uid] = rec['chosen']
        # else: no_recovery (NONE arm) — no plan, the planned V stage still
        # runs below; the DAG completes with the failure accepted

    audit = {}
    if chosens:
        audit = _apply_plans_batched(engine, state, tasks, planned,
                                     chosens, arm)

    v_jobs = []
    for t in tasks:
        uid = t['uid']
        st = state.tasks[uid]
        if st.degraded:
            continue
        chosen = chosens.get(uid)
        v_model = (chosen.pi.get('v') if chosen else None) \
            or planned['v']
        v_jobs.append(dict(task=t, node='v', kind='plain', model=v_model))
    if v_jobs:
        engine.run_jobs('V1', v_jobs)
    for t in tasks:
        state.remaining_work_est.pop(t['uid'], None)
    engine.write_task_summaries(tasks)

    # ---- terminal scoring (production implementations, v2.1 ONLY) ----
    from collab_scheduler_v1.joint_search_v1.scoring_contract_final import (
        score_v21)
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        contract_v2_gold, load_native_answers)
    from static_dag_v0.multidag_dynamic import json_value
    nat = load_native_answers()

    rows = []
    for t in tasks:
        uid = t['uid']
        st = state.tasks[uid]
        n = nat.get(uid, {})
        v21g = contract_v2_gold(n.get('native_answer'),
                                n.get('native_scale'),
                                n.get('raw_derivation',
                                      t.get('derivation', '')))
        gold = v21g.get('gold', t.get('answer'))
        vv = json_value(st.answers.get('v', ''))
        q = int(score_v21(vv, gold)) if vv is not None else 0
        rows.append(dict(
            uid=uid, condition=condition, arm=arm,
            faulted=uid in fault_uids,
            node_status=dict(st.node_status),
            degraded=st.degraded,
            Q_v21=q, final_value=vv, gold=gold,
            gold_source=v21g.get('gold_source', 'v1_fallback'),
            decision=decisions.get(uid),
            retry_jobs=audit.get(uid, []),
            logical_calls=st.calls, physical_tokens=st.tokens_physical,
            service_sum_s=round(st.service_sum, 3),
            switch_sum_s=round(st.switch_sum, 3)))

    for uid in fault_uids:                # faults never leak across cells
        server.faults.pop((uid, 'r', planned['r']), None)
    cell_metering = dict(
        new_requests=engine.requests_total - before['requests'],
        cache_hits=engine.cached_calls - before['cached'],
        injected_faults=engine.injected_calls - before['injected'],
        physical_tokens=engine.tokens_total - before['tokens'],
        logical_calls=sum(r['logical_calls'] for r in rows))
    return rows, cell_metering


# global set by main() from the freeze (kept module-level for the cell fn)
server_fault_answer = '###SYNTHETIC UNPARSEABLE r-output###'


# ---------------------------------------------------------------- preflight
def preflight(beliefs, diverge, n_files):
    freeze = json.loads(FREEZE_PATH.read_text())
    priors = build_priors(beliefs)
    from deadline_reward_v1.predictor import validate_node_profiles
    validate_node_profiles(priors)

    tasks_all = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
        .read_text())['tasks']
    by_uid = {t['uid']: t for t in tasks_all}
    tasks = [by_uid[u] for u in freeze['supplementary_uids']]
    fault_uids = set(freeze['fault_assignment']['fault_task_uids'])

    beliefs_sha = sha_obj(dict(beliefs=beliefs, diverge=diverge))
    report = dict(
        preflight='supplementary_dag_quality',
        zero_model_calls=True,
        hashes=dict(
            panel_freeze=sha_file(FREEZE_PATH),
            protocol=sha_file(PROTOCOL_PATH),
            arm_entry=sha_file(HERE / 'arm_entry.py'),
            detection=sha_file(HERE / 'detection.py'),
            priors_real=sha_file(HERE / 'PRIORS_REAL_V1.json'),
            beliefs=beliefs_sha),
        freeze_ok=dict(
            supplementary_sha_match=(sha_obj(
                freeze['supplementary_uids'])
                == freeze['supplementary_sha256']),
            n_tasks=len(tasks), n_faults=len(fault_uids & set(
                freeze['supplementary_uids']))),
        beliefs=dict(
            source=f'{n_files} formal-campaign TRAJECTORY files; deduped '
                   'real delivered non-injected records',
            rates=beliefs,
            mirror_vs_production_divergences=diverge,
            parity='detection mirrors production on every evaluated '
                   'record (fence + exec_calc fixes, 2026-10-11)'),
        decision_params=PARAMS,
        scaffolding=dict(
            D_scaffold_s=D_SCAFFOLD,
            note='deadlines inert by design; real switch costs under the '
                 'frozen per-call bound make smaller D infeasible for '
                 'every plan; timeliness is OUT of scope (gate 5)'),
        caps=CAPS,
        plan=dict(
            cells=[f'{c}|{a}' for c in CONDITIONS for a in ARMS],
            logical_base_calls=5 * 2 * 20 * 4,
            execution='one engine + one identity cache for the whole run '
                      '(M3 reuse across cells is the deployment '
                      'semantics); stage-batched; metered corruption '
                      'faults'),
        gate5_scope=(json.loads((EVID / 'ADMISSION_CHECK.json')
                                .read_text())['gate5_scope']['statement']))
    ok = (not diverge
          and report['freeze_ok']['supplementary_sha_match']
          and report['freeze_ok']['n_tasks'] == 20
          and report['freeze_ok']['n_faults'] == 6)
    report['status'] = 'PREFLIGHT_PASS' if ok else 'PREFLIGHT_FAIL'
    (EVID / 'SUPPLEMENTARY_PREFLIGHT.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))

    print(json.dumps(dict(
        status=report['status'],
        hashes=report['hashes'],
        beliefs=beliefs,
        divergences=len(diverge),
        cells=report['plan']['cells'],
        caps=CAPS, D_scaffold_s=D_SCAFFOLD,
        model_calls=0), indent=1))
    (EVID / 'SUPPLEMENTARY_PREFLIGHT.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    return 0 if ok else 2


# ---------------------------------------------------------------- execute
def execute(approved_freeze_sha):
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget
    from deadline_reward_v1 import arm_entry, policy
    from deadline_reward_v1.scheduler_state import SchedulerState
    from deadline_reward_v1.predictor import (OutcomePredictor,
                                              validate_node_profiles)

    freeze_sha = sha_file(FREEZE_PATH)
    if approved_freeze_sha != freeze_sha:
        raise PermissionError('freeze hash mismatch — re-approve')
    freeze = json.loads(FREEZE_PATH.read_text())
    beliefs, diverge, _ = build_beliefs()
    if diverge:
        raise RuntimeError('mirror/production divergence — abort')
    if sha_obj(dict(beliefs=beliefs, diverge=diverge)) != json.loads(
            (EVID / 'SUPPLEMENTARY_PREFLIGHT.json').read_text()
    )['hashes']['beliefs']:
        raise PermissionError('beliefs drifted from approved preflight')

    priors = build_priors(beliefs)
    validate_node_profiles(priors)
    params = dict(priors=priors, **PARAMS)
    predictor = OutcomePredictor(priors)
    compensator = policy.DeadlineCompensator(priors)

    tasks_all = json.loads(
        (ROOT / 'static_dag_v0/frozen200/FROZEN200_POLICY.json')
        .read_text())['tasks']
    by_uid = {t['uid']: t for t in tasks_all}
    tasks = [by_uid[u] for u in freeze['supplementary_uids']]
    fault_uids = set(freeze['fault_assignment']['fault_task_uids'])
    global server_fault_answer
    server_fault_answer = freeze['fault_assignment']['fault_answer']

    run_id = time.strftime('run_%Y%m%d_%H%M%S')
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    for name, path in (('SUPPLEMENTARY_PANEL_FREEZE.json', FREEZE_PATH),
                       ('DAG_QUALITY_CALIBRATION_PROTOCOL.json',
                        PROTOCOL_PATH)):
        (run_dir / name).write_bytes(path.read_bytes())
    (run_dir / 'BELIEFS.json').write_text(json.dumps(
        dict(beliefs=beliefs, priors=priors), indent=1))

    budget = Budget(run_dir, CAPS)
    manager = ModelManager()
    server = RealServer(priors, manager, budget, by_uid, run_dir)
    clock = RealClock()
    engine = RealEngine(run_dir, server, clock, seed='supp_v1',
                        manager=manager)
    server.engine = engine

    lock = (ROOT / 'collect/logs/local_gpu.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    status, reason = 'INCOMPLETE', 'interrupted'
    cell_records = []
    prev_alarm = signal.getsignal(signal.SIGALRM)

    def _deadline(*_a):
        raise RuntimeError('wall deadline (SIGALRM)')

    try:
        signal.signal(signal.SIGALRM, _deadline)
        signal.setitimer(
            signal.ITIMER_REAL,
            max(.001, CAPS['wall_seconds']
                - (time.monotonic() - budget.start)))
        for condition in CONDITIONS:
            f_uids = fault_uids if condition == 'fault30_D3' else set()
            for arm in ARMS:
                alloc = max(0.0, CAPS['new_total_tokens'] - budget.charged)
                state = SchedulerState(
                    clock, task_deadlines={t['uid']: D_SCAFFOLD
                                           + clock.time() for t in tasks},
                    token_allocation=alloc)
                engine.add_observer(state._on_event)
                try:
                    rows, metering = run_cell(
                        engine, server, state, tasks, PLANNED, arm,
                        condition, f_uids, predictor, compensator, params,
                        run_dir)
                finally:
                    engine.observers.remove(state._on_event)
                cell = dict(condition=condition, arm=arm,
                            n=len(rows),
                            n_correct=sum(r['Q_v21'] for r in rows),
                            P_correct=round(
                                sum(r['Q_v21'] for r in rows)
                                / max(1, len(rows)), 4),
                            metering=metering,
                            rows=rows)
                cell_records.append(cell)
                with (run_dir / 'CELL_RECORDS.jsonl').open('a') as fh:
                    fh.write(json.dumps(cell, ensure_ascii=False) + '\n')
                    fh.flush()
                    os.fsync(fh.fileno())
                budget.check()
                print(f"  {condition}|{arm}: P_correct="
                      f"{cell['P_correct']} "
                      f"(requests={budget.attempts}, "
                      f"tokens={budget.actual_tokens})", flush=True)
        status, reason = 'COMPLETE', 'all 10 cells'
    except BaseException as exc:
        reason = repr(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev_alarm)
        try:
            manager.stop_current()
        finally:
            lock.close()
            with (run_dir / 'STATUS.json').open('w') as fh:
                fh.write(json.dumps(dict(
                    status=status, reason=reason,
                    requests=budget.attempts, tokens=budget.actual_tokens,
                    charged=budget.charged,
                    wall_s=round(time.monotonic() - budget.start, 1),
                    cells_done=len(cell_records)), indent=1))

    # ---- PRIORS_REAL_V1_quality.json (protocol output) ----
    cells_out = {f"{c['condition']}|{c['arm']}": dict(
        n=c['n'], n_correct=c['n_correct'], P_correct=c['P_correct'])
        for c in cell_records}
    quality = dict(
        version='PRIORS_REAL_V1_quality_v1',
        protocol_sha256=sha_file(PROTOCOL_PATH),
        panel_freeze_sha256=sha_file(FREEZE_PATH),
        run_dir=str(run_dir), status=status,
        provenance=dict(requests=budget.attempts,
                        tokens=budget.actual_tokens,
                        charged_incl_reservations=budget.charged,
                        wall_s=round(time.monotonic() - budget.start, 1)),
        cells=cells_out,
        scoring='v2.1 ONLY (score_v21 + contract_v2_gold)',
        scope='INITIAL QUALITY CALIBRATION ONLY — see '
              'ADMISSION_CHECK.json gate5_scope; no strategy selection, '
              'no superiority claim, no frozen-parameter adjustment',
        natural_failure_note='D1/D3/D5 detections include NATURAL model '
                             'failures (parse-rate beliefs: e2 0.75-0.875, '
                             'r 0.78-0.96); faulted tasks are flagged per '
                             'row (faulted=true/false)')
    (HERE / 'PRIORS_REAL_V1_quality.json').write_text(
        json.dumps(quality, indent=1, ensure_ascii=False))
    print(json.dumps(dict(status=status, reason=reason,
                          run_dir=str(run_dir), cells=cells_out),
                     indent=1))
    return 0 if status == 'COMPLETE' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approved-freeze-sha256')
    args = parser.parse_args()
    if not args.execute:
        # production parsers import urllib/ssl at module scope — import
        # them BEFORE the socket block (pure file reading, zero calls;
        # the block then proves no dispatch can happen during preflight)
        beliefs, diverge, n_files = build_beliefs()
        with no_socket():
            return preflight(beliefs, diverge, n_files)
    if os.environ.get('SUPPLEMENTARY_EXECUTE') != '1' \
            or not args.approved_freeze_sha256:
        raise PermissionError(
            'execution requires SUPPLEMENTARY_EXECUTE=1 and the '
            'operator-approved freeze SHA-256 (measurement GO)')
    return execute(args.approved_freeze_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
