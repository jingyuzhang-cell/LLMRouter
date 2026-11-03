"""Phase V2.3-A / S2 grader (SILVER-BASED QUALIFICATION ONLY).

This is NOT terminal_quality and never produces Q. It compares SINK answers to
the task's Silver facts using the frozen scorer's own value-equality semantics
plus the approved V2.3 canonicalization candidate. Gold-frozen tasks are also
reported against their frozen contract as a cross-check.
"""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
sys.path.insert(0, '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4')
import scorer_v23_candidate as C
import terminal_quality as TQ

OK = ('CORRECT', 'CORRECT_CANON', 'CORRECT_AMOUNT')

import re as _re
from decimal import Decimal as _D, InvalidOperation as _IE

_UNITS = {'元': _D(1), '万元': _D(10000), '亿元': _D(100000000),
          '万': _D(10000), '亿': _D(100000000)}


def _amount(v):
    """Parse '<number><unit?>' (commas allowed) into (Decimal, unit)."""
    t = str(v if v is not None else '').replace('，', ',').replace(' ', '').replace('\u3000', '')
    m = _re.match(r'^(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(亿元|万元|元|亿|万|%)?$', t)
    if not m:
        return None
    try:
        num = _D(m.group(1).replace(',', ''))
    except _IE:
        return None
    return num, (m.group(2) or '')


def _amount_equal(got, gold):
    """Unit-aware numeric equality for amount/percent slots (S2 qualification only)."""
    a, b = _amount(got), _amount(gold)
    if not a or not b:
        return False
    ua, ub = a[1], b[1]
    if (ua == '%') != (ub == '%'):
        return False
    if ua == '%' or ub == '%':
        av, bv = a[0], b[0]
    else:
        # a missing unit inherits the gold unit (slot descriptions declare it)
        av = a[0] * _UNITS.get(ua, _D(1)) if ua in _UNITS else a[0]
        bv = b[0] * _UNITS.get(ub, _D(1)) if ub in _UNITS else b[0]
        if not ua and ub:
            av = a[0] * _UNITS[ub]
        if not ub and ua:
            bv = b[0] * _UNITS[ua]
    try:
        diff = abs(av - bv)
        scale = max(abs(bv), _D(1))
        return diff <= _D('1e-9') * scale + _D('1e-6')
    except ArithmeticError:
        return False


def grade(sink, contract, target_slots):
    facts = {f['fact_id']: f for f in contract.get('required_facts', [])}
    answers = {}
    for a in (sink or {}).get('answers', []) if isinstance(sink, dict) else []:
        if isinstance(a, dict) and a.get('fact_id'):
            answers.setdefault(a['fact_id'], a)
    out = {}
    for fid in target_slots:
        f = facts.get(fid)
        a = answers.get(fid)
        if f is None:
            out[fid] = dict(status='NO_FACT'); continue
        if not a or a.get('value') in (None, ''):
            out[fid] = dict(status='ABSENT'); continue
        probe = {'value': a.get('value'), 'value_kind': f.get('value_kind')}
        if TQ._value_equal(probe, f):
            status = 'CORRECT'
        else:
            canon = C._canon(fid, a.get('value'), f.get('value'))
            if canon is not None and TQ._value_equal({'value': canon, 'value_kind': f.get('value_kind')}, f):
                status = 'CORRECT_CANON'
            elif _amount_equal(a.get('value'), f.get('value')):
                status = 'CORRECT_AMOUNT'
            else:
                status = 'WRONG'
        # evidence support (diagnostic only)
        cite = {'doc_id': a.get('doc'), 'page': a.get('page'), 'quote': a.get('quote', '')}
        try:
            ev_ok = bool(TQ._citations_support_fact([cite], f, contract.get('source_pages', {})))
        except Exception:
            ev_ok = False
        out[fid] = dict(status=status, value=str(a.get('value'))[:80],
                        correct=status in OK, evidence_ok=ev_ok)
    return out
