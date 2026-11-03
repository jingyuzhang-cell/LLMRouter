"""Simplified coverage scoring for Stage-C standalone runner."""
import re, sys
sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import norm, all_dates

def score_coverage(text, silver_facts):
    if not silver_facts:
        return {'Q': 0, 'coverage': 0, 'covered': [], 'missed': []}
    covered = []
    for f in silver_facts:
        a, typ = f['answer'], f.get('answer_type', 'text')
        nt = norm(text)
        na = norm(a)
        if typ == 'date':
            dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', a)
            if dm:
                cn = f'{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日'
                covered.append(f['fact_id'] if (na in nt or norm(cn) in nt) else None)
            else:
                covered.append(f['fact_id'] if na in nt else None)
        else:
            covered.append(f['fact_id'] if na in nt else None)
    covered = [c for c in covered if c]
    cov = len(covered) / len(silver_facts)
    return {'Q': round(cov, 4), 'coverage': round(cov, 4), 'covered': covered,
            'missed': [f['fact_id'] for f in silver_facts if f['fact_id'] not in covered]}
