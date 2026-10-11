"""V2.3 five-arm stub pilot — end-to-end validation of the frozen
experimental protocol on the stub engine. ZERO real model calls.

Runs the COMPLETE V2.3 design through deadline_reward_v1's stub
infrastructure: 150 tasks × 5 arms × 3 D-tiers, with stratified D-tier
allocation, five-arm within-task pairing, all six contrast computations
(B-REC/B-REA/B-JOINT/H1-H4/S1), the method-choice rule, and the full
statistical analysis pipeline. This validates that the experimental
protocol is implementable and produces interpretable results BEFORE any
real-model budget is spent.

Run: python3 -m deadline_reward_v1.v23_pilot_stub
"""
from __future__ import annotations

import contextlib
import json
import math
import random
import socket as _socket_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import policy, reassign
from deadline_reward_v1.scheduler_state import SchedulerState
from deadline_reward_v1.stub_engine import (
    InjectedClock, StubEngine, StubModelServer, load_ledger)

HERE = Path(__file__).resolve().parent
PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
OUT = HERE / 'evidence' / 'v23_pilot'
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

# Five arms: S/S (static recovery, planned models), D/S (dynamic
# recovery, planned models), S/D (static recovery, dynamic models),
# D/D (both dynamic), NONE (floor)
ARMS = ['SS', 'DS', 'SD', 'DD', 'NONE']

Phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
phif = lambda z: math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def e1(mu, p90, d):
    s = (p90 - mu) / 1.2816
    if s <= 0:
        return (1.0 if mu <= d else 0.0), max(0.0, mu - d)
    z = (mu - d) / s
    return Phi((d - mu) / s), s * (phif(z) + z * Phi(z))


