"""B2: reference-independent deterministic final-answer extractor for the 17 numeric tasks.

Frozen rule (per E4_1_NUMERIC_UNIT_CONTRACT_FROZEN.json + Amendment-001/002):
  - Extract the candidate's STATED final answer; do NOT scan the text for the
    number closest to the reference.
  - percent: strip '%'; bare number taken at face value in percent-points. NEVER
    multiply by 100 (C9.2: 'never blind factor-100 matching').
  - currency_amount: normalize suffixed numbers (million/billion/thousand/M/B/K) to
    the contract's canonical scale; a BARE number is presumed to already be in the
    canonical (source) scale.
  - ratio / currency_per_share: take the number at face value (strip $/commas for
    per-share).
  - tolerance: abs(extracted - canonical) <= max(1e-6, 1e-4*abs(canonical)).
"""
from __future__ import annotations
import re

_NUM = r'[-+]?\d[\d,]*(?:\.\d+)?'
_SUFFIX = r'(?:\s*(?:million|billion|thousand|[MBK]\b))'
_TOKEN_RE = re.compile(
    r'(?P<sign>[-+]?)\s*\$?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<suf>%|million|billion|thousand|[MBK]\b)?',
    re.I,
)
_SCALE_FACTORS = {'million': 1e6, 'billion': 1e9, 'thousand': 1e3, 'm': 1e6, 'b': 1e9, 'k': 1e3}
_CUE_RE = re.compile(r'(answer\s*(?:is|:)|final\s*answer\s*:|=\s*)', re.I)


def _to_float(num_str: str) -> float:
    return float(num_str.replace(',', ''))


def _last_token_index(tokens, quantity_kind: str):
    """Pick the token to score, by a gold-independent rule based only on quantity_kind."""
    if not tokens:
        return None
    if quantity_kind == 'percent':
        pct = [i for i, t in enumerate(tokens) if t['suf'] == '%']
        if pct:
            return pct[-1]
    elif quantity_kind in ('currency_amount', 'currency_per_share'):
        suffixed = [i for i, t in enumerate(tokens) if t['suf'] and t['suf'] != '%']
        if suffixed:
            return suffixed[-1]
    return len(tokens) - 1


def extract_final_answer(text: str, quantity_kind: str, canonical_scale: float = 1.0):
    """Return the normalized numeric value of the candidate's stated final answer, or None."""
    if text is None:
        return None
    body = str(text).strip()
    # Narrow to text after the last answer-cue, if any cue is present.
    cue_matches = list(_CUE_RE.finditer(body))
    if cue_matches:
        body = body[cue_matches[-1].end():].strip()
    tokens = []
    for m in _TOKEN_RE.finditer(body):
        if m.group('num') is None:
            continue
        suf = (m.group('suf') or '').strip().lower() or None
        tokens.append({'num': m.group('num'), 'sign': m.group('sign'), 'suf': suf})
    idx = _last_token_index(tokens, quantity_kind)
    if idx is None:
        return None
    t = tokens[idx]
    value = _to_float(t['num'])
    if t['sign'] == '-':
        value = -value
    if quantity_kind == 'percent':
        # '%' is stripped; the number stays in percent-points. No factor-100.
        return value
    if quantity_kind == 'currency_per_share':
        return value  # absolute USD/share; $ and commas already stripped
    if quantity_kind == 'currency_amount':
        # A scale suffix (million/M/billion/B/thousand/K) means the number is absolute
        # in that unit: convert to absolute, then divide by the contract's canonical
        # scale to reach canonical units. A BARE number (no suffix) is presumed to
        # already be in the canonical (source) scale and is returned as-is.
        # Documented limitation: an absolute dollar amount written without a scale
        # suffix (e.g. '11,100,000') is taken at face value in canonical units.
        if t['suf'] and t['suf'] in _SCALE_FACTORS:
            return (value * _SCALE_FACTORS[t['suf']]) / canonical_scale
        return value
    # ratio
    return value


def score_deterministic(text: str, contract_entry: dict) -> dict:
    qk = contract_entry['quantity_kind']
    canonical = float(contract_entry['canonical_value'])
    scale = float(contract_entry.get('scale', 1) or 1)
    tol = max(1e-6, 1e-4 * abs(canonical))
    extracted = extract_final_answer(text, qk, scale)
    within = extracted is not None and abs(extracted - canonical) <= tol
    return {
        'score': 1.0 if within else 0.0,
        'extracted': extracted,
        'canonical': canonical,
        'tolerance': tol,
        'within_tolerance': within,
        'quantity_kind': qk,
        'reason': 'match' if within else ('no_number_extracted' if extracted is None else 'out_of_tolerance'),
    }
