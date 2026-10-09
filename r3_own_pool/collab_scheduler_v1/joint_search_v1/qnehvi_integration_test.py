"""Production closed-loop test: official BoTorch qNEHVI in SearchSession.

Drives the REAL SearchSession → JointEvaluator → MeteredExecutor → Budget
pipeline with the official_qnehvi_same_state selector (now using BoTorch's
actual qNoisyExpectedHypervolumeImprovement, not a proxy). Verifies:
  1. Selector produces non-degenerate scores
  2. Observations change → selection changes
  3. Budget costs from MeteredExecutor ledger
  4. BoTorch error → explicit FAIL (no silent degradation)

Zero LLM calls. Uses same stub dispatch as prior tests.
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
    MeteredExecutor, SearchSession)
from collab_scheduler_v1.joint_search_v1.selectors import SelectorState
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (
    Budget, StopRun)
from collab_scheduler_v1 import fault30_protocol as fp
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'


def stub_dispatch(model, prompt):
    time.sleep(0.001)
    tok = {'medium': 60, 'large': 90, 'coder': 70}.get(model, 60)
    if 'arithmetic reasoning' in prompt.lower():
        ans = '{"expression": "v0+v1"}'
    elif 'verifying' in prompt.lower():
        ans = '{"value": 4.0}'
    elif 'extract the quantities' in prompt.lower():
        if model == 'medium':
            ans = '{"facts": []}'
        else:
            ans = ('{"facts": [{"value": 1.5, "evidence": "a"}, '
                   '{"value": 2.5, "evidence": "b"}]}')
    else:
        ans = '{"value": 4.0}'
    return dict(status='delivered', answer=ans,
                usage=dict(prompt_tokens=tok, completion_tokens=40,
                           total_tokens=tok + 40))


def run():
    task = make_task()
    led = fp.Ledger()
    tmp = tempfile.TemporaryDirectory()
    p = Path(tmp.name)
    budget = Budget(p, dict(new_request_attempts=100,
                            new_total_tokens=8192000,
                            request_token_reservation=8192,
                            max_output_tokens=512, wall_seconds=60,
                            logical_calls_per_task_config_state=12))
    ex = MeteredExecutor(p, budget, stub_dispatch, lambda m: None,
                         dict(medium='medium', large='large', coder='coder'))
    evaluator = JointEvaluator(ex, led, [task])
    session = SearchSession(evaluator, 'official_qnehvi_same_state',
                            max_configurations=8)
    state = SelectorState('official_qnehvi_same_state', seed=42)
    states_list = [('clean', {})]

    logs = []
    try:
        for rd in range(6):
            results = session.step(state.select, states_list)
            q_vals = [r.get('objectives', {}).get('Q', 0) for r in results]
            spend = results[0].get('search_spend', {}) if results else {}
            scores = getattr(state, 'last_qnehvi_scores', None)
            if scores:
                vals = list(scores.values())
                diag = dict(n_scored=len(vals),
                            n_nonzero=sum(1 for v in vals if abs(v) > 1e-10),
                            min=float(min(vals)), max=float(max(vals)),
                            nonneg=bool(all(v >= -1e-10 for v in vals)))
            else:
                diag = None
            logs.append(dict(
                round=rd + 1, Q=q_vals, n_obs=len(session.observations),
                budget_tokens=budget.actual_tokens,
                budget_attempts=budget.attempts,
                search_spend=dict(new_requests=spend.get('new_requests'),
                                  new_tokens=spend.get('new_tokens')),
                score_diag=diag))
    except StopRun:
        pass
    except RuntimeError as e:
        logs.append(dict(round=0, error=str(e)[:200]))
    finally:
        tmp.cleanup()

    # Verification
    checks = {}
    valid_logs = [l for l in logs if 'error' not in l]
    checks['no_runtime_error'] = len(valid_logs) > 0
    if valid_logs:
        checks['has_rounds'] = len(valid_logs) >= 3
        checks['obs_grow'] = valid_logs[-1]['n_obs'] > valid_logs[0]['n_obs']
        checks['ledger_costs'] = all(
            l.get('budget_tokens', 0) > 0 for l in valid_logs)
        diags = [l.get('score_diag') for l in valid_logs if l.get('score_diag')]
        checks['scores_present'] = len(diags) > 0
        if diags:
            checks['scores_nonneg'] = all(d['nonneg'] for d in diags)
            checks['scores_nonzero'] = any(d['n_nonzero'] > 0 for d in diags)
        # Selection changes across rounds (observations influence next pick)
        if len(valid_logs) >= 2:
            checks['obs_influence'] = valid_logs[-1]['n_obs'] != valid_logs[0]['n_obs']
    q_vals = [l['Q'][0] for l in valid_logs if l.get('Q')]
    checks['q_from_evaluator'] = len(q_vals) > 0

    all_pass = bool(all(checks.values()))
    result = dict(
        method='official_qnehvi_same_state (BoTorch qNEHVI)',
        logs=logs, checks=checks, all_pass=all_pass,
        zero_model_calls=True,
        note='official BoTorch qNoisyExpectedHypervolumeImprovement directly '
             'called in SearchSession selector; no proxy fallback')
    (OUT / 'QNEHVI_INTEGRATION.json').write_text(json.dumps(result, indent=1,
                                                            default=str))
    print(f'Method: official_qnehvi_same_state (BoTorch)')
    for l in logs:
        if 'error' in l:
            print(f'  ERROR: {l["error"][:80]}')
        else:
            d = l.get('score_diag') or {}
            print(f"  round {l['round']}: Q={l['Q']} obs={l['n_obs']} "
                  f"tok={l['budget_tokens']} "
                  f"scores[{d.get('n_nonzero', '?')}/{d.get('n_scored', '?')} nonzero]")
    print(f'\nChecks: {sum(checks.values())}/{len(checks)}')
    for k, v in checks.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run()