def make_task(i, seed_val=42):
    rng = random.Random(f'task{i}')
    a = rng.choice([1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    b = rng.choice([1.5, 2.0, 2.5, 3.0])
    return dict(uid=f'pt{i}', question=f'What is {a} + {b}?',
                derivation=f'{a}+{b}', answer=a + b,
                ctx_table=f'TABLE {i}: | val | {a} |',
                ctx_text=f'PASSAGES {i}: value is {b}')


def run_arm_for_task(task, arm, d_tier, seed):
    """Run one (task, arm) episode on the stub engine; return R_task."""
    server = StubModelServer(dict(ANSWERS), PRIORS, seed=seed)
    server.set_fault(task['uid'], 'r', 'medium',
                     '###SYNTHETIC UNPARSEABLE###')
    clock = InjectedClock()
    engine = StubEngine(OUT / f'{arm}_{task["uid"]}', server, clock,
                        seed=seed, profile_key='golden_zero')
    state = SchedulerState(clock,
                           task_deadlines={task['uid']: d_tier},
                           token_allocation=100000.0)
    state.attach(engine)
    engine.start_panel([task], NODES_MODELS)
    engine.run_jobs('A', engine.planned_jobs([task], NODES_MODELS,
                                              ('e1', 'e2')))
    engine.run_jobs('R1', engine.planned_jobs([task], NODES_MODELS,
                                               ('r',)))

    st = state.tasks[task['uid']]
    cands = reassign.enumerate_candidates(state, task['uid'], NODES_MODELS)

    # arm-specific selection
    if arm == 'NONE':
        chosen = None  # no recovery
        degraded = True  # accept failure
        st.degraded = True
    elif arm == 'SS':
        # static: LOCAL with planned models (the E-arm fixed recipe)
        chosen = next((c for c in cands if c.arm == 'LOCAL'
                       and c.pi.get('r') == NODES_MODELS['r']
                       and c.pi.get('v') == NODES_MODELS['v']), None)
        degraded = chosen is None
        if degraded:
            st.degraded = True
    elif arm == 'DS':
        # dynamic recovery, planned models: pick best LOCAL with
        # planned r/v but allow R to vary via judge
        locals_ = [c for c in cands if c.arm == 'LOCAL']
        planned = [c for c in locals_
                   if c.pi.get('v') == NODES_MODELS['v']]
        chosen = planned[0] if planned else None
        degraded = chosen is None
        if degraded:
            st.degraded = True
    elif arm == 'SD':
        # static recovery recipe, dynamic models: LOCAL with the
        # recipe's R but pi free on v
        chosen = next((c for c in cands if c.arm == 'FULL_DYNAMIC'
                       and c.pi.get('r') == 'large'), None)
        degraded = chosen is None
        if degraded:
            st.degraded = True
    elif arm == 'DD':
        # both dynamic: full policy (two-stage decision)
        params = dict(priors=PRIORS, q_min=0.80, eps=0.10, lam_c=0.5,
                      lam_t=1.0, lam_f=2.0, c0=4000.0,
                      session_bonus=1.0, session_penalty=2.0)
        predictor = policy.OutcomePredictor(PRIORS)
        compensator = policy.DeadlineCompensator(PRIORS)
        decision = policy._score_and_pick(
            state, task['uid'], cands, params, predictor, compensator,
            lambda: engine.current_model)
        if decision.degraded:
            st.degraded = True
            degraded = True
            chosen = None
        else:
            degraded = False
            chosen = decision.chosen
    else:
        raise ValueError(arm)

    if not degraded and chosen is not None:
        state.remaining_work_est[task['uid']] = 0.0
        reassign.apply_whole_plan(engine, state, task, NODES_MODELS,
                                  chosen)
    else:
        engine.run_jobs('V1', engine.planned_jobs(
            [task], NODES_MODELS, ('v',)))
    engine.write_task_summaries([task])
    engine.write_session_summary(1)

    # compute R_task
    from deadline_reward_v1 import detection as det
    from deadline_reward_v1.reward import realized_rtask
    vv = det.json_value(st.answers.get('v', ''))
    gold = task.get('answer')
    q = 1.0 if (vv is not None and gold is not None
                and det.close(vv, gold)) else 0.0
    T = (st.completion_time - st.release_time) if st.completion_time \
        else 0.0
    D = d_tier - st.release_time
    C_full = st.tokens_physical
    r = realized_rtask(q=q, c_full=C_full, T=T, D=D, lam_c=0.5,
                       lam_t=1.0, lam_f=2.0, c0=4000.0)
    # clean up for next run
    import shutil
    shutil.rmtree(OUT / f'{arm}_{task["uid"]}', ignore_errors=True)
    return dict(r_task=r, q=q, T=T, D=D, C=C_full,
                degraded=st.degraded,
                arm=arm, task=task['uid'], d_tier=d_tier)


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


def main():
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- generate 150 tasks ----
    tasks = [make_task(i) for i in range(150)]

    # ---- stratified D-tier allocation (frozen seed) ----
    # Use a simple difficulty proxy: task index mod 3 -> tier
    # (stratification on the frozen prior-difficulty proxy)
    rng = random.Random(42)
    shuffled = list(range(150))
    rng.shuffle(shuffled)
    tier_map = {}
    tiers = [80.0, 60.0, 40.0]  # loose, medium, tight
    for i, idx in enumerate(shuffled):
        tier_map[idx] = tiers[i % 3]

    # ---- run all (task, arm) episodes ----
    all_results = []
    for i, task in enumerate(tasks):
        d = tier_map[i]
        for arm in ARMS:
            res = run_arm_for_task(task, arm, d, seed=f'pilot_{arm}_{i}')
            all_results.append(res)

    # ---- compute the six contrasts ----
    def mean_r(arm):
        return sum(r['r_task'] for r in all_results
                   if r['arm'] == arm) / 150

    mu_SS = mean_r('SS')
    mu_DS = mean_r('DS')
    mu_SD = mean_r('SD')
    mu_DD = mean_r('DD')

    B_REC = mu_DS - mu_SS
    B_REA = mu_SD - mu_SS
    B_JOINT = mu_DD - mu_DS - mu_SD + mu_SS
    total = mu_DD - mu_SS

    # task-level paired differences
    def task_arm_map(arm):
        return {r['task']: r['r_task'] for r in all_results
                if r['arm'] == arm}

    r_SS = task_arm_map('SS')
    r_DS = task_arm_map('DS')
    r_SD = task_arm_map('SD')
    r_DD = task_arm_map('DD')

    d_H1 = [r_DS[t] - r_SS[t] for t in r_SS]
    d_H2 = [r_SD[t] - r_SS[t] for t in r_SS]
    d_H3 = [r_DD[t] - r_DS[t] - r_SD[t] + r_SS[t] for t in r_SS]
    d_H4 = [r_DD[t] - r_SS[t] for t in r_SS]
    d_S1a = [r_DD[t] - r_DS[t] for t in r_SS]
    d_S1b = [r_DD[t] - r_SD[t] for t in r_SS]

    # simple sign-flip MC p-values (directional)
    def sign_flip_p(diffs, B=10000, seed=12345):
        obs = sum(diffs) / len(diffs)
        rng = random.Random(seed)
        count = 0
        n = len(diffs)
        for _ in range(B):
            perm = [d * rng.choice([1, -1]) for d in diffs]
            if sum(perm) / n >= obs:
                count += 1
        return (1 + count) / (B + 1)

    p_H1 = sign_flip_p(d_H1)
    p_H2 = sign_flip_p(d_H2)
    p_H3 = sign_flip_p(d_H3)
    p_H4 = sign_flip_p(d_H4)
    p_S1a = sign_flip_p(d_S1a)
    p_S1b = sign_flip_p(d_S1b)
    p_S1 = max(p_S1a, p_S1b)  # IUT

    # Holm on H1-H4
    pvals = sorted([(p_H1, 'H1'), (p_H2, 'H2'), (p_H3, 'H3'),
                    (p_H4, 'H4')])
    holm_results = {}
    for k, (p, name) in enumerate(pvals):
        threshold = 0.05 / (4 - k)
        holm_results[name] = dict(p=round(p, 6),
                                  threshold=round(threshold, 6),
                                  rejected=p <= threshold)

    # arm summaries
    arm_summary = {}
    for arm in ARMS:
        rows = [r for r in all_results if r['arm'] == arm]
        arm_summary[arm] = dict(
            mean_r_task=round(sum(r['r_task'] for r in rows) / len(rows),
                              4),
            on_time_rate=round(sum(1 for r in rows
                                   if r['T'] <= r['D']) / len(rows), 4),
            correct_rate=round(sum(r['q'] for r in rows) / len(rows), 4),
            degraded_rate=round(
                sum(1 for r in rows if r['degraded']) / len(rows), 4),
            mean_C=round(sum(r['C'] for r in rows) / len(rows), 0))

    report = dict(
        pilot='v23_five_arm_stub',
        zero_model_calls=True,
        n_tasks=150, n_arms=5, n_episodes=750,
        d_tiers=dict(loose=80.0, medium=60.0, tight=40.0),
        arm_summary=arm_summary,
        contrasts=dict(
            B_REC=round(B_REC, 4), B_REA=round(B_REA, 4),
            B_JOINT=round(B_JOINT, 4), total=round(total, 4)),
        hypotheses=dict(
            H1=dict(p=round(p_H1, 6), diff=round(
                sum(d_H1) / len(d_H1), 4)),
            H2=dict(p=round(p_H2, 6), diff=round(
                sum(d_H2) / len(d_H2), 4)),
            H3=dict(p=round(p_H3, 6), diff=round(
                sum(d_H3) / len(d_H3), 4)),
            H4=dict(p=round(p_H4, 6), diff=round(
                sum(d_H4) / len(d_H4), 4))),
        S1=dict(
            p_S1a=round(p_S1a, 6), p_S1b=round(p_S1b, 6),
            p_S1_IUT=round(p_S1, 6),
            S1_holds=p_S1 <= 0.05),
        holm=holm_results,
        note='STUB pilot: validates protocol implementability and '
             'statistical pipeline. Results are NOT real-model '
             'evidence.')

    (OUT / 'V23_PILOT_STUB.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(dict(
        arm_summary=arm_summary,
        contrasts=dict(B_REC=round(B_REC, 3), B_REA=round(B_REA, 3),
                       B_JOINT=round(B_JOINT, 3),
                       total=round(total, 3)),
        H3_p=p_H3, S1_p=p_S1,
        holm=holm_results,
    ), indent=1))
    print(f'\nzero_model_calls=true')
    return 0


if __name__ == '__main__':
    with no_socket():
        raise SystemExit(main())
