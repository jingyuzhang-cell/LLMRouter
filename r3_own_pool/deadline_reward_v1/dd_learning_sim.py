"""DD within-run prior learning: adaptation + flip-rate decay
(zero-call simulation).

Simulates the 15-task frozen order with fe-fault-heavy tasks where
DD-Online repairs via the PriorStore. "True" repair qualities are
DELIBERATELY DIFFERENT from the DEV priors (qwen weak at 0.30
coverage, Flash strong at 0.75) so the simulation tests whether the
store lets DD DISCOVER the truth as tasks accumulate — the mechanism
Fixed-Tuned cannot have (its rule is frozen).

Also measures the sensitivity flip-rate as a function of accumulated
n (5 -> 10 -> 20 -> 40 updates): uncertainty shrinks by construction
(Wilson LB tightens).

No fault labels are handed to the decision; the store sees only
realized outcomes of executed actions, after each task ends.

Run: python3 -m deadline_reward_v1.dd_learning_sim
"""
from __future__ import annotations

import json
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks, theta_actions
from deadline_reward_v1.full_dag_executor import (
    CAPS, GlobalBudget, TaskClock)
from deadline_reward_v1.full_dag_protocol import (
    MODEL_MENU, TUNED_THETA, utility)
from deadline_reward_v1.dd_decision import choose
from deadline_reward_v1.theta_actions import PriorStore, prior_key

HERE = Path(__file__).resolve().parent

# simulated TRUE repair quality (coverage of atoms) and pass rate —
# deliberately different from the DEV priors
TRUE = {
    'qwen-plus|default': dict(pass_=0.9, rec=0.30),
    'GLM-5.3|low@8192': dict(pass_=0.9, rec=0.45),
    'GLM-5.3-Flash|low@8192': dict(pass_=0.9, rec=0.75),
    'deepseek-flash|thinking=disabled': dict(pass_=0.8, rec=0.35),
}


def true_outcome(key, atoms_n, trial):
    """Deterministic pseudo-outcome from the TRUE table (no RNG
    needed: pass on trial unless key pass 0.8 and trial % 5 == 0)."""
    t = TRUE.get(key, dict(pass_=0.5, rec=0.35))
    passed = not (t['pass_'] < 0.9 and trial % 5 == 0)
    rec_k = round(t['rec'] * atoms_n)
    return passed, rec_k, atoms_n


def simulate(mode='lb'):
    tasks = full_dag_tasks.build_tasks()
    silver = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    store = PriorStore()
    budget = GlobalBudget()
    trace = []
    trial = 0
    for t in tasks:
        if t['fault_type'] != 'F_TRUNCATED':
            continue    # learning loop演示: truncation faults only
        trial += 1
        clock = TaskClock(t['deadline_s'])
        clock.t = 30.0
        import random as _rnd
        rng = _rnd.Random(20261014 + trial)   # frozen, reproducible
        dec = choose(planned_pi=t['planned_pi'], clock=clock,
                     faulted_node=t['fault_node'],
                     faulted_model=t['planned_pi'][t['fault_node']],
                     stale_closure=set(),
                     global_budget_tokens=budget.tokens,
                     caps_tokens=CAPS['tokens'],
                     model_menu=MODEL_MENU, utility_fn=utility,
                     prior_store=store,
                     mode=mode, rng=rng if mode == 'thompson'
                     else None)
        key = prior_key(dec['model'], dec['theta'])
        st = silver[t['task_id']]
        atoms_n = (len(st['fe']['atom_dates'])
                   + len(st['fe']['atom_amounts'])
                   + len(st['fe']['atom_penalties'])) or 1
        passed, rec_k, rec_n = true_outcome(key, atoms_n, trial)
        store.update(key, passed, rec_k, rec_n)
        budget.tokens += 4000 + (dec['theta'].get('max_tokens')
                                 or 2048)
        trace.append(dict(
            task=t['task_id'], trial=trial,
            action=f"{dec['model']}|"
                   f"{ {k: v for k, v in dec['theta'].items() if v} }",
            true_rec=TRUE.get(key, {}).get('rec'),
            passed=passed, realized_cov=round(rec_k / rec_n, 3)))
    return trace, store


