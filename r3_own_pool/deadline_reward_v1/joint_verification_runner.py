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

import json
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
    C, real E2E, frozen D, realized R_task (never the predictor's)."""
    from deadline_reward_v1.reward import realized_rtask
    uid = task['uid']
    T = ((st.completion_time if st.completion_time is not None
          else (st.first_event_time or st.release_time))
         - st.release_time)
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
        engine.run_jobs('MONO', [dict(task=t, node='v', kind='plain',
                                      model=mono_model)])
        pre_value[t['uid']] = extract_mono_value(
            state.tasks[t['uid']].answers.get('v', ''))
        if pre_value[t['uid']] is None:
            retry_jobs.append(dict(task=t, node='v', kind='plain',
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
    overwritten (same discipline as the supplementary line)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if status == 'COMPLETE':
        if out_path.exists():
            raise PermissionError(f'{out_path.name} exists — never '
                                  'overwritten')
        out_path.write_text(json.dumps(payload, indent=1,
                                       ensure_ascii=False))
        return out_path
    inc = out_path.with_name(out_path.stem + '_INCOMPLETE.json')
    if inc.exists():
        raise PermissionError(f'{inc.name} exists — never overwritten')
    inc.write_text(json.dumps(dict(status='INCOMPLETE', **payload),
                              indent=1, ensure_ascii=False))
    return inc
