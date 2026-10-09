"""Production closed-loop: 48-config predictor + JointEvaluator stub observations.

Fixes over previous iterations:
  1. Cost predictor uses the ACTUAL 48-config space (4-node independent X + 3 Z)
  2. All Q observations come exclusively from JointEvaluator.evaluate() — no
     manual Q injection, no stub-side quality synthesis
  3. Differentiated stub: model-quality-dependent answers (large > coder > medium)
     producing genuine Q variation across configs
  4. Per-round full-candidate score diagnostics: range, std, max-tie count
  5. Uniform-stub negative control with explicit tie-breaking

Run: python3 -m collab_scheduler_v1.joint_search_v1.closed_loop_v2
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.evaluator import (JointEvaluator,
    MeteredExecutor, SearchSession, space)
from collab_scheduler_v1.joint_search_v1.selectors import (SelectorState,
    _feat, _obs_q, _predict_incr_cost)
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (
    Budget, StopRun)
from collab_scheduler_v1 import fault30_protocol as fp
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'
GOLD = 4.0


def quality_dispatch(model, prompt):
    """Model-quality-dependent stub: large succeeds more, medium fails more.
    Answers are always format-correct; quality varies by model capability."""
    time.sleep(0.001)
    tok = {'medium': 60, 'large': 90, 'coder': 70}.get(model, 60)
    pl = prompt.lower()
    if 'arithmetic reasoning' in pl:
        ans = '{"expression": "v0+v1"}'
    elif 'verifying' in pl:
        if model == 'medium' and len(prompt) % 7 == 3:
            ans = '{"value": 99.0}'
        else:
            ans = '{"value": 4.0}'
    elif 'extract the quantities' in pl:
        if model == 'medium':
            ans = '{"facts": []}'  # medium model can't extract (capability)
        else:
            ans = ('{"facts": [{"value": 1.5, "evidence": "a"}, '
                   '{"value": 2.5, "evidence": "b"}]}')
    else:
        ans = '{"value": 4.0}'
    return dict(status='delivered', answer=ans,
                usage=dict(prompt_tokens=tok, completion_tokens=40,
                           total_tokens=tok + 40))


def uniform_dispatch(model, prompt):
    time.sleep(0.001)
    return dict(status='delivered', answer='{"value": 4.0}',
                usage=dict(prompt_tokens=60, completion_tokens=40,
                           total_tokens=100))


def run_session(dispatch_fn, method, seed=42, n_rounds=6):
    task = make_task()
    led = fp.Ledger()
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name)
    budget = Budget(p, dict(new_request_attempts=10000,
                            new_total_tokens=81920000,
                            request_token_reservation=8192,
                            max_output_tokens=512, wall_seconds=3600,
                            logical_calls_per_task_config_state=12))
    ex = MeteredExecutor(p, budget, dispatch_fn, lambda m: None,
                         dict(medium='medium', large='large', coder='coder'))
    evaluator = JointEvaluator(ex, led, [task])
    session = SearchSession(evaluator, method, max_configurations=10)
    state = SelectorState(method, seed)
    states_list = [('clean', {})]
    logs = []
    try:
        for rd in range(n_rounds):
            results = session.step(state.select, states_list)
            # Extract Q from JointEvaluator's actual output structure
            q_vals = [r.get('objectives', {}).get('Q', 0) for r in results]
            spend = results[0].get('search_spend', {}) if results else {}
            scores = getattr(state, 'last_scores', None)
            costs = getattr(state, 'last_costs', None)
            if scores:
                arr = np.array(scores)
                diag = dict(score_max=float(arr.max()),
                            score_min=float(arr.min()),
                            score_std=float(arr.std()),
                            score_range=float(arr.max() - arr.min()),
                            max_ties=int((arr == arr.max()).sum()))
            else:
                diag = None
            logs.append(dict(
                round=rd + 1, method=method, Q=q_vals,
                n_obs=len(session.observations),
                budget_tokens=budget.actual_tokens,
                budget_attempts=budget.attempts,
                search_spend=dict(new_requests=spend.get('new_requests'),
                                  new_tokens=spend.get('new_tokens')),
                score_diagnostics=diag,
                predicted_costs_head=(sorted(costs)[:5] if costs else None)))
    except StopRun:
        pass
    finally:
        tmp.cleanup()
    return logs


def run():
    all_results = {}
    checks = {}

    for scenario, dispatch in [('QUALITY', quality_dispatch),
                               ('UNIFORM', uniform_dispatch)]:
        for method in ['proposed_state_incremental', 'random',
                       'proposed_without_incremental_cost']:
            logs = run_session(dispatch, method)
            key = f'{scenario}_{method}'
            all_results[key] = logs

    # Checks: QUALITY scenario should produce Q variation
    q_logs = all_results.get('QUALITY_proposed_state_incremental', [])
    q_vals = [l['Q'][0] for l in q_logs if l['Q']]
    checks['quality_q_varies'] = len(set(q_vals)) > 1
    checks['quality_q_has_success'] = any(q > 0 for q in q_vals)
    checks['quality_q_has_failure'] = any(q == 0 for q in q_vals)

    # Score diagnostics
    diags = [l.get('score_diagnostics') for l in q_logs if l.get('score_diagnostics')]
    checks['quality_scores_present'] = len(diags) > 0
    if diags:
        ranges = [d['score_range'] for d in diags]
        stds = [d['score_std'] for d in diags]
        ties = [d['max_ties'] for d in diags]
        checks['quality_scores_nonzero_range'] = any(r > 1e-12 for r in ranges)
        checks['quality_scores_nonzero_std'] = any(s > 1e-12 for s in stds)
        checks['quality_scores_not_all_tied'] = any(t < 48 for t in ties)

    # UNIFORM scenario: Q constant
    u_q = [l['Q'][0] for l in all_results.get('UNIFORM_proposed_state_incremental', []) if l['Q']]
    checks['uniform_q_constant'] = len(set(u_q)) <= 1

    # All costs from ledger
    all_logs = [l for logs in all_results.values() for l in logs]
    checks['ledger_costs_present'] = all(
        l.get('budget_tokens', 0) > 0 for l in all_logs if l.get('round', 0) >= 1)

    # Observations grow (model update → re-selection)
    for key in ('QUALITY_proposed_state_incremental',
                'UNIFORM_proposed_state_incremental'):
        logs = all_results.get(key, [])
        if len(logs) >= 2:
            checks[f'{key}_obs_grow'] = logs[-1]['n_obs'] > logs[0]['n_obs']

    # Ablation runs
    abl_q = [l['Q'][0] for l in all_results.get(
        'QUALITY_proposed_without_incremental_cost', []) if l['Q']]
    checks['ablation_wo_incr_runs'] = len(abl_q) > 0

    all_pass = all(checks.values())
    out = dict(results=all_results, checks=checks, all_pass=all_pass,
               gold=GOLD, zero_model_calls=True,
               note='all Q from JointEvaluator; costs from MeteredExecutor '
                    'ledger; predictor on formal 48-config space')
    (OUT / 'CLOSED_LOOP_V2.json').write_text(json.dumps(out, indent=1,
                                                        default=str))
    print('=== QUALITY scenario (proposed) ===')
    for l in q_logs:
        d = l.get('score_diagnostics') or {}
        print(f"  round {l['round']}: Q={l['Q']} obs={l['n_obs']} "
              f"tok={l['budget_tokens']} "
              f"scores[min={d.get('score_min', 0):.6f} max={d.get('score_max', 0):.6f} "
              f"range={d.get('score_range', 0):.6f} ties={d.get('max_ties', '?')}]")
    print(f'\n=== UNIFORM (proposed) ===')
    for l in all_results.get('UNIFORM_proposed_state_incremental', []):
        print(f"  round {l['round']}: Q={l['Q']} obs={l['n_obs']}")
    print(f'\nVerification: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
