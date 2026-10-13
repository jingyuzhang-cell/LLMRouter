"""D-contract fault class: mechanism x output-contract mismatch.

Born from the FE paired screening (FE_PAIRED_REPORT.md, 2026-10-13):
thinking-default models (GLM-5.3, GLM-5.3-Flash, deepseek-flash) hit
the max_tokens ceiling on 15/15 calls under a 2048-token JSON contract
(deepseek: 5/5 EMPTY answers, finish=length); the direct-output model
(qwen-plus) passed 5/5 with natural stops. Failure is driven by model
MECHANISM (thinking tokens share the output budget), not capability.

This module makes that finding actionable for the scheduler:

  1. classify_call() — observable-signature fault classifier.
     D_CONTRACT  finish_reason in {length, max_tokens}, OR
                 (completion_tokens >= 0.98 x cap AND parse failure)
     D_CONTENT   parse failure with a natural stop (capability/format)
     OK          parse success
  2. MECHANISM_REGISTRY — per-model thinking_default, evidence-bound.
  3. Recovery action space: PARAM_FIX (same model, contract-adjusted
     params: max_tokens up / thinking disabled) joins MODEL_SWITCH in
     the recovery set R. Decision rule targets the fault class:
     D_CONTRACT -> PARAM_FIX first (blind GLM->deepseek switching
     re-buys the same empty responses — FE cost evidence CNY 0.122);
     D_CONTENT  -> MODEL_SWITCH.

Zero real model calls. Validation over 88 real historical calls lives
in contract_fault_validation.py.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional

# ---- fault classes -------------------------------------------------------
D_CONTRACT = 'D_CONTRACT'
D_CONTENT = 'D_CONTENT'
OK = 'OK'

# finish reasons that mean "cut by the output budget" (OpenAI-compatible
# 'length'; Anthropic-compatible 'max_tokens')
CUT_FINISH_REASONS = {'length', 'max_tokens'}
NATURAL_FINISH_REASONS = {'stop', 'end_turn'}

# signature threshold: completion within 2% of the cap counts as
# ceiling-pinned. FE evidence: GLM 10/10 at exactly 2048; deepseek
# 2047-2048. Historical negatives: max 815 vs cap 2048.
CEILING_RATIO = 0.98

# ---- mechanism registry (evidence-bound, 2026-10-13) --------------------
# thinking_default=True: model consumes output budget on reasoning tokens
# by default (cannot be assumed safe under a tight JSON output cap).
# pass_under_2048_json_contract: FE paired screening (5 calls each).
MECHANISM_REGISTRY: Dict[str, dict] = {
    'GLM-5.3': dict(
        thinking_default=True,
        evidence='FE run fe_20261013_211741: 0/5 strict JSON, '
                 'completion 2048/2048 all, 1 empty; 20-24s latency',
        pass_under_2048_json_contract=0.0, n_calls=5),
    'GLM-5.3-Flash': dict(
        thinking_default=True,
        evidence='FE run fe_20261013_211741: 0/5 strict JSON, '
                 'completion 2048/2048 all, 2 empty',
        pass_under_2048_json_contract=0.0, n_calls=5),
    'deepseek-flash': dict(
        thinking_default=True,
        evidence='FE recovery fe_recovery_20261013_213713: 0/5 strict '
                 'JSON, finish=length 5/5, EMPTY answers 5/5 '
                 '(thinking consumed the whole 2048 budget); '
                 'historical infra ran it with thinking=disabled '
                 '(DEEPSEEK_NONTHINKING_BUDGET_CHECK)',
        pass_under_2048_json_contract=0.0, n_calls=5),
    'qwen-plus': dict(
        thinking_default=False,
        evidence='FE recovery fe_recovery_20261013_213713: 5/5 strict '
                 'JSON, finish=stop 5/5 (339-1372 tok); historical 17/17 '
                 'delivered',
        pass_under_2048_json_contract=1.0, n_calls=5),
    # historical aliases (screening_full80_ledger naming)
    'glm-5.3': None, 'glm-5.3-flash': None,  # resolved below
}
MECHANISM_REGISTRY['glm-5.3'] = dict(
    MECHANISM_REGISTRY['GLM-5.3'],
    evidence='alias of GLM-5.3; historical 17 calls all natural-stop '
             'under cap 2048 with json_object+max_tokens=2048 contract '
             '(short outputs: max 815 tok)')
MECHANISM_REGISTRY['glm-5.3-flash'] = dict(
    MECHANISM_REGISTRY['GLM-5.3-Flash'],
    evidence='alias of GLM-5.3-Flash; historical 17 calls, 1 json '
             'invalid with end_turn at 152 tok (content fault, not '
             'contract)')


def thinking_default(model_id: str) -> Optional[bool]:
    """None if the model is not in the registry (unknown mechanism)."""
    e = MECHANISM_REGISTRY.get(model_id)
    return None if e is None else e['thinking_default']


# ---- signature classifier ------------------------------------------------
def parse_strict_json(text: str) -> bool:
    """Strict JSON validity after Markdown-fence stripping (top-level
    array or object). Mirrors the FE quality-analysis parser."""
    if not text or not text.strip():
        return False
    cleaned = text.strip()
    if cleaned.startswith('```'):
        parts = cleaned.split('\n', 1)
        if len(parts) == 2:
            cleaned = parts[1].rsplit('```', 1)[0].strip()
    try:
        json.loads(cleaned)
        return True
    except json.JSONDecodeError:
        return False


def classify_call(*, answer: Optional[str] = None,
                  parse_ok: Optional[bool] = None,
                  finish_reason: Optional[str] = None,
                  completion_tokens: Optional[int] = None,
                  max_output_tokens: Optional[int] = None) -> dict:
    """Classify one model call from observable signals only.

    Either pass `answer` (parsed here) or a precomputed `parse_ok`
    (for ledgers that store validity instead of text). Returns
    dict(fault, signatures: List[str], notes: List[str]).
    """
    if parse_ok is None:
        parse_ok = parse_strict_json(answer or '')
    sig: List[str] = []
    notes: List[str] = []

    cut = finish_reason in CUT_FINISH_REASONS
    ceiling_pinned = (
        max_output_tokens is not None and completion_tokens is not None
        and completion_tokens >= CEILING_RATIO * max_output_tokens)

    if cut:
        sig.append(f'finish_reason={finish_reason}')
    if ceiling_pinned:
        sig.append(f'completion {completion_tokens}/{max_output_tokens} '
                   f'>= {CEILING_RATIO:.0%} of cap')
    if not parse_ok and (cut or ceiling_pinned):
        sig.append('parse failure under budget cut')
    if not parse_ok and finish_reason in NATURAL_FINISH_REASONS \
            and not ceiling_pinned:
        notes.append('natural stop with parse failure -> content fault')

    if cut or (ceiling_pinned and not parse_ok):
        fault = D_CONTRACT
    elif not parse_ok:
        fault = D_CONTENT
    else:
        fault = OK
    return dict(fault=fault, signatures=sig, notes=notes)


# ---- parameter-aware recovery action space -------------------------------
# Recovery actions now carry call parameters, not just a model choice:
# pi(n) = (model, call_params). PARAM_FIX keeps the model and repairs
# the CONTRACT; MODEL_SWITCH keeps the contract and changes the model.
PARAM_FIX = 'PARAM_FIX'          # same model, params adjusted
MODEL_SWITCH = 'MODEL_SWITCH'    # other model, same params
MODEL_SWITCH_PARAMS = 'MODEL_SWITCH_PARAMS'  # both (fallback)

# contract repairs, in mechanism-targeting order
CONTRACT_REPAIRS = (
    dict(max_tokens_factor=4, thinking=None,
         rationale='widen the shared thinking+output budget 4x; '
                   'keeps model capability'),
    dict(max_tokens_factor=1, thinking='disabled',
         rationale='disable thinking so the full budget is visible '
                   'output (verified compatible for deepseek-flash; '
                   'changes capability profile)'),
    dict(max_tokens_factor=4, thinking='disabled',
         rationale='both repairs — belt and braces, highest pass '
                   'prior, changes capability profile'),
)


def enumerate_recovery_actions(model_id: str,
                               model_menu: List[str]) -> List[dict]:
    """Candidate recovery actions for a failed call on `model_id`.

    Ordered per the FE decision rule: for D_CONTRACT the PARAM_FIX
    entries come first (mechanism-targeted, no re-routing cost, no
    capability change for the first entry); MODEL_SWITCH entries are
    ordered by contract-compatibility pass rate when known.
    """
    actions: List[dict] = []
    for rep in CONTRACT_REPAIRS:
        actions.append(dict(
            action=PARAM_FIX, model_id=model_id,
            max_tokens_factor=rep['max_tokens_factor'],
            thinking=rep['thinking'], rationale=rep['rationale'],
            changes_capability=(rep['thinking'] == 'disabled')))
    for other in model_menu:
        if other == model_id:
            continue
        comp = MECHANISM_REGISTRY.get(other, {})
        actions.append(dict(
            action=MODEL_SWITCH, model_id=other, max_tokens_factor=1,
            thinking=None,
            rationale=f'switch to {other}',
            contract_pass_prior=comp.get(
                'pass_under_2048_json_contract')))
        # if the switch target also thinks by default, the same contract
        # trap awaits — offer the combined repair as its follow-up
        if comp.get('thinking_default'):
            actions.append(dict(
                action=MODEL_SWITCH_PARAMS, model_id=other,
                max_tokens_factor=4, thinking='disabled',
                rationale=f'switch to {other} AND repair contract '
                          f'(target is thinking-default)',
                contract_pass_prior=None,
                changes_capability=True))
    return actions


def choose_recovery(fault: str, model_id: str,
                    model_menu: List[str]) -> dict:
    """Fault-class-targeted decision rule (FE evidence-bound).

    D_CONTRACT -> best PARAM_FIX (keep model, widen budget; the first
      repair changes no capability) — a blind switch to another
      thinking-default model re-buys the failure (FE: deepseek switch
      cost CNY 0.122 for 5 empty responses).
    D_CONTENT  -> best MODEL_SWITCH ordered by known contract pass
      prior (capability hypothesis), PARAM_FIX not offered first.
    OK         -> no recovery.
    """
    if fault == OK:
        return dict(action=None, reason='no fault')
    actions = enumerate_recovery_actions(model_id, model_menu)
    if fault == D_CONTRACT:
        ranked = [a for a in actions if a['action'] == PARAM_FIX]
        rule = 'contract mismatch -> repair params on the same model'
    else:  # D_CONTENT
        ranked = sorted(
            (a for a in actions if a['action'] == MODEL_SWITCH),
            key=lambda a: -(a.get('contract_pass_prior') or -1.0))
        rule = 'content failure with natural stop -> switch model'
    if not ranked:
        # no switch target available: fall back to param repair
        ranked = [a for a in actions if a['action'] == PARAM_FIX]
        rule += ' (no switch target; param repair fallback)'
    return dict(action=ranked[0],
                ranked=ranked[:2], rule=rule)
