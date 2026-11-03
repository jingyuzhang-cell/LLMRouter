"""Scoring v2 — field-structured deterministic T1 fact matching (2026-10-14).

v1 rule (anchor_quote OR normalized_value substring) has two known defects:
  false positives: a short value like '60万元' can match unrelated amounts;
  false negatives: paraphrase/reordered phrasing ('处以60万元罚款' vs anchor
  '60万元罚款') misses semantically correct statements.

v2 rules are derived ONLY from the reference facts' OWN FIELDS (entity, amount,
relation, time-range, institution) — one deterministic rule per fact, identical
for all strategies, no post-hoc selection. Facts whose correctness cannot be
objectively string-verified stay UNRESOLVED (none of RF1-RF4 need it today, but
the framework requires the verdict).

Versioning: v1 results stay archived untouched; v2 is a NEW protocol version
applied uniformly. Old and new scores are reported side by side, never replaced.
"""
import re

from pilot_common import norm

# each rule: required field conditions on the NORMALISED report text.
# all=True means every condition must hold (AND); regex where order matters.
RULES_V2 = {
    'RF1': {'desc': '康得新被罚款60万元',
            'all': ['60万元', '罚款'], 'entity_context': ['康得新'],
            'note': 'amount+relation+subject'},
    'RF2': {'desc': '2015-2018年报存在虚假记载',
            'regex': [r'2015[^0-9]{1,12}2018'],
            'any_of': [['年报', '年度报告']], 'all': ['虚假记载'],
            'note': 'time-range + (年报|年度报告) + violation'},
    'RF3': {'desc': '10年证券市场禁入',
            'regex': [r'10年[^。；]{0,20}?(证券)?市场禁入|市场禁入[^。；]{0,20}?10年'],
            'note': 'duration+measure, order-flexible within a clause'},
    'RF4': {'desc': '北京银行西单支行现金管理业务合作协议',
            'all': ['北京银行', '西单支行', '现金管理'],
            'note': 'multi-institution AND-match'},
}
UNRESOLVED_FACTS = []  # facts lacking an objectively verifiable string rule


def score_fact(fid, report_text):
    rule = RULES_V2.get(fid)
    if rule is None or fid in UNRESOLVED_FACTS:
        return 'UNRESOLVED'
    hay = norm(report_text)
    for sub in rule.get('all', []):
        if norm(sub) not in hay:
            return 'NOT_COVERED'
    for group in rule.get('any_of', []):
        if not any(norm(opt) in hay for opt in group):
            return 'NOT_COVERED'
    for pat in rule.get('regex', []):
        if not re.search(pat, hay):
            return 'NOT_COVERED'
    for ent in rule.get('entity_context', []):
        if norm(ent) not in hay:
            return 'NOT_COVERED'
    return 'COVERED'


def score_report(report_text, fact_ids=('RF1', 'RF2', 'RF3', 'RF4')):
    per = {fid: score_fact(fid, report_text) for fid in fact_ids}
    covered = [f for f, v in per.items() if v == 'COVERED']
    return {'per_fact': per, 'covered': covered,
            'score': f'{len(covered)}/{len(fact_ids)}',
            'unresolved': [f for f, v in per.items() if v == 'UNRESOLVED']}


def chain_filter(covered, pack_text):
    """Evidence-chain: a fact counts as chain-valid only if the PACK could
    support it — the fact's OWN rule (all/any_of/regex) must match the pack.
    Regex-only rules are tested with their actual regex (a desc-prefix fallback
    would over-claim reachability: RF3 measured 0 clause-level matches in the
    10K pack despite a desc-prefix false positive)."""
    hay = norm(pack_text)
    out = []
    for fid in covered:
        rule = RULES_V2[fid]
        if not all(norm(c) in hay for c in rule.get('all', [])):
            continue
        if not all(any(norm(o) in hay for o in g) for g in rule.get('any_of', [])):
            continue
        if not all(re.search(pat, hay) for pat in rule.get('regex', [])):
            continue
        if not all(norm(e) in hay for e in rule.get('entity_context', [])):
            continue
        out.append(fid)
    return out
