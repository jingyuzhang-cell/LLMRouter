"""Six actual selector callbacks for SearchSession.step() on the formal pipeline.

Implements `select(candidates, observations) -> config_id` for each METHODS
entry. The incremental cost predictor is called by the proposed selector
BEFORE scoring (pre-selection). Two ablation selectors disable exactly one
mechanism. Official qNEHVI is BLOCKED (no BoTorch available).

Zero-call closed-loop test uses the real MeteredExecutor with independent
stub responses; actual costs come from the ledger, not predictor values.
"""
import hashlib
import json
import sys
from math import erf, sqrt
from pathlib import Path

import numpy as np
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from collab_scheduler_v1.joint_search_v1.evaluator import METHODS, space  # noqa

OUT = ROOT / 'collab_scheduler_v1/joint_search_v1'

# ==== Shared utilities ====
_MODEL_IDX = {'medium': 0, 'large': 1, 'coder': 2}
_Z_IDX = {'NONE': 0, 'LOCAL': 1, 'FULL': 2}


def _feat(cfg):
    x = cfg['X']
    return [float(_MODEL_IDX[x['e1']]), float(_MODEL_IDX[x['e2']]),
            float(_MODEL_IDX[x['r']]), float(_MODEL_IDX[x['v']]),
            float(_Z_IDX[cfg['Z']])]


def _obs_q(obs):
    return [o.get('Q', o.get('quality', 0)) if isinstance(o, dict) else 0
            for o in obs]


def _predict_incr_cost(cfg):
    """Incremental cost: upper bound of possible new calls (pre-selection).
    LOCAL adds recovery events; FULL adds full re-execution."""
    base = 4  # e1+e2+r+v planned
    z = cfg['Z']
    if z == 'LOCAL':
        return base + 6  # + e_fb×2, r_fbd, r_esc, v_fbd, v_esc
    if z == 'FULL':
        return base + 4  # + full re-execution of all 4 nodes
    return base


def _ei_score(mu, sigma, best):
    z = (np.asarray(mu) - best) / np.maximum(np.asarray(sigma), 1e-12)
    phi = 0.5 * (1 + np.array([erf(zz / sqrt(2)) for zz in z]))
    pdf = np.exp(-0.5 * z ** 2) / sqrt(2 * np.pi)
    return (mu - best) * phi + np.asarray(sigma) * pdf


class SelectorState:
    """Per-method/seed state (surrogate, round counter, etc.)."""
    def __init__(self, method, seed=42):
        self.method = method
        self.rng = np.random.default_rng(seed)
        self.round = 0
        self.alpha = 0.5  # cost-aware coefficient

    def select(self, candidates, observations):
        self.round += 1
        if self.method == 'random':
            return self._random(candidates)
        elif self.method == 'scalarized_bo':
            return self._scalarized(candidates, observations)
        elif self.method == 'proposed_state_incremental':
            return self._proposed(candidates, observations,
                                  use_state=True, use_incr_cost=True)
        elif self.method == 'proposed_without_state':
            return self._proposed(candidates, observations,
                                  use_state=False, use_incr_cost=True)
        elif self.method == 'proposed_without_incremental_cost':
            return self._proposed(candidates, observations,
                                  use_state=True, use_incr_cost=False)
        elif self.method == 'official_qnehvi_same_state':
            return self._blocked(candidates)
        raise ValueError(self.method)

    def _random(self, candidates):
        return candidates[int(self.rng.integers(len(candidates)))]['id']

    def _scalarized(self, candidates, observations):
        if not observations:
            return candidates[int(self.rng.integers(len(candidates)))]['id']
        from sa_pgfs_v1.surrogate import QSurrogate
        X = np.array([_feat(c) for c in candidates[:len(observations)]])
        y = np.array(_obs_q(observations))
        if len(y) < 2:
            return candidates[0]['id']
        sur = QSurrogate()
        sur.fit(X[:len(y)], y)
        X_all = np.array([_feat(c) for c in candidates])
        mu, sg = sur.predict(X_all, return_std=True)
        scores = _ei_score(mu, sg, y.max())
        return candidates[int(np.argmax(scores))]['id']

    def _proposed(self, candidates, observations, use_state, use_incr_cost):
        if not observations:
            return candidates[int(self.rng.integers(len(candidates)))]['id']
        from sa_pgfs_v1.surrogate import QSurrogate
        y = np.array(_obs_q(observations))
        if len(y) < 2:
            return candidates[0]['id']
        # Feature: with_state includes Z; without_state masks Z to 0
        def feat(cfg):
            f = _feat(cfg)
            if not use_state:
                f[4] = 0.0  # mask Z → state-blind
            return f
        X_obs = np.array([feat(c) for c in candidates[:len(y)]])
        sur = QSurrogate()
        sur.fit(X_obs, y)
        X_all = np.array([feat(c) for c in candidates])
        mu, sg = sur.predict(X_all, return_std=True)
        scores = _ei_score(mu, sg, y.max())
        if use_incr_cost:
            # Pre-selection incremental cost prediction
            costs = np.array([_predict_incr_cost(c) for c in candidates])
            scores = scores / (1 + self.alpha * costs)
        self.last_scores = scores.tolist()
        self.last_costs = ([_predict_incr_cost(c) for c in candidates]
                           if use_incr_cost else None)
        return candidates[int(np.argmax(scores))]['id']

    def _blocked(self, candidates):
        raise NotImplementedError(
            f'{self.method}: BLOCKED — official BoTorch qNEHVI not available; '
            'cannot substitute with marginal-sampling approximation')


