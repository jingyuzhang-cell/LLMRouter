"""GO-decision inputs (zero calls): deadline feasibility per tier x
arm, and DD prior sensitivity.

Part 1 — feasibility: deterministic sequential time estimates per
(task, arm) using MEASURED latencies only:
  tl/er/xc nodes: (node_type, model) median + p90 from the 68 real
  historical calls (FULL_DAG_NODE_PRIORS.json);
  fe node: measured per-(model, theta) latencies from the FE runs and
  Phase-4 cells;
  recovery: +1 repair call on the faulted node (+ closure re-exec for
  the delayed regime at real node-type latencies).
No parallelism claimed. Reports per-tier late counts for SS/Fixed/DD.

Part 2 — DD prior sensitivity: the S1 decision (fe fault, GLM) re-
evaluated over Wilson-style bounds of the tiny-n priors (qwen n=3,
GLM low@8192 n=2); counts how often DD's argmax flips away from qwen
-> measures whether DD's qwen preference is prior-noise-driven.

Run: python3 -m deadline_reward_v1.go_feasibility
"""
from __future__ import annotations

import json
from pathlib import Path

from deadline_reward_v1 import dd_decision, full_dag_tasks
from deadline_reward_v1.full_dag_protocol import (
    MODEL_MENU, TUNED_THETA, utility)
from deadline_reward_v1.theta_actions import (
    DEFAULT_THETA, budget_reservation, prior_for)

HERE = Path(__file__).resolve().parent
NP = json.loads((HERE / 'FULL_DAG_NODE_PRIORS.json').read_text())
PR4 = json.loads((HERE / 'PARAM_RECOVERY_RESULTS.json').read_text())

# fe latencies measured per (model, theta-bucket) from Phase-4 cells
FE_LAT = {
    ('fe', 'GLM-5.3', 'low@8192'): [r['latency_s'] for r in
                                    PR4['results'] if r['cell'] in
                                    (5, 6)],
    ('fe', 'GLM-5.3', 'low@2048'): [r['latency_s'] for r in
                                    PR4['results'] if r['cell'] in
                                    (3, 4)],
    ('fe', 'deepseek-flash', 'disabled@2048'): [
        r['latency_s'] for r in PR4['results'] if r['cell'] in (1, 2)],
}
# qwen fe latency from the FE recovery run (5 real calls, 7.8-31.1s)
FE_LAT[('fe', 'qwen-plus', 'default')] = [15.2, 7.8, 16.8, 31.1, 17.9]
# GLM default fe (truncating) from the original FE run
FE_LAT[('fe', 'GLM-5.3', 'default')] = [20.3, 23.6, 20.1, 20.2, 22.2]


