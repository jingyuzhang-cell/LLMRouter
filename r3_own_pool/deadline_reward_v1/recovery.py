"""M4 — static recovery arms: NONE / LOCAL / FULL(E-arm matched). Zero calls.

Executes the STATIC recovery semantics exactly as production implements
them (no policy, no dynamic π — that is M5/M6):

- LOCAL mirrors fault30_run.eval_config LOCAL_REROUTE stage-for-stage:
  ER (e-fb on empty facts, memory rule by PANEL DETECTION ORDER: first
  detected task → coder, rest → medium; only the empty e-node re-runs),
  R2 (r-fbd on PLANNED r model where fb actually changed facts), R3 (r-esc
  to 'large' on unparseable r, ungated), V1, V2 (v-fbd on planned v model
  where r changed — FINAL-STATE rule: last vs ORIGINAL r answer), V3
  (v-esc to 'large' on v fail). Single pass per stage (production caps).
- FULL mirrors netbenefit_runner.eval_dag_arm's Z=FULL branch (the frozen
  E-arm MATCHED semantics — NOT JointEvaluator's all-swap): base pass with
  Z=NONE behavior, then recovery_plans-style per-task plans (e: memory
  rule by panel det order; r→large on unparseable; v→large on None or
  mismatch), tasks grouped BY IDENTICAL PLAN (sorted), groups in sorted
  order, each replayed as the FULL graph where trigger nodes run on the
  plan's alternative model and every other node re-executes on its
  PLANNED model. Faults are (uid,node,MODEL)-keyed, so replayed trigger
  nodes on alternative models do not re-inject (same keying as
  V3Executor / production).

Everything the runner decides is computed from ALREADY-OCCURRED observable
outputs (latest answers, facts parses); no gold, no fault registry reads,
no future information. All calls flow through the M1 engine (batching,
cache identity, fault registry, switch costs, ledger)."""
from __future__ import annotations

from typing import Dict, List

from . import detection as det

ARMS = ('NONE', 'LOCAL', 'FULL')


def _facts(engine, uid: str, node: str) -> list:
    return det.parse_facts(engine.tasks[uid].answers.get(node, ''))


def _merged(engine, uid: str) -> list:
    return det.merged_facts(_facts(engine, uid, 'e1'),
                            _facts(engine, uid, 'e2'))


def _latest(engine, uid: str, node: str) -> str:
    return engine.tasks[uid].answers.get(node, '')


def _first_answer(engine, uid: str, node: str):
    hist = engine.tasks[uid].node_history.get(node)
    return hist[0][1] if hist else None


