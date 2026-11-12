"""Audit the remaining 50 prefilter survivors for P2 task pool expansion (network PDF retrieval, zero model calls)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, '.')
import search_cases as S

log = json.loads(Path('PREFILTER_LOG.json').read_text('utf-8'))
by = {r['code']: r for r in log['survivors']}
already = {r['code'] for r in json.loads(Path('AUDIT_LOG.json').read_text('utf-8'))['results']}
ranked = json.loads(Path('AUDIT_ORDER.json').read_text('utf-8'))['order']
to_audit = [c for c in ranked if c not in already]
print(f'auditing {len(to_audit)} remaining candidates', flush=True)
S.audit_codes(to_audit)
