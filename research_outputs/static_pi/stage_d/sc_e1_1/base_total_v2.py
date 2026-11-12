"""Deterministic penalty total, version 2. Version 1 is detectors_v2.deterministic_total (frozen, kept).

Only change: party names are mapped to a canonical name through aliases the source document itself declares
in the form X（以下简称“A”、“B”）. No similarity matching. Parties that share a canonical name are counted once
when their amounts agree; disagreeing amounts make the total unavailable. The mapping and every addend are
returned with the result. Inclusion rule (unchanged): one amount per distinct party in the final-decision
extraction (E_D2) that carries a numeric penalty_amount.
"""
import re
import unicodedata
from decimal import Decimal

import detectors_v2 as V2

VERSION = 'base_total_v2'
DECLARATION_RE = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9()（）·]{2,60}?)[（(]以下(?:简称|称)([^）)]{1,80})[）)]')
QUOTED_RE = re.compile(r'[“"]([^”"]{1,20})[”"]')
ENTITY_SUFFIX = ('公司', '集团', '有限合伙', '事务所', '银行', '证券')


def norm(x):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str('' if x is None else x)))


def declared_aliases(source_text):
    """alias -> canonical, from explicit 以下简称 declarations whose subject ends in an entity suffix."""
    t = norm(source_text)
    mapping, conflicts = {}, set()
    for subject, body in DECLARATION_RE.findall(t):
        subject = re.sub(r'^.*?(?:[,，;；。:：]|对|与|由|向)', '', subject)
        if not subject.endswith(ENTITY_SUFFIX):
            continue
        for alias in QUOTED_RE.findall(body):
            alias = norm(alias)
            if alias == subject:
                continue
            if alias in mapping and mapping[alias] != subject:
                conflicts.add(alias)
            mapping.setdefault(alias, subject)
    for alias in conflicts:
        mapping.pop(alias, None)
    return mapping, sorted(conflicts)


def total(e_d2_obj, source_text):
    aliases, alias_conflicts = declared_aliases(source_text)
    amounts, members, conflicts = {}, {}, []
    for p in (e_d2_obj or {}).get('parties') or []:
        if not isinstance(p, dict) or p.get('penalty_amount') in (None, ''):
            continue
        name, value = norm(p.get('name')), V2._to_wan(p.get('penalty_amount'))
        if not name or value is None:
            continue
        canonical = aliases.get(name, name)
        members.setdefault(canonical, set()).add(name)
        if canonical in amounts and amounts[canonical] != value:
            conflicts.append(canonical)
        amounts.setdefault(canonical, value)
    detail = dict(rule=V2.TOTAL_RULE + '; names mapped through aliases declared in the source (以下简称)',
                  aliases_declared=aliases, alias_declaration_conflicts=alias_conflicts,
                  merged={c: sorted(m) for c, m in members.items() if len(m) > 1})
    if conflicts or not amounts:
        return dict(value=None, parties=len(amounts), conflicts=sorted(set(conflicts)), **detail)
    s = sum(amounts.values(), Decimal(0))
    return dict(value=f'{s.normalize():f}万元', value_wan=float(s), parties=len(amounts), conflicts=[],
                addends={c: f'{v.normalize():f}' for c, v in amounts.items()}, **detail)
