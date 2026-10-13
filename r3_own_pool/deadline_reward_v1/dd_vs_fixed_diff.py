"""DD-Online vs Fixed-Tuned decision differentiation test (zero
calls). THE key research deliverable of this round.

Six frozen states (operator ruling section 五):
  S1 budget-rich, deadline-rich (node fe, GLM-5.3, truncation seen)
  S2 budget-poor, deadline-rich  (same node; global tokens near cap)
  S3 budget-rich, deadline-tight (task clock 105/120s consumed)
  S4 fe fault with stale downstream (closure re-exec pending)
  S5 er fault (deepseek-flash), partial closure {er, xc}
  S6 xc fault (qwen-plus), local-only repair

Per state we record: Fixed's pre-committed action, DD's argmax
action, legality under remaining budget, the two-branch utilities of
DD's top candidates, and WHAT OBSERVABLE INFORMATION drives any
difference. DD receives only observable feedback (node, model,
finish_reason, clock, budget) — never the injected fault label or
same-task candidate outcomes.

Honest conclusion printed at the end (no forced divergence).

Run: python3 -m deadline_reward_v1.dd_vs_fixed_diff
"""
from __future__ import annotations

import json
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks
from deadline_reward_v1.full_dag_executor import (
    CAPS, GlobalBudget, RealRunner, TaskClock)
from deadline_reward_v1.full_dag_protocol import TUNED_THETA
from deadline_reward_v1.theta_actions import (
    DEFAULT_THETA, budget_reservation, enumerate_legal_thetas,
    prior_for, theta_legal)

HERE = Path(__file__).resolve().parent


def fixed_action(model):
    if model.startswith('GLM'):
        return ('GLM low@8192 (same model)', 'GLM-5.3',
                TUNED_THETA['GLM-5.3'])
    if model == 'deepseek-flash':
        return ('DS thinking=disabled (same model)', 'deepseek-flash',
                TUNED_THETA['deepseek-flash'])
    return ('qwen switch', 'qwen-plus', dict(DEFAULT_THETA))


def dd_full(arm_runner, clock, node, model, budget):
    """DD candidate ranking with full diagnostics."""
    from deadline_reward_v1.full_dag_protocol import MODEL_MENU
    cands = []
    for m in MODEL_MENU:
        thetas = ([a['theta'] for a in enumerate_legal_thetas(m)]
                  if m == model else
                  [dict(DEFAULT_THETA)] +
                  [a['theta'] for a in enumerate_legal_thetas(m)])
        for th in thetas:
            ok, _ = theta_legal(m, th)
            if not ok:
                continue
            res = budget_reservation(m, th, 4000)
            legal = (budget.tokens + res['tokens_in']
                     + res['tokens_out_reserved'] <= CAPS['tokens'])
            p = prior_for(m, th)
            pr, mr = p['pass_rate'], p['mean_recall']
            fb = budget_reservation('qwen-plus', dict(DEFAULT_THETA),
                                    4000)
            U_succ = _util(mr, res['tokens_in']
                           + res['tokens_out_reserved'],
                           clock.t + res['latency_s_reserved'],
                           clock.D)
            U_fail = _util(0.0,
                           res['tokens_in']
                           + res['tokens_out_reserved']
                           + fb['tokens_in'] + fb['tokens_out_reserved'],
                           clock.t + res['latency_s_reserved']
                           + fb['latency_s_reserved'], clock.D)
            eU = round(pr * U_succ + (1 - pr) * U_fail, 6)
            cands.append(dict(
                model=m, theta={k: v for k, v in th.items() if v},
                legal=legal, eU=eU, U_succ=U_succ, U_fail=U_fail,
                pr=pr, mr=mr,
                reserved_tokens=res['tokens_in']
                + res['tokens_out_reserved']))
    cands.sort(key=lambda c: -c['eU'])
    return cands


def _util(q, tokens, T, D):
    from deadline_reward_v1.full_dag_protocol import utility
    return utility(q, tokens, T, D)


