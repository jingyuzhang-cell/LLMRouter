"""Node-output semantic consistency detectors, version 3. V2 (detectors_v2.py) is frozen and kept.

Only change from V2: slots whose predicate starts with 是否 are typed 'polar' and checked by polarity instead
of being assumed to be denials. Polarity is read for the slot's own verb, the two characters after 是否 in the
predicate (是否触及… -> 触及), so other verbs in the sentence (公司涉及的违法行为) do not count.
  M1  a polar slot's candidate row is a table row that names the predicate and states either polarity
  M3  a polar answer is consistent when its polarity equals the polarity of its quote; inconsistent when both
      are determinate and differ; UNDETERMINED when either polarity cannot be read (for example a quote that
      denies one clause and affirms another)
Everything else delegates to V2 unchanged. The base total is a separate module (base_total_v2.py) and enters
as an argument. Gold is never read.
"""
import hashlib
import re
from pathlib import Path

import detectors_v2 as V2

VERSION = 'v3'
V2_SHA256 = 'c2c3384265b39aee6783eff407402c4c775d7eb0b18aea005442f80ec1548c24'

NEGATORS = '(?:未|不|没有|并未|尚未|无)'
DENY_ANSWER = re.compile(r'^(否|不是|没有|未)|未触及|不触及|没有触及|未触发|不触发|不构成|未构成|不涉及|未涉及|不属于')
AFFIRM_ANSWER = re.compile(r'^(是|已|确已)|已触及|^触及|^构成|^属于')


def verify_v2():
    actual = hashlib.sha256(Path(V2.__file__).read_bytes()).hexdigest()
    if actual != V2_SHA256:
        raise RuntimeError(f'detectors_v2 drifted: {actual[:16]}')


def slot_type(slot):
    if V2.norm(slot.get('predicate')).startswith('是否'):
        return 'polar'
    return V2.slot_type(slot)


def slot_verb(slot):
    return V2.norm(slot.get('predicate'))[2:4]


def quote_polarity(quote, verb):
    q = V2.norm(quote)
    affirm = q.count(verb) if verb else 0
    deny = len(re.findall(NEGATORS + re.escape(verb), q)) if verb else 0
    if affirm == 0:
        return 'UNKNOWN'
    if deny == 0:
        return 'AFFIRM'
    if deny == affirm:
        return 'DENY'
    return 'UNKNOWN'


def answer_polarity(value):
    if value is True:
        return 'AFFIRM'
    if value is False:
        return 'DENY'
    v = V2.norm(value)
    deny, affirm = bool(DENY_ANSWER.search(v)), bool(AFFIRM_ANSWER.search(v))
    if deny and not affirm:
        return 'DENY'
    if affirm and not deny:
        return 'AFFIRM'
    return 'UNKNOWN'


def _polar_candidates(slot, rows):
    pred = V2.norm(slot.get('predicate'))[2:]
    keys = V2._chunks(pred)
    verb = slot_verb(slot)
    return [r for r in rows if quote_polarity(r['quote'], verb) != 'UNKNOWN' and any(k in V2.norm(r['quote']) for k in keys)]


def detect_m1(slots, j2_obj, rows):
    out = V2.detect_m1([s for s in slots if slot_type(s) != 'polar'], j2_obj, rows)
    st = V2.j2_statuses(j2_obj)
    for slot in slots:
        if slot_type(slot) != 'polar':
            continue
        fid = slot['fact_id']
        cands = _polar_candidates(slot, rows)
        status = st.get(fid)
        if not cands:
            state = 'NONE'
        elif status is None:
            state = 'OMISSION'
        elif status in V2.SUPPRESSION_STATUSES:
            state = 'EXPLICIT_SUPPRESSION'
        else:
            state = 'NONE'
        out[fid] = dict(state=state, j2_status=status, candidates=len(cands), candidate_rows=[r['row'] for r in cands])
    return {s['fact_id']: out[s['fact_id']] for s in slots}


def detect_m2(slots, j2_obj, base):
    return V2.detect_m2(slots, j2_obj, base)


def detect_m3(slots, sink_obj, rows, base):
    by_slot = {s['fact_id']: s for s in slots}
    out = V2.detect_m3([s for s in slots if slot_type(s) != 'polar'], sink_obj, rows, base)
    table = {(r['doc'], V2.norm(r['quote'])) for r in rows}
    for a in (sink_obj or {}).get('answers') or []:
        if not isinstance(a, dict) or a.get('fact_id') not in by_slot or slot_type(by_slot[a['fact_id']]) != 'polar':
            continue
        value = a.get('value')
        if value is None or V2.norm(value) in ('', 'null', 'unknown', '未知', '未载明'):
            continue
        in_table = (str(a.get('doc')), V2.norm(a.get('quote'))) in table
        ap, qp = answer_polarity(value), quote_polarity(a.get('quote'), slot_verb(by_slot[a['fact_id']]))
        if not in_table:
            state, reason = 'SELF_EVIDENCE_INCONSISTENT', 'quote not in evidence table'
        elif ap == 'UNKNOWN' or qp == 'UNKNOWN':
            state, reason = 'UNDETERMINED', f'polarity unreadable (answer {ap}, quote {qp})'
        elif ap == qp:
            state, reason = 'CONSISTENT', None
        else:
            state, reason = 'SELF_EVIDENCE_INCONSISTENT', f'answer {ap} but quote {qp}'
        out[a['fact_id']] = dict(state=state, kind='polar', reason=reason, answer_polarity=ap, quote_polarity=qp)
    return out


def detect_all(slots, j2_obj, sink_obj, base, rows):
    verify_v2()
    return dict(version=VERSION, base_total=base, m1=detect_m1(slots, j2_obj, rows), m2=detect_m2(slots, j2_obj, base),
                m3=detect_m3(slots, sink_obj, rows, base))
