"""ST (江苏舜天) field-structured scoring rules v2 — same standard as KDX v2.

Field rules derived only from the reference facts' OWN fields (amount/relation/
concept + subject); deterministic; identical for all strategies; UNRESOLVED for
anything not objectively string-verifiable.
"""
import re

from pilot_common import norm

RULES_ST_V2 = {
    'RF5': {'desc': '江苏舜天被罚款1,000万元',
            'any_of': [['1,000万元', '1000万元']],
            'all': ['罚款'], 'entity_context': ['舜天'],
            'note': 'amount(+comma variants)+relation+subject'},
    'RF6': {'desc': '专网通信为虚假自循环业务',
            'all': ['虚假自循环'],
            'note': 'concept phrase (norm keeps contiguity)'},
    'RF7': {'desc': '虚增金额85,340,644.67元',
            'any_of': [['85,340,644.67', '85340644.67', '8,534.06万', '8534.06万']],
            'note': 'exact amount variants'},
}
UNRESOLVED_FACTS = []


def score_fact_st(fid, report_text):
    rule = RULES_ST_V2.get(fid)
    if rule is None or fid in UNRESOLVED_FACTS:
        return 'UNRESOLVED'
    hay = norm(report_text)
    if not all(norm(x) in hay for x in rule.get('all', [])):
        return 'NOT_COVERED'
    if not all(any(norm(o) in hay for o in g) for g in rule.get('any_of', [])):
        return 'NOT_COVERED'
    if not all(norm(e) in hay for e in rule.get('entity_context', [])):
        return 'NOT_COVERED'
    return 'COVERED'


def score_report_st(report_text, fact_ids=('RF5', 'RF6', 'RF7')):
    per = {fid: score_fact_st(fid, report_text) for fid in fact_ids}
    covered = [f for f, v in per.items() if v == 'COVERED']
    return {'per_fact': per, 'covered': covered, 'score': f'{len(covered)}/{len(fact_ids)}'}


def chain_filter_st(covered, pack_text):
    hay = norm(pack_text)
    out = []
    for fid in covered:
        rule = RULES_ST_V2[fid]
        if not all(norm(x) in hay for x in rule.get('all', [])):
            continue
        if not all(any(norm(o) in hay for o in g) for g in rule.get('any_of', [])):
            continue
        if not all(norm(e) in hay for e in rule.get('entity_context', [])):
            continue
        out.append(fid)
    return out
