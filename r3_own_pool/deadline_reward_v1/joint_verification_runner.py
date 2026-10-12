"""Joint-scheduling VERIFICATION runner (zero-call build; execution NOT
authorized). Six arms — SS / DS / SD / DD / NONE / MONO (operator
correction 2026-10-12: six, not seven).

G1 (ruling): terminal reward settlement uses score_v21 + contract_v2_gold
— realized Q/C/T/D/on-time-correct/R_task per task; predicted and
realized rewards strictly separated; gold enters ONLY here.

G2 (ruling): MONO = single-model full-context execution with a
PRE-DEFINED same-model single fallback (retry once on unparseable
value). MONO has no r node: the DAG arms' D3_r injection CANNOT be
claimed as an equivalent fault for MONO — MONO is a DESCRIPTIVE
baseline outside the same-fault causal contrasts (an optional
mono-side answer-corruption condition exists for sensitivity ONLY,
labeled non-equivalent).

G3: no D-tier freezing here — see the feasibility analysis evidence.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Dict, List

ARMS = ('SS', 'DS', 'SD', 'DD', 'NONE', 'MONO')   # SIX arms (ruling)
LAM = dict(lam_c=0.5, lam_t=1.0, lam_f=2.0, c0=4000.0)


# ------------------------------------------------------------- G1 settlement
def build_gold_map(tasks) -> Dict[str, dict]:
    """v2.1 gold per task (production contract; terminal-only use)."""
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        contract_v2_gold, load_native_answers)
    nat = load_native_answers()
    out = {}
    for t in tasks:
        n = nat.get(t['uid'], {})
        out[t['uid']] = contract_v2_gold(
            n.get('native_answer'), n.get('native_scale'),
            n.get('raw_derivation', t.get('derivation', '')))
    return out


def terminal_q(final_value, gold) -> int:
    if final_value is None:
        return 0
    from collab_scheduler_v1.joint_search_v1.scoring_contract_final import (
        score_v21)
    return int(score_v21(final_value, gold))


def realized_row(st, task, gold_map, params_lam, q, D_abs):
    """Per-task realized settlement row — G1: v2.1 terminal q, physical
    C, real E2E, frozen D, realized R_task (never the predictor's).

    Unfinished tasks are REFUSED, not guessed: a task without a
    completion_time (interrupted before its terminal summary) must
    never be settled with a fabricated low latency (operator ruling
    2026-10-12: no first-event-time fallback)."""
    from deadline_reward_v1.reward import realized_rtask
    uid = task['uid']
    if st.completion_time is None:
        raise ValueError(
            f'settlement refused: task {uid} has no completion_time '
            '(interrupted before its terminal summary)')
    T = st.completion_time - st.release_time
    D = D_abs - st.release_time
    gold = gold_map[uid].get('gold', task.get('answer'))
    c_full = st.tokens_physical
    r = realized_rtask(q=q, c_full=c_full, T=T, D=D, **params_lam)
    return dict(uid=uid, Q=q, C_tokens=c_full, T=round(T, 6),
                D=round(D, 6), on_time_correct=int(q == 1 and T <= D),
                degraded=bool(st.degraded),
                R_task=round(r, 10),
                gold=gold,
                gold_source=gold_map[uid].get('gold_source',
                                              'v1_fallback'))


def settle_cell(state, tasks, gold_map, params_lam, D_abs_by_uid,
                final_q_by_uid):
    """Settle one cell: rows + ledger append. Gold used ONLY here."""
    rows = [realized_row(state.tasks[t['uid']], t, gold_map, params_lam,
                         final_q_by_uid[t['uid']],
                         D_abs_by_uid[t['uid']]) for t in tasks]
    return rows


# ------------------------------------------------------------- G2 MONO
def mono_prompt(task) -> str:
    return (f"Question: {task['question']}\n\n"
            f"Table:\n{task['ctx_table']}\n\n"
            f"Passages:\n{task['ctx_text']}\n\n"
            f"Answer with the final numeric value only.")


def extract_mono_value(answer: str):
    """MONO terminal value extraction: strict JSON first, then a single
    numeric token fallback (documented convention; deterministic)."""
    import re
    from deadline_reward_v1 import detection as det
    v = det.json_value(answer)
    if v is not None:
        return v
    m = re.search(r'-?\d+(?:\.\d+)?', answer or '')
    return float(m.group()) if m else None


def run_mono_cell(engine, state, tasks, mono_model, gold_map, params_lam,
                  D_abs_by_uid, mono_corrupt_uids=()):
    """MONO arm cell: one full-context call per task; PRE-DEFINED
    fallback = exactly one same-model retry when no value parses.

    Engine note: MONO occupies the terminal 'v' SLOT with stage/kind
    labeled 'mono'/'plain' — the frozen four-node topology is untouched;
    stage names carry the arm semantics for the ledger.
    mono_corrupt_uids: OPTIONAL sensitivity-only answer corruption
    (non-equivalent to the DAG D3_r fault; never used in the primary
    same-fault contrasts)."""
    server = engine.server
    for uid in mono_corrupt_uids:
        server.set_fault(uid, 'v', mono_model,
                         '###MONO CORRUPTION (sensitivity-only)###')
    planned = dict(e1=mono_model, e2=mono_model, r=mono_model,
                   v=mono_model)
    engine.start_panel(tasks, planned)
    retry_jobs = []
    pre_value = {}
    for t in tasks:
        engine.run_jobs('MONO', [dict(task=t, node='v', kind='mono',
                                      model=mono_model)])
        pre_value[t['uid']] = extract_mono_value(
            state.tasks[t['uid']].answers.get('v', ''))
        if pre_value[t['uid']] is None:
            retry_jobs.append(dict(task=t, node='v', kind='mono',
                                   model=mono_model, no_cache=True))
    if retry_jobs:                        # the pre-defined fallback
        engine.run_jobs('MONO_RETRY', retry_jobs)
    engine.write_task_summaries(tasks)
    final_q = {}
    for t in tasks:
        uid = t['uid']
        val = extract_mono_value(state.tasks[uid].answers.get('v', ''))
        if val is None and any(j['task']['uid'] == uid for j in retry_jobs):
            val = pre_value[uid]           # still None -> q=0
        final_q[uid] = terminal_q(val, gold_map[uid].get(
            'gold', t.get('answer')))
    rows = settle_cell(state, tasks, gold_map, params_lam, D_abs_by_uid,
                       final_q)
    for uid in mono_corrupt_uids:          # faults never leak
        server.faults.pop((uid, 'v', mono_model), None)
    return rows


# ------------------------------------------------- DAG-arm cell (G1 wiring)
def run_dag_cell(engine, state, tasks, planned, arm, condition, fault_uids,
                 predictor, compensator, params, gold_map, params_lam,
                 D_abs_by_uid):
    """Six-arm DAG cell = supplementary run_cell + v2.1 realized
    settlement rows appended (predictions stay in the arm_decision
    ledger; realized R here — strictly separated)."""
    from deadline_reward_v1 import supplementary_runner as sr
    from deadline_reward_v1 import detection as det
    rows, metering = sr.run_cell(
        engine, engine.server, state, tasks, planned, arm, condition,
        fault_uids, predictor, compensator, params, engine.directory)
    final_q = {}
    for t in tasks:
        uid = t['uid']
        val = det.json_value(state.tasks[uid].answers.get('v', ''))
        final_q[uid] = terminal_q(val, gold_map[uid].get(
            'gold', t.get('answer')))
    settled = settle_cell(state, tasks, gold_map, params_lam,
                          D_abs_by_uid, final_q)
    for r, s in zip(rows, settled):
        r.update(R_settlement=s)
    return rows, settled, metering


# ------------------------------------------------- INCOMPLETE-safe reporting
def write_results(out_path: Path, status: str, payload: dict):
    """Complete-only official file; INCOMPLETE otherwise; never
    overwritten. A run that has EVER written its INCOMPLETE twin can
    never be marked COMPLETE afterwards (operator ruling 2026-10-12:
    a failed run must not be post-hoc labeled complete)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    inc = out_path.with_name(out_path.stem + '_INCOMPLETE.json')
    if status == 'COMPLETE':
        if out_path.exists():
            raise PermissionError(f'{out_path.name} exists — never '
                                  'overwritten')
        if inc.exists():
            raise PermissionError(
                f'{inc.name} exists — a run that recorded INCOMPLETE '
                'can never be marked COMPLETE')
        out_path.write_text(json.dumps(payload, indent=1,
                                       ensure_ascii=False))
        return out_path
    if inc.exists():
        raise PermissionError(f'{inc.name} exists — never overwritten')
    inc.write_text(json.dumps(dict(status='INCOMPLETE', **payload),
                              indent=1, ensure_ascii=False))
    return inc


# --------------------------------------- cross-arm cache fairness (ruling #2)
def run_shared_base(engine, tasks, planned, fault_uids, d3_answer):
    """SHARED BASE phase (operator ruling 2026-10-12): the planned
    e1/e2/r stages execute ONCE for all tasks with the fault draws
    active; every arm then starts from an IDENTICAL copy of this cache
    snapshot — no arm inherits another arm's recovery or v calls.
    Returns the cache snapshot dict (to be COPIED into each arm's
    engine)."""
    server = engine.server
    for uid in fault_uids:
        server.set_fault(uid, 'r', planned['r'], d3_answer)
    engine.start_panel(tasks, planned)
    engine.run_jobs('BASE_A', [dict(task=t, node='e1', kind='plain',
                                    model=planned['e1'])
                               for t in tasks]
                    + [dict(task=t, node='e2', kind='plain',
                            model=planned['e2']) for t in tasks])
    engine.run_jobs('BASE_R1', [dict(task=t, node='r', kind='plain',
                                     model=planned['r']) for t in tasks])
    return dict(engine._cache)


def arm_engine_from_snapshot(directory, server, clock, snapshot,
                             manager=None, real=False):
    """Fresh per-arm engine seeded with a COPY of the shared-base cache:
    symmetric legal initial state for every arm; cross-arm leakage
    impossible (separate engine objects, separate caches).

    real=True -> the REAL engine (model load/stop/switch through the
    ModelManager; operator ruling d1353b1: arms must use RealEngine's
    switch implementation, never a silent StubEngine substitution on
    the true path). The stub path remains for zero-call tests only.
    Inherits the manager's running model so a same-model first job
    needs no switch (stage-handoff fix)."""
    if real:
        from deadline_reward_v1.supplementary_runner import RealEngine
        eng = RealEngine(directory, server, clock, seed='jv_arm',
                         manager=manager)
        if manager is not None and manager.state['model'] is not None:
            eng.current_model = manager.state['model']
    else:
        from deadline_reward_v1.stub_engine import StubEngine
        eng = StubEngine(directory, server, clock, seed='jv_arm')
    eng._cache = dict(snapshot)
    return eng


# ------------------------------------------------- G3: frozen D-tier rule
# Anchor: per-task planned-path SERVICE mean from the INDEPENDENT
# reliability FIT binding (never the confirmatory panel's own
# executions). Switch overhead deliberately NOT in the anchor: it
# belongs to each candidate's predicted mu_e2e — anchoring on it would
# let every no-switch plan pass trivially at every tier. Multipliers
# pre-registered so that (stub-verified, T10): a one-switch LOCAL
# recovery is infeasible at tight / feasible at medium+; a three-switch
# FULL replay is feasible only at wide.
G3_MULT = dict(tight=15.0, medium=25.0, wide=50.0)   # pre-registered


# ------------------------------------------------- P3 panel (ruling #5)
P3_SEED_PANEL = 20261101
P3_SEED_FAULT = 20261102
P3_SEED_TIER = 20261103
P3_N_TASKS = 60
P3_FAULT_RATE = 0.30


def _render_table(tbl):
    return 'TABLE:\n' + '\n'.join(
        ' | '.join('' if c is None else str(c) for c in row)
        for row in tbl)


def _render_passages(paras):
    ordered = sorted(paras, key=lambda x: x.get('order', 0))
    return 'PASSAGES:\n' + '\n'.join(
        f'[{i}] {p["text"]}' for i, p in enumerate(ordered))


def build_p3_panel(n_tasks=P3_N_TASKS, write_path=None):
    """P3 confirmatory panel (zero-call): TAT-QA TRAIN split, the
    frozen200 eligibility filters, EVERY previously used uid excluded,
    native-v2.1-gold-backed only. Deterministic seeds; no outcome-based
    selection of any kind. Returns the freeze dict (and writes it)."""
    ROOT = Path('/root/r3_own_pool')
    tr = json.loads((ROOT / 'data/tatqa/tatqa_dataset_train.json')
                    .read_text())
    fz = json.loads((ROOT / 'static_dag_v0/frozen200/'
                     'FROZEN200_POLICY.json').read_text())['tasks']
    used = {t['uid'] for t in fz}
    tp = json.loads(
        (ROOT / 'collab_scheduler_v1/joint_search_v1/review/'
         'TASK_PANEL_V1.json').read_text())
    for k in ('tasks_search', 'tasks_test', 'reserve'):
        for t in tp.get(k, []):
            used.add(t if isinstance(t, str) else t.get('uid'))
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        load_native_answers)
    nat = load_native_answers()
    pool = {}
    for p in tr:
        if not p.get('table', {}).get('table') or not p.get('paragraphs'):
            continue
        ctx_table = _render_table(p['table']['table'])
        ctx_text = _render_passages(p['paragraphs'])
        for q in p['questions']:
            d = (q.get('derivation') or '').strip()
            if (q.get('answer_from') == 'table-text'
                    and q.get('answer_type') == 'arithmetic' and d
                    and re.search(r'[+\-*/]', d)
                    and q['uid'] not in used and q['uid'] in nat):
                pool[q['uid']] = dict(
                    uid=q['uid'], question=q['question'], derivation=d,
                    answer=q.get('answer'), ctx_table=ctx_table,
                    ctx_text=ctx_text)
    uids = sorted(pool)
    chosen = sorted(random.Random(P3_SEED_PANEL).sample(uids, n_tasks))
    faults = sorted(random.Random(P3_SEED_FAULT).sample(
        chosen, int(n_tasks * P3_FAULT_RATE)))
    tiers = {u: t for i, u in enumerate(chosen)
             for t in [('tight', 'medium', 'wide')[i % 3]]}
    tasks = [pool[u] for u in chosen]
    freeze = dict(
        version='JOINT_VERIFY_P3_FREEZE_v1',
        klass='pre_measurement_freeze',
        note='Confirmatory panel for the joint-scheduling verification. '
             'Drawn ONLY from never-used, eligibility-matching, '
             'native-gold-backed TAT-QA train tasks; deterministic '
             'seeds; no outcome-based selection.',
        pool_size=len(pool), n_tasks=n_tasks,
        seeds=dict(panel=P3_SEED_PANEL, fault=P3_SEED_FAULT,
                   tier=P3_SEED_TIER),
        uids=chosen, uids_sha256=hashlib.sha256(
            json.dumps(chosen, sort_keys=True).encode()).hexdigest(),
        fault_uids=faults, fault_rate=P3_FAULT_RATE,
        fault_node='r', fault_model='planned_r_model',
        fault_answer='###SYNTHETIC UNPARSEABLE r-output###',
        tiers=tiers, tier_multipliers=G3_MULT,
        tasks=tasks)
    # determinism re-derivation
    assert chosen == sorted(random.Random(P3_SEED_PANEL).sample(
        uids, n_tasks))
    assert faults == sorted(random.Random(P3_SEED_FAULT).sample(
        chosen, int(n_tasks * P3_FAULT_RATE)))
    if write_path:
        Path(write_path).write_text(json.dumps(freeze, indent=1,
                                               ensure_ascii=False))
    return freeze


