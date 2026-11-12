"""Node-output semantic consistency detectors, version 2 (frozen; V1 results kept in MECHANISM_DETECTION_OFFLINE.json).

Every check reads only node outputs, the verified evidence table and the slot schema shared with the
models (fact_id, subject, predicate, unit). Gold values are never read.

  M1  cross-node evidence inconsistency: J2 rejects or omits a slot that the evidence table can support
        EXPLICIT_SUPPRESSION  J2 states the slot cannot be verified
        OMISSION              J2 does not mention the slot
  M2  derived-result inconsistency: a model-stated total differs from the deterministic base module
      (the base module supplies the value; M2 is reported, never offered to the scheduler)
  M3  output-versus-own-evidence inconsistency in a SINK answer, checked by slot type

V2 was written after seeing the development failures and is scored on the same development data, so
its development numbers are not accuracy estimates.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

VERSION = 'v2'
SUPPRESSION_STATUSES = {'unverifiable', 'unverified', 'not_verifiable', 'cannot_verify', 'insufficient_evidence',
                        '无法核验', '不可核验', '无法验证', '证据不足', '未核实'}
DENIAL_RE = re.compile(r'未触及|不触及|没有触及|未触发|不触发|不构成|未构成|不涉及|未涉及')
DOC_NUMBER_RE = re.compile(r'[【\[〔(（](\d{4})[】\]〕)）](\d+)号')
DATE_RE = re.compile(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})')
AMOUNT_RE = re.compile(r'(\d[\d,，.]*)\s*(亿元|万元|元|亿|万)?')
TITLE_WORDS = ('董事长', '总裁', '总经理', '经理', '董事', '监事', '总监', '秘书', '负责人')
UNIT_TO_WAN = {'亿元': Decimal(10000), '亿': Decimal(10000), '万元': Decimal(1), '万': Decimal(1), '元': Decimal('0.0001')}
# Frozen inclusion rule of the base module: one amount per party named in the final decision (E_D2).
TOTAL_RULE = 'sum over distinct parties extracted from the final decision (E_D2) that carry a numeric penalty_amount'


def norm(x):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str('' if x is None else x)))


def slot_type(slot):
    """Typed from the slot schema the models already see; no Gold metadata."""
    pred = norm(slot.get('predicate'))
    if '合计' in pred or '总计' in pred:
        return 'derived'
    if pred.startswith('是否'):
        return 'negation'
    if '文号' in pred:
        return 'doc_number'
    if pred.endswith('日期') or pred.endswith('日'):
        return 'date'
    if pred in ('职务', '职位', '任职'):
        return 'title'
    if slot.get('unit'):
        return 'amount'
    return 'text'


def _chunks(text, n=4, drop=('收到日期', '罚款金额', '处罚罚款', '行政处罚')):
    t = norm(text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))} - set(drop)


def candidate_rows(slot, rows):
    """Evidence-table rows that could support the slot, by type."""
    kind = slot_type(slot)
    subject, pred = norm(slot.get('subject')), norm(slot.get('predicate'))
    out = []
    for r in rows:
        q = norm(r['quote'])
        if kind == 'doc_number':
            ok = bool(DOC_NUMBER_RE.search(q)) and any(c in q for c in _chunks(subject, 4) | {subject})
        elif kind == 'date':
            ok = bool(DATE_RE.search(q)) and any(c in q for c in _chunks(pred.replace('日期', '').replace('收到', ''), 3))
        elif kind == 'negation':
            ok = bool(DENIAL_RE.search(q)) and any(c in q for c in _chunks(pred[2:]))
        elif kind == 'title':
            ok = subject in q and any(w in q for w in TITLE_WORDS)
        elif kind == 'amount':
            keys = _chunks(pred) | ({subject} if 1 < len(subject) <= 4 else set())
            ok = bool(re.search(r'\d', q)) and any(k in q for k in keys)
        else:
            ok = False
        if ok:
            out.append(r)
    return out


def j2_statuses(j2_obj):
    st = {}
    for v in (j2_obj or {}).get('verified') or []:
        if isinstance(v, dict) and v.get('fact_id'):
            st[str(v['fact_id'])] = norm(v.get('status')).lower()
    for d in (j2_obj or {}).get('derived') or []:
        if isinstance(d, dict) and d.get('fact_id'):
            st.setdefault(str(d['fact_id']), 'derived')
    return st


def detect_m1(slots, j2_obj, rows):
    st = j2_statuses(j2_obj)
    out = {}
    for slot in slots:
        fid = slot['fact_id']
        if slot_type(slot) == 'derived':
            out[fid] = dict(state='NOT_APPLICABLE', j2_status=st.get(fid), candidates=0)
            continue
        cands = candidate_rows(slot, rows)
        status = st.get(fid)
        if not cands:
            state = 'NONE'
        elif status is None:
            state = 'OMISSION'
        elif status in SUPPRESSION_STATUSES:
            state = 'EXPLICIT_SUPPRESSION'
        else:
            state = 'NONE'
        out[fid] = dict(state=state, j2_status=status, candidates=len(cands), candidate_rows=[r['row'] for r in cands])
    return out


def _to_wan(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    m = AMOUNT_RE.search(norm(value))
    if not m:
        return None
    try:
        n = Decimal(m.group(1).replace(',', '').replace('，', ''))
    except InvalidOperation:
        return None
    return n * UNIT_TO_WAN.get(m.group(2) or '万元', Decimal(1))


def deterministic_total(e_d2_obj):
    """Base module (M2). Bare numbers are read in 万元, the unit of the penalty slots."""
    amounts, conflicts = {}, []
    for p in (e_d2_obj or {}).get('parties') or []:
        if not isinstance(p, dict) or p.get('penalty_amount') in (None, ''):
            continue
        name, v = norm(p.get('name')), _to_wan(p.get('penalty_amount'))
        if not name or v is None:
            continue
        if name in amounts and amounts[name] != v:
            conflicts.append(name)
        amounts.setdefault(name, v)
    if conflicts or not amounts:
        return dict(value=None, parties=len(amounts), conflicts=conflicts, rule=TOTAL_RULE)
    total = sum(amounts.values())
    text = f"{total.normalize():f}万元"
    return dict(value=text, value_wan=float(total), parties=len(amounts), conflicts=[], rule=TOTAL_RULE,
                computation=' + '.join(f'{n}:{v.normalize():f}' for n, v in amounts.items()))


def detect_m2(slots, j2_obj, base):
    out = {}
    stated = {}
    for d in (j2_obj or {}).get('derived') or []:
        if isinstance(d, dict) and d.get('fact_id'):
            stated[str(d['fact_id'])] = d.get('value')
    for slot in slots:
        if slot_type(slot) != 'derived':
            continue
        fid = slot['fact_id']
        v = _to_wan(stated.get(fid)) if stated.get(fid) is not None else None
        if base.get('value') is None:
            state = 'BASE_UNAVAILABLE'
        elif v is None:
            state = 'NOT_STATED'
        else:
            state = 'CONSISTENT' if abs(float(v) - base['value_wan']) < 1e-6 else 'DERIVED_MISMATCH'
        out[fid] = dict(state=state, stated=stated.get(fid), base=base.get('value'))
    return out


def _value_in_quote(kind, value, quote):
    q, v = norm(quote), norm(value)
    if kind == 'date':
        dv, dq = DATE_RE.search(v), {tuple(int(x) for x in m) for m in DATE_RE.findall(q)}
        return bool(dv) and tuple(int(x) for x in dv.groups()) in dq
    if kind == 'doc_number':
        tv = set(DOC_NUMBER_RE.findall(v))
        return bool(tv) and tv <= set(DOC_NUMBER_RE.findall(q))
    if kind == 'title':
        titles = [w for w in TITLE_WORDS if w in v.replace('副', '')]
        return bool(titles) and all(t in q.replace('副' + t, '') for t in titles)
    nums = re.findall(r'\d[\d,，.]*', v)
    if nums:
        qq = q.replace(',', '').replace('，', '')
        return all(n.replace(',', '').replace('，', '').rstrip('.') in qq for n in nums)
    core = v[:12]
    return bool(core) and core in q


def _denies(value):
    if value is False:
        return True
    t = norm(value)
    return bool(DENIAL_RE.search(t)) or t.startswith('否') or t.endswith('否')


def detect_m3(slots, sink_obj, rows, base):
    by_slot = {s['fact_id']: s for s in slots}
    table = {(r['doc'], norm(r['quote'])) for r in rows}
    out = {}
    for a in (sink_obj or {}).get('answers') or []:
        if not isinstance(a, dict) or a.get('fact_id') not in by_slot:
            continue
        fid, value = a['fact_id'], a.get('value')
        if value is None or norm(value) in ('', 'null', 'unknown', '未知', '未载明'):
            continue
        kind = slot_type(by_slot[fid])
        in_table = (str(a.get('doc')), norm(a.get('quote'))) in table
        if kind == 'derived':
            ok = base.get('value') is not None and _to_wan(value) is not None and abs(float(_to_wan(value)) - base['value_wan']) < 1e-6
            reason = None if ok else 'derived value differs from base module'
        elif kind == 'negation':
            ok = in_table and _denies(value) and bool(DENIAL_RE.search(norm(a.get('quote'))))
            reason = None if ok else 'negation not supported by a table quote with a denial phrase'
        else:
            readable = _value_in_quote(kind, value, a.get('quote'))
            ok = in_table and readable
            reason = None if ok else ('quote not in evidence table' if not in_table else 'value not readable in its quote')
        out[fid] = dict(state='CONSISTENT' if ok else 'SELF_EVIDENCE_INCONSISTENT', kind=kind, reason=reason)
    return out


def detect_all(slots, j2_obj, sink_obj, e_d2_obj, rows):
    base = deterministic_total(e_d2_obj)
    return dict(version=VERSION, base_total=base, m1=detect_m1(slots, j2_obj, rows),
                m2=detect_m2(slots, j2_obj, base), m3=detect_m3(slots, sink_obj, rows, base))
