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

# ---- fine-grained taxonomy (operator ruling 2026-10-13) ------------------
# Six observable fault types, kept SEPARATE from diagnosis and action
# selection (identification != remedy). Families group them for the
# earlier family-level API.
F_TRUNCATED = 'F_TRUNCATED'            # budget cut (empty=True variant)
F_EMPTY = 'F_EMPTY_RESPONSE'           # empty visible output, natural stop
F_JSON = 'F_JSON_INVALID'              # natural stop, unparseable
F_CITATION = 'F_EVIDENCE_CITATION'     # valid JSON, citations off-contract
F_UNAVAILABLE = 'F_MODEL_UNAVAILABLE'  # transport/5xx/timeout, no answer
F_PRE_DISPATCH = 'F_PRE_DISPATCH'      # client-side: code/credential/
                                       # request-construction error

FAMILY = {
    F_TRUNCATED: 'BUDGET', F_EMPTY: 'CONTENT', F_JSON: 'CONTENT',
    F_CITATION: 'CITATION', F_UNAVAILABLE: 'EXECUTION',
    F_PRE_DISPATCH: 'EXECUTION', OK: 'OK',
}

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
    empty_visible = not (answer or '').strip()

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


# ---- v2: entry-level classification over the six fine types --------------
def citations_of(parsed) -> List[str]:
    """Collect evidence_doc_id values from a parsed JSON answer
    (top-level array of fact objects, or {facts: [...]})."""
    items = parsed if isinstance(parsed, list) else (
        parsed.get('facts') if isinstance(parsed, dict) else None)
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(
                it.get('evidence_doc_id'), str):
            out.append(it['evidence_doc_id'])
    return out


def _decode_fenced(text: str) -> str:
    text = (text or '').strip()
    if text.startswith('```'):
        parts = text.split('\n', 1)
        if len(parts) == 2:
            text = parts[1].rsplit('```', 1)[0].strip()
    return text


def classify_entry(entry: dict, *, expected_doc_ids: Optional[List[str]]
                   = None, prompt_text: Optional[str] = None,
                   parse_ok: Optional[bool] = None) -> dict:
    """Full six-type classification for one ledger-style record.

    Identification only — no remedy implied. `entry` accepts FE ledger
    shapes: status in {delivered, ERROR}, answer/usage/finish_reason/
    max_output_tokens/error fields. `parse_ok` overrides answer
    parsing for ledgers that store validity instead of text (e.g. the
    historical screening ledger's json_valid field).

    Citation layer (applies only when format passed AND
    expected_doc_ids given):
      F_CITATION with cause:
        - 'contract_unverifiable': NONE of the expected ids appears in
          prompt_text -> the requirement references an id the model
          never saw; prompt/contract defect, not a model fault
          (observed on ALL FE answers: ledger ids like
          'D3_E03-yuandao_2026-08-29' never occur in the evidence
          text; models cite the real in-text source ids instead).
        - 'model_citation_fault': ids were available in the prompt but
          the model cited outside the set.
    """
    status = entry.get('status', 'delivered')
    sig: List[str] = []
    notes: List[str] = []

    if status != 'delivered':
        err = str(entry.get('error', ''))
        err_l = err.lower()
        if any(k in err_l for k in
               ('timeout', 'timed out', 'connection', 'connectionerror',
                'http 5', 'httperror 5', 'overload', 'service '
                'unavailable')):
            fault = F_UNAVAILABLE
        else:
            # ModuleNotFoundError (code), invalid api key (config),
            # malformed request — all client-side, pre-model
            fault = F_PRE_DISPATCH
        sig.append(f'entry status={status}')
        if 'modulenotfounderror' in err_l:
            notes.append('code defect (import of JSON file)')
        elif '401' in err_l or 'authentication' in err_l:
            notes.append('credential invalid (client config)')
        return dict(fault=fault, family=FAMILY[fault], signatures=sig,
                    notes=notes, citation=None)

    # None = answer text unavailable (validity-only ledger entry);
    # '' = genuinely empty visible output — the two must not collapse
    answer = entry.get('answer')
    finish = entry.get('finish_reason')
    usage = entry.get('usage', {}) or {}
    cap = entry.get('max_output_tokens')

    parsed_ok = (parse_strict_json(answer) if parse_ok is None
                 else bool(parse_ok))
    base = classify_call(answer=answer, parse_ok=parsed_ok,
                         finish_reason=finish,
                         completion_tokens=usage.get('completion_tokens'),
                         max_output_tokens=cap)
    # empty_visible is only decidable when the answer TEXT is present;
    # ledgers storing only validity (answer=None) keep it False with a
    # note so a missing answer is never read as "model returned empty"
    empty_visible = answer is not None and not answer.strip()
    if answer is None:
        base.setdefault('notes', []).append(
            'answer text unavailable (validity-only ledger)')

    if base['fault'] == D_CONTRACT:
        fault = F_TRUNCATED
        sig = base['signatures'] + [
            f'empty_visible={empty_visible}']
        notes = ['budget cut; empty variant = thinking consumed the '
                 'whole budget before any visible output'] if \
            empty_visible else ['mid-output cut']
        citation = None
    elif base['fault'] == D_CONTENT:
        fault = F_EMPTY if empty_visible else F_JSON
        sig = base['signatures'] + [
            f'finish_reason={finish} (natural)',
            f'visible_chars='
            f'{len(answer) if answer is not None else "unknown"}']
        notes = base['notes']
        citation = None
    else:
        # format passed -> citation layer if requested
        citation = None
        if expected_doc_ids is not None:
            try:
                parsed = json.loads(_decode_fenced(answer))
            except json.JSONDecodeError:
                parsed = None
            cited = citations_of(parsed) if parsed is not None else []
            bad = [c for c in cited if c not in expected_doc_ids]
            if bad:
                fault = F_CITATION
                in_prompt = [d for d in expected_doc_ids
                             if prompt_text and d in prompt_text]
                cause = ('contract_unverifiable' if not in_prompt
                         else 'model_citation_fault')
                sig = [f'{len(bad)}/{len(cited)} citations outside '
                       f'expected id set',
                       f'expected ids present in prompt: {bool(in_prompt)}']
                notes = [f'citation cause = {cause}',
                         f'example cited: {bad[0][:60]}']
                citation = dict(cause=cause, cited=cited,
                                expected=expected_doc_ids)
            else:
                fault = OK
                citation = dict(cause='ok', cited=cited,
                                expected=expected_doc_ids)
        else:
            fault = OK

    return dict(fault=fault, family=FAMILY[fault], signatures=sig,
                notes=notes, citation=citation)