def planned_path_work(task_planned, fit_binding, switch_costs=None):
    """W_i: pre-execution SERVICE work of the PLANNED path from the
    INDEPENDENT reliability FIT binding (queue-free, switch-free —
    switches are candidate-side, see G3_MULT note)."""
    return sum(fit_binding[f"{n}|{m}"]['mean']
               for n, m in task_planned.items())


def frozen_deadline(planned, tier, fit_binding, switch_costs):
    """D_i = multiplier(tier) x W_i — computable BEFORE execution from
    independent historical calibration only (ruling: never from the
    confirmatory panel's realized latencies)."""
    return G3_MULT[tier] * planned_path_work(planned, fit_binding,
                                             switch_costs)


# ================= controlled real execution entry (ruling d1353b1) =====
EXEC_ENV_FLAG = 'JOINT_VERIFY_EXECUTE'   # does NOT exist until a GO adds it

# Metering semantics (operator ruling, frozen):
#   physical_total      = every settled response in the run's ledgers
#   base_share_per_arm  = shared-base physical tokens/requests attributed
#                         EQUALLY to each arm's full-task cost C_full
#   arm_incremental     = the arm's own physical spend after the snapshot
#   T (per arm)         = release->completion of the arm's OWN episode,
#                         base replay included as cache hits (~0 service);
#   PRIMARY endpoint    = FULL-TASK realized R with C_full = base_share
#                         + incremental. The recovery-CONDITIONAL contrast
#                         (incremental-only costs) is reported SEPARATELY
#                         and never presented as independent end-to-end
#                         deployment benefit.


