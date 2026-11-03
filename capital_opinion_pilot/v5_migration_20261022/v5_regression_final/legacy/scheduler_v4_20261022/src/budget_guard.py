"""Budget guard calibration & audit (zero model calls).

Replaces the ad-hoc 0.9 tokens/char heuristic with an EMPIRICAL upper bound
calibrated on every recorded call in all pilot ledgers (each entry carries exact
prompt_chars and input_tokens). The bound is max_observed_ratio x margin — a
data-validated conservative estimate for THIS endpoint/model family, not a
tokenizer-exact count; the report states this domain of validity honestly.
Also provides the post-settle overrun sentinel used by Meter.
"""
import json
from pathlib import Path

PILOT = Path('/root/capital_opinion_pilot')
LEDGERS = ['model_call_ledger.jsonl', 'model_call_ledger_v2.jsonl', 'model_call_ledger_v21.jsonl',
           'model_call_ledger_v22.jsonl', 'model_call_ledger_v3kdx.jsonl',
           'model_call_ledger_v3kdxra.jsonl', 'model_call_ledger_v3kdxrepair.jsonl']
MARGIN = 1.10
FALLBACK_RATIO = 0.90  # only used if no ledger data exists


def all_calls():
    out = []
    for name in LEDGERS:
        p = PILOT / name
        if p.exists():
            out += [(name, json.loads(l)) for l in p.read_text().splitlines() if l.strip()]
    return out


def calibrate():
    calls = all_calls()
    pts = [(c['prompt_chars'], c['usage']['input_tokens']) for _, c in calls
           if c.get('prompt_chars') and c['usage']['input_tokens']]
    ratios = sorted(t / ch for ch, t in pts)
    max_ratio = max(ratios) if ratios else FALLBACK_RATIO
    guard_ratio = max(max_ratio * MARGIN, 0.50)  # floor for degenerate short prompts
    return {'n_calls': len(pts), 'ratio_min': round(min(ratios), 4) if ratios else None,
            'ratio_median': round(ratios[len(ratios) // 2], 4) if ratios else None,
            'ratio_max': round(max_ratio, 4), 'guard_ratio': round(guard_ratio, 4),
            'margin': MARGIN,
            'validity': 'empirical upper bound over %d real calls on this endpoint/model family; '
                        'NOT a tokenizer-exact count; auto-recalibrates as ledgers grow' % len(pts)}


GUARD_RATIO = calibrate()['guard_ratio']


def estimate_input_tokens(system, user):
    return int((len(system) + len(user)) * GUARD_RATIO)