def run_arm(engine, state, tasks: List[dict], node_models: Dict[str, str],
            arm: str) -> List[dict]:
    if arm not in ARMS:
        raise ValueError('arm must be one of ' + '/'.join(ARMS))
    engine.start_panel(tasks, node_models)
    engine.run_jobs('A', engine.planned_jobs(tasks, node_models,
                                             ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs(tasks, node_models, ('r',)))
    if arm == 'LOCAL':
        _local_er_r2_r3(engine, state, tasks, node_models)
    if 'v' in node_models:
        engine.run_jobs('V1', engine.planned_jobs(tasks, node_models,
                                                  ('v',)))
    if arm == 'LOCAL':
        _local_v2_v3(engine, state, tasks, node_models)
    elif arm == 'FULL':
        _full_e_replay(engine, state, tasks, node_models)
    summaries = engine.write_task_summaries(tasks)
    engine.write_session_summary(len(tasks))
    return summaries


# ---------------------------------------------------------------- LOCAL
def _retry(engine, state, t, node, kind, model) -> dict:
    """A LOCAL recovery job. Cache is bypassed ONLY when the node is
    FAILED — a retry of a failed node is a REAL charged attempt (operator
    rule); refreshes of healthy nodes keep the production alias semantics
    (e.g. V2 after an already-refreshed input may legally alias)."""
    failed = (state.tasks[t['uid']].node_status.get(node) == 'FAILED')
    return dict(task=t, node=node, kind=kind, model=model,
                no_cache=failed)


def _local_er_r2_r3(engine, state, tasks, node_models) -> None:
    # ER — trigger D1 (empty facts), memory rule by panel detection order.
    det_uids = [t['uid'] for t in tasks
                if not _facts(engine, t['uid'], 'e1')
                or not _facts(engine, t['uid'], 'e2')]
    target = {uid: ('coder' if i == 0 else 'medium')
              for i, uid in enumerate(det_uids)}
    old_facts = {(uid, nd): _facts(engine, uid, nd)
                 for uid in det_uids for nd in ('e1', 'e2')}
    jobs = [_retry(engine, state, t, nd, 'fb', target[t['uid']])
            for t in tasks if t['uid'] in target
            for nd in ('e1', 'e2')
            if not _facts(engine, t['uid'], nd)]
    engine.run_jobs('ER', jobs)
    # R2 — r-fbd (planned model) where fb actually CHANGED facts.
    chg = [t for t in tasks if t['uid'] in target
           and any(_facts(engine, t['uid'], nd)
                   != old_facts[(t['uid'], nd)]
                   for nd in ('e1', 'e2'))]
    engine.run_jobs('R2', [_retry(engine, state, t, 'r', 'fbd',
                                   node_models['r']) for t in chg])
    # R3 — r-esc to 'large' on unparseable r (ungated, current facts).
    rerr = [t for t in tasks
            if det.value_of(_latest(engine, t['uid'], 'r'),
                            _merged(engine, t['uid']))[1]]
    engine.run_jobs('R3', [_retry(engine, state, t, 'r', 'esc', 'large')
                           for t in rerr])


def _local_v2_v3(engine, state, tasks, node_models) -> None:
    # V2 — v-fbd (planned v model) where the FINAL r answer differs from
    # the ORIGINAL (pre-recovery) r answer (production final-state rule).
    rch = [t for t in tasks
           if (_first_answer(engine, t['uid'], 'r')
               != _latest(engine, t['uid'], 'r'))]
    engine.run_jobs('V2', [_retry(engine, state, t, 'v', 'fbd',
                                   node_models['v']) for t in rch])
    # V3 — v-esc to 'large' on latest-v fail (None or mismatch vs r value).
    vfail = []
    for t in tasks:
        uid = t['uid']
        vv = det.json_value(_latest(engine, uid, 'v'))
        rv, rre = det.value_of(_latest(engine, uid, 'r'),
                               _merged(engine, uid))
        if vv is None or (not rre and not det.close(vv, rv)):
            vfail.append(t)
    engine.run_jobs('V3', [_retry(engine, state, t, 'v', 'esc', 'large')
                           for t in vfail])


# ---------------------------------------------------------------- FULL-E
def _recovery_plans_mirror(engine, tasks):
    """Node-level plans EXACTLY as production recovery_plans()
    (netbenefit_runner.py:231-280): e-level memory rule by panel detection
    order over base-pass outputs; r→large on unparseable; v→large on
    None/mismatch."""
    e_det = [t['uid'] for t in tasks
             if not _facts(engine, t['uid'], 'e1')
             or not _facts(engine, t['uid'], 'e2')]
    target = {uid: ('coder' if i == 0 else 'medium')
              for i, uid in enumerate(e_det)}
    plans = {}
    for t in tasks:
        uid = t['uid']
        plan = {}
        if not _facts(engine, uid, 'e1'):
            plan['e1'] = target[uid]
        if not _facts(engine, uid, 'e2'):
            plan['e2'] = target[uid]
        facts = det.merged_facts(_facts(engine, uid, 'e1'),
                                 _facts(engine, uid, 'e2'))
        value, error = det.value_of(_latest(engine, uid, 'r'), facts)
        verified = det.json_value(_latest(engine, uid, 'v'))
        if error:
            plan['r'] = 'large'
        if verified is None or (not error
                                and not det.close(value, verified)):
            plan['v'] = 'large'
        if plan:
            plans[uid] = plan
    return plans


def _full_e_replay(engine, state, tasks, node_models) -> None:
    plans = _recovery_plans_mirror(engine, tasks)
    retry = [t for t in tasks if t['uid'] in plans]
    groups: Dict[tuple, List[dict]] = {}
    for t in retry:
        key = tuple(sorted(plans[t['uid']].items()))
        groups.setdefault(key, []).append(t)
    for key, group in sorted(groups.items()):
        plan = dict(key)
        replay_models = {**node_models, **plan}
        # E-arm frozen semantics: NO cache substitution in the replay —
        # every replayed logical call is charged (production MeteredExecutor
        # scopes replay identities under the 'replay' key position, so
        # aliasing is impossible; we mirror by bypassing the cache).
        engine.run_jobs('A:replay', [dict(j, no_cache=True) for j in
                                     engine.planned_jobs(group, replay_models,
                                                          ('e1', 'e2'))])
        engine.run_jobs('R1:replay', [dict(j, no_cache=True) for j in
                                      engine.planned_jobs(group, replay_models,
                                                          ('r',))])
        engine.run_jobs('V1:replay', [dict(j, no_cache=True) for j in
                                      engine.planned_jobs(group, replay_models,
                                                          ('v',))])
        for t in group:  # recovery accounting (observable bookkeeping)
            state.tasks[t['uid']].recovery_counts['replay'] += 1