def lat(node, model, bucket, p90=False):
    if node == 'fe':
        vals = FE_LAT.get((node, model, bucket))
        if vals:
            v = sorted(vals)
            return v[-1] if p90 else v[len(v) // 2]
    e = NP['node_priors'].get(f'{node}|{model}')
    if e:
        return e['lat_p90'] if p90 else e['lat_med']
    return budget_reservation(model, DEFAULT_THETA,
                              0)['latency_s_reserved']


def theta_bucket(model):
    if model.startswith('GLM'):
        return 'low@8192'
    if model == 'deepseek-flash':
        return 'disabled@2048'
    return 'default'


def task_time(task, arm, p90=False):
    """Deterministic sequential estimate."""
    pi = task['planned_pi']
    t = 0.0
    for n in ('fe', 'er', 'tl', 'xc'):
        t += lat(n, pi[n], theta_bucket(pi[n]), p90)
    if arm == 'SS-Tuned':
        return t   # fault accepted, no extra calls
    fn, ft = task['fault_node'], task['fault_type']
    if ft == 'F_TRUNCATED':
        # repair on the faulted node: same-model tuned (Fixed) or the
        # DD prior argmax (qwen by current priors); use qwen (the
        # slower-to-decide, conservative case for BOTH recovery arms
        # we price Fixed=GLM repair, DD=qwen switch)
        t += lat(fn, 'GLM-5.3' if pi[fn].startswith('GLM')
                 else 'deepseek-flash',
                 'low@8192' if pi[fn].startswith('GLM')
                 else 'disabled@2048', p90) if arm == 'Fixed-Tuned' \
            else lat(fn, 'qwen-plus', 'default', p90)
    else:  # F_JSON delayed: root repair + closure re-exec
        t += lat(fn, 'GLM-5.3' if pi[fn].startswith('GLM')
                 else pi[fn], theta_bucket(pi[fn]), p90)
        for d in full_dag_tasks.downstream(fn):
            t += lat(d, pi[d], theta_bucket(pi[d]), p90)
    return round(t, 1)


def feasibility():
    tasks = full_dag_tasks.build_tasks()
    rows = []
    tiers = {}
    for t in tasks:
        row = dict(task=t['task_id'], tier_s=t['deadline_s'],
                   fault=f"{t['fault_node']}/{t['fault_type']}")
        for arm in ('SS-Tuned', 'Fixed-Tuned', 'DD-Online'):
            med = task_time(t, arm)
            p90 = task_time(t, arm, p90=True)
            row[arm] = dict(t_med=med, t_p90=p90,
                            late_med=med > t['deadline_s'],
                            late_p90=p90 > t['deadline_s'])
        rows.append(row)
        for arm in ('SS-Tuned', 'Fixed-Tuned', 'DD-Online'):
            k = f"{t['deadline_s']:g}s"
            tiers.setdefault(k, {}).setdefault(arm,
                                               [0, 0, 0])
            tiers[k][arm][0] += int(row[arm]['late_med'])
            tiers[k][arm][1] += int(row[arm]['late_p90'])
            tiers[k][arm][2] += 1
    return rows, tiers


def sensitivity():
    """S1 decision under prior uncertainty: vary qwen mr and GLM
    low@8192 mr over small-n bounds; count argmax flips."""
    tasks = full_dag_tasks.build_tasks()
    t = next(x for x in tasks if x['fault_node'] == 'fe'
             and x['fault_type'] == 'F_TRUNCATED')
    from deadline_reward_v1.full_dag_executor import (
        CAPS, GlobalBudget, TaskClock)
    clock = TaskClock(t['deadline_s'])
    clock.t = 20.0
    flips = 0
    trials = 0
    outcomes = []
    base = dd_decision.choose(
        planned_pi=t['planned_pi'], clock=clock, faulted_node='fe',
        faulted_model='GLM-5.3', stale_closure=set(),
        global_budget_tokens=0, caps_tokens=CAPS['tokens'],
        model_menu=MODEL_MENU, utility_fn=utility)
    base_action = (base['model'],
                   tuple(sorted(base['theta'].items())))
    # perturb AROUND the Wilson-LB values the decision actually uses
    # (qwen LB ~0.226, GLM53 low@8192 LB ~0.316, DS LB ~0.286 pooled)
    for qwen_mr in (0.15, 0.23, 0.34):
        for glm_mr in (0.25, 0.32, 0.45):
            for ds_mr in (0.20, 0.29, 0.40):
                for pr in (0.55, 0.95):
                    import deadline_reward_v1.theta_actions as ta
                    orig = dict(ta.PRIORS)
                    ta.PRIORS = dict(orig)
                    ta.PRIORS['qwen-plus|default'] = dict(
                        pass_rate=pr, pass_rate_lb=pr,
                        pooled_recall=qwen_mr,
                        pooled_recall_lb=qwen_mr,
                        provenance='sensitivity-trial')
                    ta.PRIORS['GLM-5.3|low@8192'] = dict(
                        pass_rate=pr, pass_rate_lb=pr,
                        pooled_recall=glm_mr,
                        pooled_recall_lb=glm_mr,
                        provenance='sensitivity-trial')
                    ta.PRIORS['deepseek-flash|thinking=disabled'] =                         dict(pass_rate=pr, pass_rate_lb=pr,
                             pooled_recall=ds_mr,
                             pooled_recall_lb=ds_mr,
                             provenance='sensitivity-trial')
                    try:
                        dec = dd_decision.choose(
                            planned_pi=t['planned_pi'], clock=clock,
                            faulted_node='fe',
                            faulted_model='GLM-5.3',
                            stale_closure=set(),
                            global_budget_tokens=0,
                            caps_tokens=CAPS['tokens'],
                            model_menu=MODEL_MENU,
                            utility_fn=utility)
                        act = (dec['model'],
                               tuple(sorted(dec['theta'].items())))
                    finally:
                        ta.PRIORS = orig
                    trials += 1
                    if act != base_action:
                        flips += 1
                    outcomes.append(f'{act[0]}')
    from collections import Counter
    return dict(
        base_action=f'{base_action[0]}',
        trials=trials, flips=flips,
        flip_rate=round(flips / trials, 3),
        action_distribution=dict(Counter(outcomes)),
        grid='qwen/glm/ds pooled-recall LB± x pass {0.55,0.95} '
             '(108 trials, perturbed around Wilson LBs)',
        note='flip rate = fraction of prior-uncertainty trials in '
             'which DD abandons its baseline action')


def main():
    rows, tiers = feasibility()
    sens = sensitivity()
    report = dict(
        version='GO_FEASIBILITY_v1', zero_model_calls=True,
        latency_sources='68 historical (node-type) + FE/Phase-4 '
                        'measured (fe node); sequential, no '
                        'parallelism claimed',
        per_task=rows, tier_summary={
            k: {arm: dict(late_med=v[0], late_p90=v[1], n=v[2])
                for arm, v in arms.items()}
            for k, arms in tiers.items()},
        dd_prior_sensitivity=sens,
        reading=dict(
            tiers='late_med/late_p90 = tasks whose estimated '
                  'sequential time exceeds the deadline at median/p90 '
                  'latencies',
            sensitivity='if flip_rate is high, DD\'s current action '
                        'preference is prior-noise-driven and the '
                        'real run may not reproduce it'))
    (HERE / 'GO_FEASIBILITY.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print('tier summary (late_med / late_p90 of n):')
    for k, arms in report['tier_summary'].items():
        print(f'  D={k}: ' + '  '.join(
            f'{a}: {v["late_med"]}/{v["late_p90"]} of {v["n"]}'
            for a, v in arms.items()))
    print('\nDD prior sensitivity:',
          json.dumps({k: sens[k] for k in
                      ('base_action', 'trials', 'flips',
                       'flip_rate', 'action_distribution')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
