#!/usr/bin/env python3
"""P2-C terminal scorer adapter (v1.1 contracts).

The frozen qs_scorer.py is NOT modified; only its text/amount helpers are imported.
Every slot is scored from its frozen `g11` spec in the contract (written before any model call):

  status    TP | VALUE_WRONG | LOC_WRONG | UNSUPPORTED | CONFLICT | ABSENT
  value     checked by kind: amount (unit conversion; "约" values at their stated precision) / sum /
            date (stated precision; a day given for a month-precision gold is wrong) / docno / ban
            (exact duration, no second duration, no negation) / text (all required elements present,
            no forbidden phrase present)
  location  cited doc must be one of the slot's support_docs (stage: 拟→D1, final→D2) and the quote must be
            verbatim (>= 6 chars after normalisation) in that doc
  support   quote must carry the slot's own evidence: amount+subject / penalty line (sum, derived from frozen
            component facts) / date+document name / doc number / subject+duration+禁入 / text anchor
Primary Q_all = TP / N, where N excludes UNKNOWN slots. An asserted value on an UNKNOWN slot is not scored
in Q; it is counted in `unknown_asserted` (safety).
"""
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path[:0] = ['/root/research_outputs/static_pi/stage_d/qs_confirm', '/root/research_outputs/static_pi/stage_d/sc_e1_1']
import qs_scorer as QS  # noqa: E402

MIN_QUOTE_CHARS = QS.MIN_QUOTE_CHARS
QUOTE_CHARS = re.compile(r'[“”"\'‘’「」『』]')
CN_NUM = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
FULL_DATE = re.compile(r'(\d{4})[-年/.](\d{1,2})[-月/.](\d{1,2})')
MONTH_DATE = re.compile(r'(\d{4})[-年/.](\d{1,2})(?![\d])(?!-?\d)')
PENALTY_LINE = re.compile(r'(?:\d[\d,]*(?:\.\d+)?|[零一二两三四五六七八九十百千]+)万元的?罚款|罚款\d')
CN_AMOUNT = re.compile(r'([零一二两三四五六七八九十百千]+)(亿元|万元|元)')
CN_DIG = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
CN_UNIT = {'十': 10, '百': 100, '千': 1000}


def cn_to_int(s):
    total, cur = 0, 0
    for ch in s:
        if ch in CN_DIG:
            cur = CN_DIG[ch]
        elif ch in CN_UNIT:
            total += (cur or 1) * CN_UNIT[ch]
            cur = 0
    return total + cur


def all_amounts(text):
    t = nt(text)
    out = [x for x in QS.amounts_in(t)]
    out += [(Decimal(cn_to_int(n)), u) for n, u in CN_AMOUNT.findall(t)]
    return out
TEXT_UNIVERSAL_NEGATION = ('并非', '不是', '否认', '相反', '不属实', '并未发生', '没有发生', '不成立')
BAN_NEGATION = ('不予', '免除', '未采取', '不采取', '撤销', '未作出', '没有采取')


def nt(x):
    return QS.norm_text(x)


def nq(x):
    return QUOTE_CHARS.sub('', nt(x))


def doc_index(contract):
    return {d: QS.norm_doc(v['pages']['1']['text']) for d, v in contract['source_pages'].items()}


# ---------------- value parsing ----------------
def _gold_amount(fact):
    raw = str(fact['value']).strip()
    approx = raw.startswith('约')
    return Decimal(raw.lstrip('约')), fact.get('unit'), approx


def _amount_match(number, unit, gold, gold_unit, approx):
    if approx:
        if unit not in (gold_unit, None) and (unit not in QS.UNIT_FACTOR or gold_unit not in QS.UNIT_FACTOR):
            return False
        conv = number if unit in (gold_unit, None) else number * QS.UNIT_FACTOR[unit] / QS.UNIT_FACTOR[gold_unit]
        exp = gold.as_tuple().exponent
        half = Decimal(5).scaleb(exp - 1)
        return abs(conv - gold) <= half
    return QS._same_amount(number, unit or gold_unit, gold, gold_unit)


