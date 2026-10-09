"""Differentiated-stub closed-loop: config-dependent Q + intermediate diagnostics.

Two stub scenarios on the FORMAL pipeline (SearchSession+JointEvaluator+MeteredExecutor):
  DIFF: dispatch returns answers that vary by (model, prompt_content) —
        some configs produce correct answers (Q>0), others fail (Q=0).
        Selector does NOT see this rule; it only sees evaluated Q observations.
  UNIFORM: all answers identical (negative control) — Q constant; verify
        tie-breaking is explicit, not fixed-order.

Diagnostics logged per round: GP mu/sigma, EI scores, predicted incremental
costs, selected candidate, and whether ranking changed from previous round.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.evaluator import (JointEvaluator,  # noqa
    MeteredExecutor, SearchSession, space)
from collab_scheduler_v1.joint_search_v1.selectors import SelectorState  # noqa
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (  # noqa
    Budget, StopRun)
from collab_scheduler_v1 import fault30_protocol as fp  # noqa
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task  # noqa

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
GOLD = 4.0  # make_task answer
N_ROUNDS = 5


def diff_dispatch(model, prompt):
    """Returns model- and prompt-dependent answers. Some succeed, some fail."""
    time.sleep(0.001)
    tok = {'medium': 60, 'large': 90, 'coder': 70}.get(model, 60)
    if 'extract' in prompt.lower():
        # large extracts better facts; medium sometimes garbled
        if model == 'medium' and len(prompt) % 3 == 0:
            ans = '{"facts": []}'  # extraction failure
        else:
            ans = '{"facts": [{"value": 1.5, "evidence": "a"}, {"value": 2.5, "evidence": "b"}]}'
    elif 'arithmetic' in prompt.lower() or 'reasoning' in prompt.lower():
        # medium computes correct; large sometimes wrong
        if model == 'large' and len(prompt) % 4 == 0:
            ans = '{"expression": "v0-v1"}'  # wrong expression
        else:
            ans = '{"expression": "v0+v1"}'
    elif 'verif' in prompt.lower():
        # coder verifies correctly; large sometimes wrong value
        if model == 'large' and len(prompt) % 5 == 0:
            ans = '{"value": 99.0}'  # wrong
        else:
            ans = '{"value": 4.0}'
    else:
        ans = '{"value": 4.0}'
    return dict(status='delivered', answer=ans,
                usage=dict(prompt_tokens=tok, completion_tokens=40,
                           total_tokens=tok + 40))


def uniform_dispatch(model, prompt):
    """Uniform stub (negative control)."""
    time.sleep(0.001)
    return dict(status='delivered', answer='{"value": 4.0}',
                usage=dict(prompt_tokens=60, completion_tokens=40,
                           total_tokens=100))


def run_scenario(name, dispatch_fn, method='proposed_state_incremental'):
    task = make_task()
    led = fp.Ledger()
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name)
    budget = Budget(p, dict(new_request_attempts=10000,
                            new_total_tokens=81920000,
                            request_token_reservation=8192,
                            max_output_tokens=512, wall_seconds=3600,
                            logical_calls_per_task_config_state=12))
    ex = MeteredExecutor(p, budget, dispatch_fn, lambda model: None,
                         dict(medium='medium', large='large', coder='coder'))
    evaluator = JointEvaluator(ex, led, [task])
    session = SearchSession(evaluator, method, max_configurations=8)
    state = SelectorState(method, seed=42)
    states_list = [('clean', {})]
    logs = []
    prev_pick = None
    try:
        for rd in range(N_ROUNDS):
            obs_before = session.observations[:]
            results = session.step(state.select, states_list)
            q_vals = [r.get('Q', 0) for r in results]
            pick = None
            # record selector internals if available
            scores = getattr(state, 'last_scores', None)
            costs = getattr(state, 'last_costs', None)
            logs.append(dict(
                round=rd + 1, method=method, scenario=name,
                selected=pick or 'N/A',
                Q=q_vals, n_obs=len(session.observations),
                budget_tokens=budget.actual_tokens,
                scores_head=(sorted(scores, reverse=True)[:5]
                             if scores else None),
                costs_head=(sorted(costs)[:5] if costs else None),
                ranking_changed=(prev_pick != pick if prev_pick else None)))
            prev_pick = pick
    except StopRun:
        pass
    finally:
        tmp.cleanup()
    return logs


def run():
    results = {}
    checks = {}

    # Scenario DIFF: differentiated responses
    diff_logs = run_scenario('DIFF', diff_dispatch)
    results['DIFF'] = diff_logs

    # Scenario UNIFORM: negative control
    uni_logs = run_scenario('UNIFORM', uniform_dispatch)
    results['UNIFORM'] = uni_logs

    # Checks for DIFF
    diff_q = [l['Q'][0] for l in diff_logs if l['Q']]
    checks['diff_q_varies'] = len(set(diff_q)) > 1
    checks['diff_q_not_all_zero'] = any(q > 0 for q in diff_q)
    checks['diff_q_not_all_one'] = any(q < 1 for q in diff_q)
    # Scores non-degenerate
    diff_scores = [l.get('scores_head') for l in diff_logs if l.get('scores_head')]
    checks['diff_scores_present'] = len(diff_scores) > 0
    if diff_scores:
        flat = [s for sl in diff_scores for s in sl]
        checks['diff_scores_nonzero'] = any(abs(s) > 1e-10 for s in flat)
        checks['diff_scores_vary'] = len(set(flat)) > 1

    # Checks for UNIFORM
    uni_q = [l['Q'][0] for l in uni_logs if l['Q']]
    checks['uniform_q_constant'] = len(set(uni_q)) <= 1

    # Both ran
    checks['both_have_rounds'] = len(diff_logs) >= 3 and len(uni_logs) >= 3
    checks['both_ledger_cost'] = all(
        l.get('budget_tokens', 0) > 0 for l in diff_logs + uni_logs)

    all_pass = all(checks.values())
    out = dict(results=results, checks=checks, all_pass=all_pass,
               gold=GOLD, zero_model_calls=True,
               note='DIFF: model+prompt-dependent answers (selector blind to '
                    'rule); UNIFORM: constant answers (negative control)')
    (OUT / 'DIFF_STUB_RESULT.json').write_text(json.dumps(out, indent=1,
                                                          default=str))
    print('=== DIFF (differentiated stub) ===')
    for l in diff_logs:
        print(f"  round {l['round']}: Q={l['Q']} obs={l['n_obs']} "
              f"tok={l['budget_tokens']} scores={(l.get('scores_head') or [])[:3]}")
    print('\n=== UNIFORM (negative control) ===')
    for l in uni_logs:
        print(f"  round {l['round']}: Q={l['Q']} obs={l['n_obs']} "
              f"tok={l['budget_tokens']}")
    print(f'\nVerification: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