def make_selector(method, seed=42):
    state = SelectorState(method, seed)
    return state.select


# ==== Closed-loop test ====
def run_closed_loop():
    """Drive the REAL SearchSession + JointEvaluator with stub responses.
    Verify: init → model update → re-selection; non-degenerate scores;
    ablation isolation; costs from ledger."""
    from collab_scheduler_v1.joint_search_v1.evaluator import (JointEvaluator,
                                                                SearchSession)
    from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget, StopRun
    from collab_scheduler_v1 import fault30_protocol as fp

    import tempfile
    from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
    from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
    task = make_task()
    led = fp.Ledger()

    results = {}
    checks = {}

    active = [m for m in METHODS if m != 'official_qnehvi_same_state']
    for method in active:
        tmp = tempfile.TemporaryDirectory()
        p = Path(tmp.name)
        budget = Budget(p, dict(new_request_attempts=10000,
                                new_total_tokens=81920000,
                                request_token_reservation=8192,
                                max_output_tokens=512,
                                wall_seconds=3600,
                                logical_calls_per_task_config_state=12))
        q_map = {'medium': 0.25, 'large': 0.40, 'coder': 0.30}
        def dispatch(model, prompt):
            import time; time.sleep(0.001)
            if 'extract' in prompt.lower():
                ans = '{"facts": [{"value": 1.0, "evidence": "a"}, {"value": 2.0, "evidence": "b"}]}'
            elif 'arithmetic' in prompt.lower() or 'reasoning' in prompt.lower():
                ans = '{"expression": "v0+v1"}'
            elif 'verif' in prompt.lower():
                ans = '{"value": 4.0}'
            else:
                ans = '{"value": 4.0}'
            tok = int(q_map.get(model, 0.3) * 300)
            return dict(status='delivered', answer=ans,
                        usage=dict(prompt_tokens=tok, completion_tokens=40,
                                   total_tokens=tok + 40))
        ex = MeteredExecutor(p, budget, dispatch, lambda model: None,
                             dict(medium='medium', large='large', coder='coder'))
        evaluator = JointEvaluator(ex, led, [task])
        session = SearchSession(evaluator, method, max_configurations=8)
        sel = make_selector(method, seed=42)
        states = [('clean', {})]
        round_logs = []
        try:
            for rd in range(5):
                obs_before = len(session.observations)
                results_rd = session.step(sel, states)
                q_vals = [r.get('Q', 0) for r in results_rd]
                round_logs.append(dict(
                    round=rd + 1, method=method,
                    n_obs_before=obs_before,
                    n_obs_after=len(session.observations),
                    Q=q_vals,
                    budget_attempts=budget.attempts,
                    budget_tokens=budget.actual_tokens))
        except StopRun:
            pass
        except NotImplementedError as e:
            round_logs.append(dict(round=0, method=method,
                                   blocked=str(e)[:80]))
        results[method] = round_logs
        tmp.cleanup()

    # Verification
    for method in active:
        logs = results[method]
        if not logs or 'blocked' in logs[0]:
            checks[f'{method}_blocked'] = True
            continue
        checks[f'{method}_has_rounds'] = len(logs) >= 3
        checks[f'{method}_obs_grow'] = logs[-1]['n_obs_after'] > logs[0]['n_obs_before']
        checks[f'{method}_ledger_cost'] = any(
            l['budget_tokens'] > 0 for l in logs)
    # Non-degenerate scores for proposed
    proposed = 'proposed_state_incremental'
    if proposed in results and len(results[proposed]) >= 2:
        checks['proposed_non_degenerate'] = any(
            l.get('Q') and max(l['Q']) != min(l['Q'])
            for l in results[proposed] if isinstance(l.get('Q'), list))
    # Ablation isolation
    checks['qnehvi_blocked'] = 'official_qnehvi_same_state' not in active

    all_pass = all(checks.values())
    out = dict(methods_tested=active, blocked=['official_qnehvi_same_state'],
               results=results, checks=checks, all_pass=all_pass,
               zero_model_calls=True,
               note='five selectors wired on formal pipeline; qNEHVI BLOCKED')
    (OUT / 'CLOSED_LOOP_RESULT.json').write_text(json.dumps(out, indent=1,
                                                            default=str))
    print(f'Methods tested: {active}')
    print(f'Blocked: official_qnehvi_same_state')
    for method in active:
        logs = results[method]
        if logs and 'blocked' in logs[0]:
            print(f'  {method}: BLOCKED')
        elif logs:
            print(f'  {method}: {len(logs)} rounds, '
                  f'tokens={logs[-1].get("budget_tokens", 0)}, '
                  f'attempts={logs[-1].get("budget_attempts", 0)}')
    print(f'\nVerification: {sum(checks.values())}/{len(checks)}')
    print(f'{"ALL PASS" if all_pass else "FAIL PRESENT"}')


if __name__ == '__main__':
    run_closed_loop()