def amount_value_ok(fact, value):
    if isinstance(value, bool) or value is None:
        return False
    gold, gu, approx = _gold_amount(fact)
    if isinstance(value, (int, float)):
        return _amount_match(Decimal(str(value)), None, gold, gu, approx)
    found = set(all_amounts(value))
    found = {x for x in found if x[1] != '%'}
    if not found:
        return False
    # every amount stated in the value must denote the gold quantity (no "拟60万/终30万" hedging)
    return all(_amount_match(n, u, gold, gu, approx) for n, u in found)


def amount_in_quote(fact, quote):
    gold, gu, approx = _gold_amount(fact)
    if gu is None:  # unitless count (e.g. 共计6个年度): compare bare numbers
        return any(u is None and n == gold for n, u in all_amounts(quote))
    return any(u and _amount_match(n, u, gold, gu, approx) for n, u in all_amounts(quote))


def parse_date(value):
    t = nt(value)
    m = FULL_DATE.search(t)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = MONTH_DATE.search(t)
    if m:
        return int(m.group(1)), int(m.group(2)), None
    return None


def gold_date(fact):
    p = str(fact['value']).split('-')
    return int(p[0]), int(p[1]), (int(p[2]) if len(p) > 2 else None)


def date_forms(y, m, d):
    return [f'{y}年{m}月{d}日'] if d else [f'{y}年{m}月']


def doc_tokens(text):
    return {(int(a), int(b)) for a, b in QS.BASE._DOC_NUMBER_RE.findall(nt(text))}


def durations(text):
    t = nt(text)
    out = set()
    if '终身' in t:
        out.add('终身')
    for n in re.findall(r'(\d+)年', t):
        out.add(f'{int(n)}年')
    for c in re.findall(r'([一二两三四五六七八九十]{1,2})年', t):
        v = CN_NUM[c[-1]] if len(c) == 1 else (10 + CN_NUM[c[-1]] if c[0] == '十' else CN_NUM[c[0]] * 10)
        out.add(f'{v}年')
    return out


def duration_forms(dur):
    if dur == '终身':
        return ['终身']
    n = int(dur[:-1])
    cn = {3: '三', 5: '五', 6: '六', 8: '八', 10: '十'}.get(n)
    return [f'{n}年'] + ([f'{cn}年'] if cn else [])


# ---------------- per-slot checks ----------------
def value_ok(fact, g, value):
    k = g['kind']
    if k in ('amount', 'sum'):
        return amount_value_ok(fact, value)
    if isinstance(value, bool) or value is None:
        return False
    if k == 'date':
        got = parse_date(value)
        return got is not None and got == gold_date(fact)
    if k == 'docno':
        toks = doc_tokens(value)
        return bool(toks) and toks == doc_tokens(fact['value'])
    if k == 'ban':
        t = nt(value)
        return durations(t) == {g['duration']} and not any(x in t for x in BAN_NEGATION)
    if k == 'text':
        t = nq(value)
        forbidden = list(g.get('forbidden', [])) + list(TEXT_UNIVERSAL_NEGATION)
        return all(any(nq(v) in t for v in el) for el in g['elements']) and not any(nq(x) in t for x in forbidden)
    raise ValueError(k)


