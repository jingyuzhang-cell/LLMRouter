"""Ledger-only budget aggregation (zero calls; survives any executor crash)."""
import json
import sys
from pathlib import Path

PILOT = Path('/root/capital_opinion_pilot')


def audit(ledger_path):
    calls = [json.loads(l) for l in Path(ledger_path).read_text().splitlines() if l.strip()]
    per_purpose = {}
    for c in calls:
        s = per_purpose.setdefault(c['purpose'], {'n': 0, 'in': 0, 'out': 0, 'max': 0})
        s['n'] += 1
        s['in'] += c['usage']['input_tokens']
        s['out'] += c['usage']['output_tokens']
        s['max'] += c['max_tokens']
    actual = sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in calls)
    return {'ledger': str(ledger_path), 'n_calls': len(calls), 'settled_actual': actual,
            'conservative_actual_plus_sum_max': actual + sum(c['max_tokens'] for c in calls),
            'per_purpose': per_purpose}


if __name__ == '__main__':
    for p in sys.argv[1:] or [PILOT / 'model_call_ledger_v21.jsonl']:
        r = audit(p)
        print(json.dumps(r, ensure_ascii=False, indent=1))
