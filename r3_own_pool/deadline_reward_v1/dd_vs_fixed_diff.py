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
            pr, mr = p['pass_rate_lb'], p['pooled_recall_lb']
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
    from deadline_reward_v1 import dd_decision
    from deadline_reward_v1.full_dag_protocol import (
        MODEL_MENU, utility)
    tasks = full_dag_tasks.build_tasks()
    t_fe = next(x for x in tasks if x['fault_node'] == 'fe')
    t_er = next(x for x in tasks if x['fault_node'] == 'er')
    t_xc = next(x for x in tasks if x['fault_node'] == 'xc')

    def state(name, task, node, model, clock, budget, stale=()):
        fx_desc, fx_model, fx_theta = fixed_action(model)
        fx_res = budget_reservation(fx_model, fx_theta, 4000)
        clo_tok = 0
        clo_lat = 0.0
        from deadline_reward_v1.full_dag_protocol import TUNED_THETA
        for d in stale:
            m = task['planned_pi'][d]
            r = budget_reservation(m, TUNED_THETA[m], 4000)
            clo_tok += r['tokens_in'] + r['tokens_out_reserved']
            clo_lat += dd_decision.lat_of(d, m)
        fx_legal = (budget.tokens + fx_res['tokens_in']
                    + fx_res['tokens_out_reserved'] + clo_tok
                    <= CAPS['tokens'])
        dec = dd_decision.choose(
            planned_pi=task['planned_pi'], clock=clock,
            faulted_node=node, faulted_model=model,
            stale_closure=set(stale),
            global_budget_tokens=budget.tokens,
            caps_tokens=CAPS['tokens'], model_menu=MODEL_MENU,
            utility_fn=utility)
        top = dec['chosen']
        dd_th = {k: v for k, v in dec['theta'].items() if v}
        dd_th_str = json.dumps(dd_th, ensure_ascii=False)
        fx_th = {k: v for k, v in fx_theta.items() if v}
        same = (dec['model'] == fx_model and dd_th == fx_th)
        if same:
            driver = ("identical: DD argmax coincides with the "
                      "pre-committed rule")
        else:
            rule_c = next((c for c in dec['candidates']
                           if c['model'] == fx_model
                           and {k: v for k, v in c['theta'].items()
                                if v} == fx_th), None)
            gap = (round(top['eU'] - rule_c['eU'], 6)
                   if rule_c else None)
            driver = (f"DD prefers {dec['model']} {dd_th} "
                      f"eU={top['eU']} vs rule {fx_desc} "
                      f"eU={rule_c['eU'] if rule_c else 'n/a'} "
                      f"(gap={gap}); q_task_succ="
                      f"{top['q_task_succ']}, closure="
                      f"{round(clo_lat,1)}s/{clo_tok}tok priced in "
                      f"both branches; T={round(clock.t,1)}/"
                      f"D={clock.D}")
        return dict(
            state=name, node=node, faulted_model=model,
            stale_closure=sorted(stale),
            closure_price=dict(tokens=clo_tok,
                               lat_s=round(clo_lat, 3)),
            clock=dict(t_s=clock.t, D_s=clock.D,
                       remaining_s=round(clock.remaining(), 1)),
            budget=dict(tokens_spent=budget.tokens,
                        tokens_cap=CAPS['tokens']),
            ss=dict(action='accept fault (no recovery — static '
                           'arm)', legal=True,
                    note='terminal q takes the contract failure as '
                         'semantic 0 on this node'),
            fixed=dict(action=fx_desc, legal=fx_legal),
            dd=dict(action=f"{dec['model']} {dd_th_str}",
                    legal=True, eU=top['eU'],
                    U_succ=top['U_succ'], U_fail=top['U_fail'],
                    q_task_succ=top['q_task_succ'],
                    q_task_fail=top['q_task_fail']),
            same_choice=same, driver=driver,
            top3=[dict(
                action=f"{c['model']} "
                       f"{ {k: v for k, v in c['theta'].items() if v} }",
                eU=c['eU'])
                for c in dec['candidates'][:3]])

    rich = GlobalBudget()
    poor = GlobalBudget()
    poor.tokens = CAPS['tokens'] - 12000
    clock_rich = TaskClock(120.0)
    clock_rich.t = 20.0
    clock_tight = TaskClock(120.0)
    clock_tight.t = 105.0
    clock_s4 = TaskClock(160.0)
    clock_s4.t = 40.0
    clock_s5 = TaskClock(120.0)
    clock_s5.t = 55.0

    rows = [
        state('S1 rich/rich (fe, GLM)', t_fe, 'fe', 'GLM-5.3',
              clock_rich, rich),
        state('S2 budget-poor (fe, GLM)', t_fe, 'fe', 'GLM-5.3',
              clock_rich, poor),
        state('S3 deadline-tight (fe, GLM)', t_fe, 'fe', 'GLM-5.3',
              clock_tight, rich),
        state('S4 fe fault + stale {tl,xc}', t_fe, 'fe', 'GLM-5.3',
              clock_s4, rich, stale=('tl', 'xc')),
        state('S5 er fault (DS) + stale {xc}', t_er, 'er',
              'deepseek-flash', clock_s5, rich, stale=('xc',)),
        state('S6 xc fault (qwen, local)', t_xc, 'xc', 'qwen-plus',
              clock_rich, rich),
    ]

    n_same = sum(1 for r in rows if r['same_choice'])
    n_diff = len(rows) - n_same
    s4_like_s1 = (rows[0]['dd']['action']
                  == rows[3]['dd']['action'])
    conclusion = dict(
        n_states=len(rows), n_same=n_same, n_diff=n_diff,
        verdict=('DD decision rule exhibits state-conditioned '
                 'differentiation (v2: closure priced, node-type '
                 'latencies, task-level quality propagation)'
                 if n_diff >= 2 else
                 '当前DD决策规则尚未体现足够的状态条件化判别能力'),
        closure_state_conditioning=dict(
            S4_vs_S1_same_action=s4_like_s1,
            S1_eU=rows[0]['dd']['eU'], S4_eU=rows[3]['dd']['eU'],
            note='S1 and S4 are the same fault at different clocks; '
                 'v2 prices S4\'s closure in both branches — eU '
                 'difference reflects the priced downstream re-run'),
        remaining_gaps=[
            'recall prior shared across node types (no per-node-type '
            'silver exists); node-type signal enters via latency '
            'only',
            'priors rest on tiny DEV samples (n=2 per theta cell); '
            'Flash-vs-GLM recall gap 9/17 vs 8/17 is n=1 noise',
            'sequential clock; no parallel/critical-path execution '
            'model (not claimed)'])

    report = dict(
        version='DD_VS_FIXED_DIFF_v2', zero_model_calls=True,
        decision_method='dd_decision.choose v2 (closure pricing + '
                        'task-quality propagation + node-type '
                        'latency priors from 68 real historical '
                        'calls)',
        states=rows, conclusion=conclusion,
        notes='DD sees only node/model/finish/clock/budget/closure '
              '(observable); injected fault labels never passed to '
              'the decision')
    (HERE / 'DD_VS_FIXED_DIFF.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    for r in rows:
        print(f"{r['state']:34s} same={r['same_choice']} "
              f"fixed={r['fixed']['action'][:26]:26s} "
              f"legal={r['fixed']['legal']} | "
              f"dd={r['dd']['action'][:36]:36s} eU={r['dd']['eU']}")
        print(f"   driver: {r['driver'][:150]}")
    print(json.dumps(conclusion, indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