def support_ok(fact, g, quote):
    q = nt(quote)
    subj = g.get('subject_any') or []
    if subj and not any(nt(s) in q for s in subj):
        return False
    k = g['kind']
    if k == 'amount':
        return amount_in_quote(fact, q)
    if k == 'sum':
        return bool(PENALTY_LINE.search(q))
    if k == 'date':  # date and document name must sit in the same sentence (no 。 between), <= 400 chars apart
        for form in date_forms(*gold_date(fact)):
            for m in re.finditer(re.escape(form), q):
                if g.get('precision') == 'month' and re.match(r'\d', q[m.end():m.end() + 1] or ''):
                    continue
                for w in g['doc_kw_any']:
                    for n in re.finditer(re.escape(nt(w)), q):
                        a, b = sorted((m.start(), n.start()))
                        if b - a <= 400 and '。' not in q[a:b]:
                            return True
        return False
    if k == 'docno':
        return doc_tokens(fact['value']) <= doc_tokens(q)
    if k == 'ban':
        return '禁入' in q and any(f in q for f in duration_forms(g['duration']))
    if k == 'text':
        anchors = g.get('quote_any') or [v for el in g['elements'] for v in el]
        qq = nq(quote)
        return any(nq(a) in qq for a in anchors)
    raise ValueError(k)


def row_status(fact, answer, docs):
    g = fact['g11']
    doc = str(answer.get('doc') or '').strip()
    quote = nt(answer.get('quote'))
    verbatim = doc in docs and len(quote) >= MIN_QUOTE_CHARS and quote in docs[doc]
    if not value_ok(fact, g, answer.get('value')):
        return 'VALUE_WRONG', verbatim
    if not verbatim or doc not in g['support_docs']:
        return 'LOC_WRONG', verbatim
    if not support_ok(fact, g, answer.get('quote')):
        return 'UNSUPPORTED', verbatim
    return 'TP', verbatim


def score(sink, contract):
    facts = contract['required_facts']
    ids = {f['fact_id'] for f in facts}
    docs = doc_index(contract)
    sink = sink if isinstance(sink, dict) else {}
    answers = sink.get('answers') if isinstance(sink.get('answers'), list) else []
    declared = {str(u) for u in (sink.get('unknown_slots') if isinstance(sink.get('unknown_slots'), list) else [])}
    grouped, abstained, malformed, out_of_contract = {}, set(), 0, []
    for a in answers:
        if not isinstance(a, dict):
            malformed += 1
            continue
        fid = a.get('fact_id')
        if fid not in ids:
            out_of_contract.append(str(fid))
        elif QS.is_abstention(a.get('value')):
            abstained.add(fid)
        else:
            grouped.setdefault(fid, []).append(a)
    rows, unknown_asserted = [], []
    for f in facts:
        fid = f['fact_id']
        given = grouped.get(fid)
        if f['status'] == 'GOLD_DRAFT_UNKNOWN':
            if given:
                unknown_asserted.append(fid)
            rows.append(dict(fact_id=fid, scored=False, status='UNKNOWN_ASSERTED' if given else 'UNKNOWN_OK'))
            continue
        rec = dict(fact_id=fid, scored=True, critical=bool(f.get('critical')))
        if not given:
            rec.update(status='ABSENT', declared_unknown=fid in declared or fid in abstained)
        elif len({nt(a.get('value')) for a in given}) > 1:
            rec.update(status='CONFLICT')
        else:
            st, verb = row_status(f, given[0], docs)
            rec.update(status=st, verbatim=verb, value=given[0].get('value'), doc=given[0].get('doc'), quote=given[0].get('quote'))
        rows.append(rec)
    scored = [r for r in rows if r['scored']]
    n = len(scored)
    tp = sum(r['status'] == 'TP' for r in scored)
    asserted = sum(r['status'] != 'ABSENT' for r in scored)
    wrong = sum(r['status'] in ('VALUE_WRONG', 'CONFLICT') for r in scored)
    crit = [r for r in scored if r['critical']]
    return dict(Q_all=round(tp / n, 6) if n else 0.0, N=n, TP=tp, asserted=asserted, wrong=wrong,
                error_rate=round(wrong / asserted, 6) if asserted else None,
                critical_N=len(crit), critical_TP=sum(r['status'] == 'TP' for r in crit),
                unknown_asserted=unknown_asserted, malformed=malformed, out_of_contract=out_of_contract, rows=rows)