def main():
    tasks = full_dag_tasks.build_tasks()
    t_fe = next(x for x in tasks if x['fault_node'] == 'fe')
    t_er = next(x for x in tasks if x['fault_node'] == 'er')
    t_xc = next(x for x in tasks if x['fault_node'] == 'xc')

    def state(name, task, node, model, clock, budget):
        runner = RealRunner('DD-Online', {}, budget,
                            Path('/tmp/dd_diff_ledger.jsonl'))
        runner.task_id = task['task_id']
        cands = dd_full(runner, clock, node, model, budget)
        fx_desc, fx_model, fx_theta = fixed_action(model)
        fx_res = budget_reservation(
            fx_model, fx_theta, 4000)
        fx_legal = (budget.tokens + fx_res['tokens_in']
                    + fx_res['tokens_out_reserved']
                    <= CAPS['tokens'])
        top = cands[0]
        same = (top['model'] == fx_model
                and {k: v for k, v in top['theta'].items() if v}
                == {k: v for k, v in fx_theta.items() if v})
        # what drives the difference
        if same:
            driver = 'identical: DD\'s argmax coincides with the ' \
                     'pre-committed rule'
        else:
            better = next((c for c in cands
                           if c['model'] == fx_model
                           and {k: v for k, v in c['theta'].items()
                                if v}
                           == {k: v for k, v in fx_theta.items()
                               if v}), None)
            d = round(top['eU'] - better['eU'], 6) if better else None
            driver = (f"DD prefers {top['model']} "
                      f"{top['theta']} (eU={top['eU']}, pr={top['pr']},"
                      f" mr={top['mr']}) over rule's {fx_desc} "
                      f"(eU={better['eU'] if better else 'n/a'}); "
                      f"eU gap={d}; driven by DEV priors"
                      f" (pass/recall) + latency reservation under "
                      f"T={round(clock.t,1)}/D={clock.D}"
                      if not same else '')
        return dict(
            state=name, node=node, faulted_model=model,
            clock=dict(t_s=clock.t, D_s=clock.D,
                       remaining_s=round(clock.remaining(), 1)),
            budget=dict(tokens_spent=budget.tokens,
                        tokens_cap=CAPS['tokens']),
            fixed=dict(action=fx_desc, legal=fx_legal),
            dd=dict(action=f"{top['model']} {top['theta']}",
                    legal=top['legal'], eU=top['eU'],
                    U_succ=top['U_succ'], U_fail=top['U_fail']),
            same_choice=same, driver=driver,
            top3=[dict(action=f"{c['model']} {c['theta']}",
                       eU=c['eU'], legal=c['legal'])
                  for c in cands[:3]])

    rich = GlobalBudget()
    poor = GlobalBudget()
    poor.tokens = CAPS['tokens'] - 12000   # only cheap candidates fit
    clock_rich = TaskClock(120.0)
    clock_rich.t = 20.0
    clock_poor_budget = TaskClock(120.0)
    clock_poor_budget.t = 20.0
    clock_tight = TaskClock(120.0)
    clock_tight.t = 105.0                  # 15s left
    clock_s4 = TaskClock(160.0)
    clock_s4.t = 40.0

    rows = [
        state('S1 rich/rich (fe, GLM)', t_fe, 'fe', 'GLM-5.3',
              clock_rich, rich),
        state('S2 budget-poor (fe, GLM)', t_fe, 'fe', 'GLM-5.3',
              clock_poor_budget, poor),
        state('S3 deadline-tight (fe, GLM)', t_fe, 'fe', 'GLM-5.3',
              clock_tight, rich),
        state('S4 fe fault + stale downstream', t_fe, 'fe', 'GLM-5.3',
              clock_s4, rich),
        state('S5 er fault (DS, partial closure)', t_er, 'er',
              'deepseek-flash', clock_rich, rich),
        state('S6 xc fault (qwen, local)', t_xc, 'xc', 'qwen-plus',
              clock_rich, rich),
    ]

    n_same = sum(1 for r in rows if r['same_choice'])
    n_diff = len(rows) - n_same
    conclusion = dict(
        n_states=len(rows), n_same=n_same,
        n_diff=n_diff,
        verdict=('DD decision rule DOES exhibit state-conditioned '
                 'differentiation' if n_diff >= 2 else
                 '当前DD决策规则尚未体现足够的状态条件化判别能力'
                 ' (DD decision rule does NOT yet exhibit sufficient '
                 'state-conditioned discrimination)'),
        known_gaps=[
            'closure re-execution cost/latency NOT yet inside eU '
            '(S4/S5 downstream re-runs are un-priced in the decision)',
            'priors rest on tiny DEV samples (FE3/FE4 n=2 per cell); '
            'Flash-vs-GLM recall gap 9/17 vs 8/17 is n=1 noise-prone',
            'no per-node-type quality prior (fe/tl/er/xc share one '
            'recall prior per model)',
            'no downstream quality-propagation model (repaired fe '
            'quality -> tl/xc terminal impact is unmodeled)',
            'sequential clock only; no critical-path/parallel model'])

    report = dict(version='DD_VS_FIXED_DIFF_v1', zero_model_calls=True,
                  states=rows, conclusion=conclusion,
                  notes='DD sees only node/model/finish/clock/budget '
                        '(observable); injected fault labels never '
                        'passed to the decision')
    (HERE / 'DD_VS_FIXED_DIFF.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    for r in rows:
        print(f"{r['state']:34s} same={r['same_choice']} "
              f"fixed={r['fixed']['action'][:28]:28s} "
              f"legal={r['fixed']['legal']} | "
              f"dd={r['dd']['action'][:34]:34s} "
              f"eU={r['dd']['eU']}")
        print(f"   driver: {r['driver'][:160]}")
    print(json.dumps(conclusion, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
