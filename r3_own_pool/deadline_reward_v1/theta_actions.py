"""Theta (execution-parameter) support table + legal action enumeration
for the joint action a = (Z, R, pi, theta).

Operator ruling 2026-10-13 (DD fault-aware parameter recovery):
  - theta must be declared per-model; NEVER send unsupported combos.
  - deepseek-flash supports thinking: {"type": "disabled"}.
  - GLM-5.3 / GLM-5.3-Flash do NOT support disabling thinking; legal
    controls are reasoning_effort in {low, high, max} and the output
    token cap.
  - qwen-plus is a direct-output model (enable_thinking exists, default
    off; natural stops observed 5/5).
  - Every parameter change is charged to real token/cost/latency
    budgets.
  - Outcomes of theta variants that were never really executed are
    UNOBSERVED: they may inform priors but NEVER settle as observed
    quality gains (Phase-3 honesty rule).

Real observation anchors (provenance-bound):
  FE paired runs (fe_20261013_211741 / fe_recovery_20261013_213713):
    GLM-5.3, GLM-5.3-Flash, deepseek-flash @ default theta,
    max_tokens=2048 -> 0/15 strict JSON, all completion_tokens at cap.
    qwen-plus @ default -> 5/5 strict JSON (finish=stop).
  Historical screening (screening_full80_ledger, frozen registry
  screening_full_80_frozen.json):
    deepseek-flash @ thinking=disabled + response_format=json_object +
    max_tokens=2048 -> 17/17 json_valid, completion 39-773 (med 224),
    latency 0.92-10.31s. CAVEAT: different prompts/node types than FE;
    usable as a PRIOR only, not as an FE-quality observation.

Zero real model calls in this module.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ---- theta support table (operator ruling + evidence) --------------------
MODEL_THETA_SUPPORT: Dict[str, dict] = {
    'GLM-5.3': dict(
        thinking_disable=False,
        reasoning_effort=('low', 'high', 'max'),   # ruling: control
        max_tokens_range=(1, 65536),
        response_format=False,                      # not evidenced
        evidence='ruling 2026-10-13: no thinking off; reasoning_effort '
                 'low/high/max only'),
    'GLM-5.3-Flash': dict(
        thinking_disable=False,
        reasoning_effort=('low', 'high', 'max'),
        max_tokens_range=(1, 65536),
        response_format=False,
        evidence='same family rules as GLM-5.3'),
    'deepseek-flash': dict(
        thinking_disable=True,
        reasoning_effort=None,
        max_tokens_range=(1, 8192),
        response_format=True,   # json_object used in historical calls
        evidence='deepseek docs (ruling): thinking {"type":"disabled"} '
                 'supported; historical 17/17 json_valid with it'),
    'qwen-plus': dict(
        thinking_disable=True,   # enable_thinking param exists
        reasoning_effort=None,
        max_tokens_range=(1, 8192),
        response_format=True,    # json_object used in historical calls
        evidence='dashscope compatible-mode; enable_thinking default '
                 'off for qwen-plus; historical 17 calls used '
                 'response_format json_object'),
}
# aliases used in ledgers
MODEL_THETA_SUPPORT['glm-5.3'] = MODEL_THETA_SUPPORT['GLM-5.3']
MODEL_THETA_SUPPORT['glm-5.3-flash'] = MODEL_THETA_SUPPORT['GLM-5.3-Flash']

DEFAULT_THETA = dict(reasoning_effort=None, thinking=None,
                     max_tokens=2048, response_format=None)
# i.e. the FE contract: no effort control, thinking untouched, cap 2048


def theta_legal(model_id: str, theta: dict) -> tuple:
    """(legal, reason). theta keys: reasoning_effort, thinking,
    max_tokens, response_format (None = don't send)."""
    sup = MODEL_THETA_SUPPORT.get(model_id)
    if sup is None:
        return False, f'model {model_id} not in support table'
    re_ = theta.get('reasoning_effort')
    if re_ is not None:
        if sup['reasoning_effort'] is None:
            return False, f'{model_id} has no reasoning_effort support'
        if re_ not in sup['reasoning_effort']:
            return False, (f'reasoning_effort {re_} not in '
                           f'{sup["reasoning_effort"]} for {model_id}')
    th = theta.get('thinking')
    if th is not None:
        if th not in ('enabled', 'disabled'):
            return False, f'unknown thinking value {th}'
        if th == 'disabled' and not sup['thinking_disable']:
            return False, (f'{model_id} does NOT support disabling '
                           f'thinking (use reasoning_effort instead)')
    mt = theta.get('max_tokens')
    if mt is not None:
        lo, hi = sup['max_tokens_range']
        if not (lo <= mt <= hi):
            return False, f'max_tokens {mt} outside [{lo},{hi}]'
    if theta.get('response_format') and not sup['response_format']:
        return False, f'{model_id} response_format not supported'
    return True, 'ok'


def enumerate_legal_thetas(model_id: str) -> List[dict]:
    """The parameter-repair ladder for a model: same model, repaired
    theta. Ordered per the ruling's repair philosophy — cheapest
    capability-preserving change first. Every entry carries its
    observation status (never claim unobserved as observed)."""
    out = []
    if MODEL_THETA_SUPPORT.get(model_id, {}).get('reasoning_effort'):
        # GLM family: lower the reasoning intensity first
        out.append(dict(theta=dict(DEFAULT_THETA,
                                   reasoning_effort='low'),
                        repair='reasoning_effort=low',
                        capability_preserving=True,
                        observed=True, refuted=True,
                        observed_where='param_recovery FE3/FE4: REFUTED '
                                        '(still max_tokens cut at 2048)'))
        out.append(dict(theta=dict(DEFAULT_THETA,
                                   reasoning_effort='low',
                                   max_tokens=8192),
                        repair='reasoning_effort=low + max_tokens=8192',
                        capability_preserving=True,
                        observed=True, refuted=False,
                        observed_where='param_recovery FE3/FE4: 2/2 '
                                        'end_turn, strict JSON, recall '
                                        'beats frozen bounds'))
    if MODEL_THETA_SUPPORT.get(model_id, {}).get('thinking_disable'):
        # deepseek family (and qwen, though it needs no repair)
        out.append(dict(theta=dict(DEFAULT_THETA, thinking='disabled'),
                        repair='thinking=disabled',
                        capability_preserving=False,
                        observed=True, refuted=False,
                        observed_where='screening_full80 17/17 (other '
                                        'prompts, PRIOR) + param_recovery '
                                        'FE3/FE4 2/2 functional'))
        out.append(dict(theta=dict(DEFAULT_THETA, thinking='disabled',
                                   max_tokens=8192),
                        repair='thinking=disabled + max_tokens=8192',
                        capability_preserving=False,
                        observed=False, refuted=False,
                        observed_where=None))
    for a in out:  # hard legality gate
        ok, why = theta_legal(model_id, a['theta'])
        assert ok, f'illegal theta emitted for {model_id}: {why}'
    return out


def budget_reservation(model_id: str, theta: dict,
                       prompt_tokens: int) -> dict:
    """Conservative resource reservation for a (model, theta) call.
    Parameter changes are charged for real: reservation uses the full
    new cap for output tokens (we cannot assume the model will stop
    early on an unobserved theta)."""
    sup = MODEL_THETA_SUPPORT[model_id]
    mt = theta.get('max_tokens') or DEFAULT_THETA['max_tokens']
    hi = sup['max_tokens_range'][1]
    mt = min(mt, hi)
    # thinking-disabled historical real range: outputs stay small, but
    # reservation stays conservative (full cap) until observed on THIS
    # contract.
    lat_prior = 35.0  # conservative seconds; FE observed 7.8-34.3s
    return dict(tokens_in=prompt_tokens, tokens_out_reserved=mt,
                max_tokens=mt, latency_s_reserved=lat_prior,
                provenance='conservative reservation (full new cap)')


# ---- DEV-set priors for online decisions (derived from anchors) ----------
def wilson_lb(k: int, n: int, z: float = 1.96) -> float:
    """Wilson 95% lower bound — the pessimistic small-n stance."""
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    rad = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return round(max(0.0, (centre - rad) / d), 4)


def _mk(pass_k, pass_n, rec_k, rec_n, provenance):
    return dict(
        pass_rate=round(pass_k / pass_n, 4) if pass_n else 0.0,
        pass_rate_lb=wilson_lb(pass_k, pass_n),
        pooled_recall=(round(rec_k / rec_n, 4) if rec_n else 0.0),
        pooled_recall_lb=wilson_lb(rec_k, rec_n),
        recall_n=rec_n, pass_n=pass_n,
        provenance=provenance)


# Pooled counts (honest small-n handling: pooled recall, not the mean
# of per-task recalls; pass at Wilson lower bounds).
PRIORS: Dict[str, dict] = {
    'GLM-5.3|low@8192': _mk(
        2, 2, 8 + 3, 17 + 4,
        'Phase-4 cells 5-6: 2/2 pass, pooled recall 11/21'),
    'GLM-5.3-Flash|low@8192': _mk(
        2, 2, 9 + 3, 17 + 4,
        'Phase-4 cells 7-8: 2/2 pass, pooled recall 12/21'),
    'GLM-5.3|low@2048': _mk(
        0, 2, 0, 0,
        'Phase-4 cells 3-4 REFUTED (still max_tokens cut)'),
    'deepseek-flash|thinking=disabled': _mk(
        # pass: FE 2/2 same-contract blended with historical 17/17
        # different-prompt discounted x0.5 -> effective 8.5/9
        8, 9, 7 + 3, 17 + 4,
        'Phase-4 cells 1-2 + historical 17/17 (discounted); pooled '
        'recall 10/21'),
    'qwen-plus|default': _mk(
        5, 5, 6 + 2 + 1, 17 + 4 + 1,
        'FE recovery 5/5 pass, pooled recall 9/22'),
}
UNINFORMED_PRIOR = dict(
    pass_rate=0.5, pass_rate_lb=0.5,
    pooled_recall=0.35, pooled_recall_lb=0.35,
    recall_n=0, pass_n=0, provenance='uninformed')


def prior_for(model_id: str, theta: dict) -> dict:
    re_ = theta.get('reasoning_effort')
    mt = theta.get('max_tokens')
    key = None
    if model_id.startswith('GLM') and re_ == 'low':
        key = f'{model_id}|low@{mt}'
    elif model_id == 'deepseek-flash' and theta.get('thinking') == \
            'disabled' and mt in (None, 2048):
        key = 'deepseek-flash|thinking=disabled'
    elif model_id == 'qwen-plus' and theta == dict(DEFAULT_THETA):
        key = 'qwen-plus|default'
    return PRIORS.get(key, UNINFORMED_PRIOR)


def prior_key(model_id: str, theta: dict):
    """Canonical bucket key for the store."""
    re_ = theta.get('reasoning_effort')
    mt = theta.get('max_tokens')
    if model_id.startswith('GLM') and re_ == 'low':
        return f'{model_id}|low@{mt}'
    if model_id == 'deepseek-flash' and theta.get('thinking') == \
            'disabled' and mt in (None, 2048):
        return 'deepseek-flash|thinking=disabled'
    if model_id == 'qwen-plus' and theta == dict(DEFAULT_THETA):
        return 'qwen-plus|default'
    return None


class PriorStore:
    """Within-run prior learning for DD-Online. Pooled counts start
    from the DEV prior counts; each COMPLETED task's executed actions
    update the store (pass from the node's contract outcome, recall
    from silver-matched counts when evaluable). Wilson-LB priors are
    recomputed on every read, so uncertainty shrinks as n grows.

    Legality: updates happen only AFTER a task finishes (its decision
    was already made); task k's outcome can never inform task k's
    decision. No same-task lookahead by construction.
    """

    def __init__(self):
        self.counts = {}
        for k, v in PRIORS.items():
            if v.get('pass_n'):
                self.counts[k] = dict(
                    pass_k=round(v['pass_rate'] * v['pass_n']),
                    pass_n=v['pass_n'],
                    rec_k=round(v['pooled_recall'] * v['recall_n']),
                    rec_n=v['recall_n'])

    def update(self, key: str, passed: bool,
               rec_k: int = 0, rec_n: int = 0):
        c = self.counts.setdefault(key, dict(pass_k=0, pass_n=0,
                                             rec_k=0, rec_n=0))
        c['pass_k'] += int(bool(passed))
        c['pass_n'] += 1
        if rec_n > 0:
            c['rec_k'] += max(0, min(rec_k, rec_n))
            c['rec_n'] += rec_n

    def prior(self, key: str) -> dict:
        c = self.counts.get(key)
        if not c or not c['pass_n']:
            return UNINFORMED_PRIOR
        return dict(
            pass_rate=round(c['pass_k'] / c['pass_n'], 4),
            pass_rate_lb=wilson_lb(c['pass_k'], c['pass_n']),
            pooled_recall=(round(c['rec_k'] / c['rec_n'], 4)
                           if c['rec_n'] else 0.0),
            pooled_recall_lb=(wilson_lb(c['rec_k'], c['rec_n'])
                              if c['rec_n'] else 0.0),
            recall_n=c['rec_n'], pass_n=c['pass_n'],
            provenance=f'PriorStore(n={c["pass_n"]})')

    def sample(self, key: str, rng) -> dict:
        """Thompson sample: Beta posteriors on pass and recall. Gives
        untried/under-tried candidates natural exploration while
        converging to the true best — fixes the pessimistic-LB
        lock-in (never exploring a mis-prioried candidate)."""
        c = self.counts.get(key)
        if not c or not c['pass_n']:
            return dict(pass_rate=0.5, pass_rate_lb=0.5,
                        pooled_recall=0.35, pooled_recall_lb=0.35,
                        recall_n=0, pass_n=0,
                        provenance='uninformed-sample')
        pr = rng.betavariate(c['pass_k'] + 1,
                             c['pass_n'] - c['pass_k'] + 1)
        if c['rec_n']:
            rc = rng.betavariate(c['rec_k'] + 1,
                                 c['rec_n'] - c['rec_k'] + 1)
        else:
            rc = 0.35
        return dict(pass_rate=round(pr, 4), pass_rate_lb=round(pr, 4),
                    pooled_recall=round(rc, 4),
                    pooled_recall_lb=round(rc, 4),
                    recall_n=c['rec_n'], pass_n=c['pass_n'],
                    provenance=f'Thompson(n={c["pass_n"]})')


# ---- real per-(model, theta) outcome anchors (read-only evidence) --------
REAL_OUTCOME_ANCHORS: Dict[str, dict] = {
    'GLM-5.3|default': dict(
        strict_json=0, n=5, completion_at_cap=5, empty=1,
        source='FE fe_20261013_211741'),
    'GLM-5.3-Flash|default': dict(
        strict_json=0, n=5, completion_at_cap=5, empty=2,
        source='FE fe_20261013_211741'),
    'deepseek-flash|default': dict(
        strict_json=0, n=5, completion_at_cap=5, empty=5,
        finish='length', source='FE fe_recovery_20261013_213713'),
    'qwen-plus|default': dict(
        strict_json=5, n=5, finish='stop',
        citation_conform=0,   # cites in-text source ids, not ledger ids
        source='FE fe_recovery_20261013_213713'),
    'deepseek-flash|thinking=disabled': dict(
        strict_json=17, n=17, completion_max=773, completion_med=224,
        latency_min=0.92, latency_max=10.31,
        caveat='different prompts + response_format=json_object; '
               'PRIOR ONLY — not an FE-contract observation',
        source='screening_full80_ledger + frozen registry'),
    # ---- Phase-4 observed (FE3/FE4, same prompts, param_recovery run) ----
    'GLM-5.3|low@2048': dict(
        strict_json=0, n=2, completion_at_cap=2, finish='max_tokens',
        verdict='REFUTED: low effort alone does NOT fit the 2048 cap '
                '(the budget itself is the binding constraint)',
        source='param_recovery FE3/FE4 cells 3-4'),
    'GLM-5.3|low@8192': dict(
        strict_json=2, n=2, finish='end_turn', outputs=(2961, 2624),
        recall=dict(FE3=8 / 17, FE4=3 / 4), semantic=True,
        verdict='FUNCTIONAL+SEMANTIC (both beats frozen diagnostic '
                'bounds 7/17, 2/4)',
        source='param_recovery FE3/FE4 cells 5-6'),
    'GLM-5.3-Flash|low@8192': dict(
        strict_json=2, n=2, finish='end_turn', outputs=(2617, 1862),
        recall=dict(FE3=9 / 17, FE4=3 / 4), semantic=True,
        verdict='FUNCTIONAL+SEMANTIC',
        source='param_recovery FE3/FE4 cells 7-8'),
    'deepseek-flash|disabled@2048(FE)': dict(
        strict_json=2, n=2, finish='stop', outputs=(1888, 1612),
        recall=dict(FE3=7 / 17, FE4=3 / 4),
        verdict='FUNCTIONAL both; SEMANTIC on FE4 only (FE3 7/17 '
                'equals the diagnostic bound, not above)',
        source='param_recovery FE3/FE4 cells 1-2'),
}