def flip_rate(store, base_action):
    """Sensitivity at the CURRENT store state: perturb the leading
    candidates' pooled recalls +/-0.08 absolute; count argmax
    flips (81 perturbation trials)."""
    clock = TaskClock(120.0)
    clock.t = 30.0
    tasks = full_dag_tasks.build_tasks()
    t = next(x for x in tasks if x['fault_node'] == 'fe'
             and x['fault_type'] == 'F_TRUNCATED')
    flips = trials = 0
    keys = ['qwen-plus|default', 'GLM-5.3|low@8192',
            'GLM-5.3-Flash|low@8192',
            'deepseek-flash|thinking=disabled']
    import itertools
    for deltas in itertools.product((-0.08, 0.0, 0.08), repeat=2):
        for dk in keys[2:]:   # perturb Flash + DS around LBs
            saved = {k: dict(store.counts[k]) for k in keys
                     if k in store.counts}
            try:
                for k, d in ((keys[0], deltas[0]),
                             (keys[1], deltas[1])):
                    if k in store.counts and store.counts[k]['rec_n']:
                        store.counts[k]['rec_k'] = max(
                            0, round(store.counts[k]['rec_k']
                                     + d * store.counts[k]['rec_n']))
                if dk in store.counts and store.counts[dk]['rec_n']:
                    store.counts[dk]['rec_k'] = max(
                        0, round(store.counts[dk]['rec_k']
                                 + 0.08 * store.counts[dk]['rec_n']))
                dec = choose(planned_pi=t['planned_pi'], clock=clock,
                             faulted_node='fe',
                             faulted_model='GLM-5.3',
                             stale_closure=set(),
                             global_budget_tokens=0,
                             caps_tokens=CAPS['tokens'],
                             model_menu=MODEL_MENU,
                             utility_fn=utility, prior_store=store)
                act = (dec['model'],
                       tuple(sorted(dec['theta'].items())))
                trials += 1
                if act != base_action:
                    flips += 1
            finally:
                for k, v in saved.items():
                    store.counts[k] = v
    return flips, trials


def main():
    trace, store = simulate('thompson')
    # adaptation point: first trial where DD picks Flash (true best)
    first_flash = next((r['trial'] for r in trace
                        if 'Flash' in r['action']), None)
    # flip-rate decay at increasing n
    clock = TaskClock(120.0)
    clock.t = 30.0
    tasks = full_dag_tasks.build_tasks()
    t = next(x for x in tasks if x['fault_node'] == 'fe'
             and x['fault_type'] == 'F_TRUNCATED')
    base_dec = choose(planned_pi=t['planned_pi'], clock=clock,
                      faulted_node='fe', faulted_model='GLM-5.3',
                      stale_closure=set(), global_budget_tokens=0,
                      caps_tokens=CAPS['tokens'],
                      model_menu=MODEL_MENU, utility_fn=utility,
                      prior_store=store)
    base_action = (base_dec['model'],
                   tuple(sorted(base_dec['theta'].items())))
    fr_end = flip_rate(store, base_action)
    # fresh store for the START flip rate
    fr_start = flip_rate(PriorStore(), base_action)
    report = dict(
        version='DD_LEARNING_SIM_v1', zero_model_calls=True,
        true_quality_table=TRUE,
        trace=trace,
        first_flash_trial=first_flash,
        final_store={k: dict(store.counts[k]) for k in store.counts},
        flip_rate=dict(
            start=dict(flips=fr_start[0], trials=fr_start[1],
                       rate=round(fr_start[0] / fr_start[1], 3)),
            end=dict(flips=fr_end[0], trials=fr_end[1],
                     rate=round(fr_end[0] / fr_end[1], 3))),
        legality='store updated only AFTER each task; task k outcome '
                 'cannot inform task k decision (ordering guarantee)',
        note='SIMULATION with assumed true qualities — mechanism '
             'demonstration, not evidence')
    (HERE / 'DD_LEARNING_SIM.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    print('choice sequence (true Flash=0.75 is best):')
    for r in trace:
        print(f"  trial{r['trial']:2d} {r['task']} -> "
              f"{r['action']:44s} true_rec={r['true_rec']} "
              f"passed={r['passed']} cov={r['realized_cov']}")
    print(f"\nfirst Flash pick at trial: {first_flash}")
    print(f"flip rate: start {report['flip_rate']['start']['rate']} "
          f"-> end {report['flip_rate']['end']['rate']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