# ---- parameter-aware recovery action space -------------------------------
# Recovery actions now carry call parameters, not just a model choice:
# pi(n) = (model, call_params, theta). PARAM_FIX keeps the model and
# repairs the contract via LEGAL theta only (theta_actions is the
# authority); MODEL_SWITCH keeps the contract and changes the model.
from deadline_reward_v1 import theta_actions as _theta  # noqa: E402

PARAM_FIX = 'PARAM_FIX'          # same model, legal theta adjusted
MODEL_SWITCH = 'MODEL_SWITCH'    # other model, same params
MODEL_SWITCH_PARAMS = 'MODEL_SWITCH_PARAMS'  # both (fallback)


def enumerate_recovery_actions(model_id: str,
                               model_menu: List[str]) -> List[dict]:
    """Candidate recovery actions for a failed call on `model_id`,
    theta-legality enforced per model (operator ruling: never emit an
    unsupported combination — GLM models never get thinking=disabled).
    """
    actions: List[dict] = []
    for a in _theta.enumerate_legal_thetas(model_id):
        actions.append(dict(
            action=PARAM_FIX, model_id=model_id, theta=a['theta'],
            rationale=a['repair'],
            observed=a['observed'],
            changes_capability=not a['capability_preserving']))
    for other in model_menu:
        if other == model_id:
            continue
        comp = MECHANISM_REGISTRY.get(other, {})
        actions.append(dict(
            action=MODEL_SWITCH, model_id=other,
            theta=dict(_theta.DEFAULT_THETA),
            rationale=f'switch to {other}',
            contract_pass_prior=comp.get(
                'pass_under_2048_json_contract')))
        # if the switch target also thinks by default, the same
        # contract trap awaits — offer the combined repair follow-up
        if comp.get('thinking_default') and other in \
                _theta.MODEL_THETA_SUPPORT:
            legal = _theta.enumerate_legal_thetas(other)
            if legal:
                actions.append(dict(
                    action=MODEL_SWITCH_PARAMS, model_id=other,
                    theta=legal[0]['theta'],
                    rationale=f'switch to {other} AND repair contract '
                              f'({legal[0]["repair"]})',
                    observed=legal[0]['observed'],
                    changes_capability=True))
    return actions


def choose_recovery(fault: str, model_id: str,
                    model_menu: List[str]) -> dict:
    """Fault-family-targeted decision rule (identification and remedy
    stay separate: a budget-cut signature licenses a PARAM_FIX
    CANDIDATE, never the claim that it will work — unobserved repairs
    carry observed=False and their outcomes await real calls).

    F_TRUNCATED (family BUDGET) -> first legal PARAM_FIX on the same
      model. A blind switch to another thinking-default model re-buys
      the failure (FE: deepseek switch cost CNY 0.122 for five empty
      responses).
    F_EMPTY/F_JSON (family CONTENT) -> MODEL_SWITCH ordered by known
      contract pass prior.
    F_CITATION -> not a model remedy: contract/prompt repair (see
      classify_entry cause field).
    """
    if fault in (OK,):
        return dict(action=None, reason='no fault')
    if fault == F_CITATION:
        return dict(action=dict(action='PROMPT_CONTRACT_REPAIR',
                                rationale='citation fault: fix the '
                                          'prompt/contract (state the '
                                          'doc_id), not the model'),
                    ranked=[], rule='citation -> contract repair')
    actions = enumerate_recovery_actions(model_id, model_menu)
    budget_family = fault in (F_TRUNCATED, D_CONTRACT)
    if budget_family:
        ranked = [a for a in actions if a['action'] == PARAM_FIX]
        rule = 'budget cut -> first legal theta repair on same model'
    else:
        ranked = sorted(
            (a for a in actions if a['action'] == MODEL_SWITCH),
            key=lambda a: -(a.get('contract_pass_prior') or -1.0))
        rule = 'content failure with natural stop -> switch model'
    if not ranked:
        ranked = [a for a in actions if a['action'] == PARAM_FIX]
        rule += ' (no switch target; param repair fallback)'
    return dict(action=ranked[0],
                ranked=ranked[:2], rule=rule)
