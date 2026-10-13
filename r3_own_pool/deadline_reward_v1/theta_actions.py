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