def execute(approved_p3_sha, run_root, make_server, manager, tasks,
            gold_map, fit_binding, switch_costs, tiers, fault_uids,
            d3_answer, planned, params, predictor, compensator,
            tier_rule=None):
    """One controlled six-arm execution. `make_server(budget, task_map)`
    returns a server (real or fake transport). NO flag check here — the
    caller (the future pilot entry, gated by EXEC_ENV_FLAG + operator
    GO) decides; tests drive it with a fake transport for the full
    six-arm closed loop. Fail-stop: any exception -> INCOMPLETE +
    preserve ledgers; never auto-restart; INCOMPLETE permanently blocks
    COMPLETE (write_results)."""
    import os
    import shutil
    from deadline_reward_v1.scheduler_state import SchedulerState
    run_root = Path(run_root)
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise PermissionError('run dir exists — no silent reuse')
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner \
        import Budget
    caps = dict(wall_seconds=1800.0, new_request_attempts=60,
                new_total_tokens=25000, request_token_reservation=6144,
                max_output_tokens=4096)          # micro-pilot worst case
    (run_root / 'budget').mkdir(parents=True, exist_ok=True)
    budget = Budget(run_root / 'budget', caps)
    task_map = {t['uid']: t for t in tasks}
    server = make_server(budget, task_map)
    lam = dict(LAM)
    statuses = {}

    def _d_abs(uid):
        st_tier = tiers[uid]
        mult = G3_MULT[st_tier]
        w = planned_path_work(planned, fit_binding, switch_costs)
        return mult * w                     # relative anchor; state
        # deadlines are set relative to each episode's release below

    # ---- shared base (once; faults active) ---------------------------
    from deadline_reward_v1.supplementary_runner import RealClock
    base_engine = arm_engine_from_snapshot(
        run_root / 'base', server, RealClock(), {}, manager=manager,
        real=True)
    server.engine = base_engine
    snapshot = run_shared_base(base_engine, tasks, planned, fault_uids,
                               d3_answer)
    base_phys_tokens = base_engine.tokens_total
    base_phys_reqs = base_engine.requests_total
    statuses['base'] = 'COMPLETE'
    n_arms = len(ARMS)

    # ---- per-arm episodes from identical snapshot copies -------------
    all_rows = {}
    for arm in ARMS:
        adir = run_root / arm
        eng = arm_engine_from_snapshot(adir, server, RealClock(),
                                       snapshot, manager=manager,
                                       real=True)
        server.engine = eng
        state = SchedulerState(
            eng.clock,
            task_deadlines={t['uid']: eng.clock.time()
                            + _d_abs(t['uid']) for t in tasks},
            token_allocation=max(0.0, caps['new_total_tokens']
                                 - budget.charged))
        state.attach(eng)
        fset = set(fault_uids) if arm != 'MONO' else set()
        if arm == 'MONO':
            d_abs = {t['uid']: eng.clock.time() + _d_abs(t['uid'])
                     for t in tasks}
            rows = run_mono_cell(
                eng, state, tasks, planned['e1'], gold_map, lam, d_abs)
            for r in rows:
                r['arm'] = 'MONO'
                r['metering'] = dict(
                    arm_incremental_tokens=state.tasks[r['uid']].tokens_physical,
                    base_share_tokens=base_phys_tokens / n_arms,
                    C_full_task=base_phys_tokens / n_arms
                    + state.tasks[r['uid']].tokens_physical,
                    C_attribution=dict(
                        base_share=base_phys_tokens / n_arms,
                        arm_incremental=state.tasks[r['uid']].tokens_physical,
                        semantics='full-task primary; incremental '
                                  'reported separately'))
        else:
            rows, settled, metering = run_dag_cell(
                eng, state, tasks, planned, arm, 'fault30_D3', fset,
                predictor, compensator, params, gold_map, lam,
                {t['uid']: eng.clock.time() + _d_abs(t['uid'])
                 for t in tasks})
            for r, s in zip(rows, settled):
                r['arm'] = arm
                # full-task cost attribution (frozen semantics above)
                s['C_full_task'] = (base_phys_tokens / n_arms
                                   + state.tasks[r['uid']].tokens_physical)
                s['C_attribution'] = dict(
                    base_share=base_phys_tokens / n_arms,
                    arm_incremental=state.tasks[r['uid']].tokens_physical,
                    semantics='full-task primary; incremental reported '
                              'separately as the recovery-CONDITIONAL '
                              'contrast')
                r['R_settlement'] = s
                r['metering'] = metering
        all_rows[arm] = rows
        statuses[arm] = 'COMPLETE'
        budget.check()

    payload = dict(
        statuses=statuses,
        physical_total=dict(requests=budget.attempts,
                            tokens=budget.actual_tokens),
        shared_base=dict(requests=base_phys_reqs,
                         tokens=base_phys_tokens,
                         per_arm_share=base_phys_tokens / n_arms),
        rows={a: all_rows[a] for a in ARMS},
        primary_endpoint='FULL-TASK realized R (C_full = base share + '
                         'arm incremental); recovery-CONDITIONAL '
                         'incremental contrast reported separately',
        tiers=tiers)
    out = run_root.parent / 'JOINT_VERIFY_RESULTS.json'
    write_results(out, 'COMPLETE', payload)
    return payload
