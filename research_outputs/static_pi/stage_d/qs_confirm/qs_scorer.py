"""Terminal scorer for the Qianshan confirmation task (contract-driven, arm-blind).

Primary Q_all = TP / N. TP = value correct by the slot's rule, cited doc in the slot's whitelist, quote
verbatim in that doc (>= 6 chars, whitespace and PDF page markers ignored), quote grounds the slot
(anchors plus rule-specific value evidence). Whitelists and rules are read from the contract, whose
sha256 is pinned below. score() receives only the parsed SINK object and the contract.

Differences from sc_e1_scorer (written before any call on this task, because the documents need them):
  amount          claims in another unit of the same dimension are converted to the gold unit; a claim
                  in a finer unit (元 against 万元) is compared at the gold's stated precision
  affirmation     a 是否 slot whose source answer is 是
  penalty lines   accept both "万元罚款" and "万元的罚款"
"""
import hashlib
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / 'sc_e1_1')]
import sc_e1_scorer as BASE  # noqa: E402

CONTRACT_PATH = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/QS_300216/TASK_CONTRACT_QS_v1.json')
CONTRACT_SHA256 = '910fa806a833d748580f380c7b45404f241f1075c7ee77c0d32c8281276775d3'
CONTRACT_STATUS = 'GOLD_APPROVED'
WEIGHTS = {'F': 0.5, 'E': 0.3, 'C': 0.2}
MIN_QUOTE_CHARS = 6
UNIT_FACTOR = {'元': Decimal(1), '万元': Decimal(10_000), '亿元': Decimal(100_000_000)}
AMOUNT_RE = re.compile(r'(-?\d[\d,]*(?:\.\d+)?)(%|亿元|万元|元|亿|万)?')
AFFIRM_RE = re.compile(r'^是|已触及|^触及|构成')

norm_text, norm_doc, is_abstention = BASE.norm_text, BASE.norm_doc, BASE.is_abstention


def verify_pins():
    BASE.verify_pins()


def load_contract(path=CONTRACT_PATH):
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != CONTRACT_SHA256:
        raise RuntimeError(f'not the pinned Qianshan contract: {path} is {actual[:16]}')
    return json.loads(raw)


def doc_index(contract):
    return {d: norm_doc(v['pages']['1']['text']) for d, v in contract['source_pages'].items()}


def _unit(u):
    return {'亿': '亿元', '万': '万元'}.get(u, u)


def amounts_in(text):
    """Distinct (Decimal, unit or None) pairs in normalized text."""
    out = []
    for num, unit in AMOUNT_RE.findall(norm_text(text)):
        try:
            out.append((Decimal(num.replace(',', '')), _unit(unit) or None))
        except InvalidOperation:
            pass
    return out


def _same_amount(number, unit, gold, gold_unit):
    if unit == gold_unit:
        return number == gold
    if unit == '%' or gold_unit == '%' or unit not in UNIT_FACTOR or gold_unit not in UNIT_FACTOR:
        return False
    converted = number * UNIT_FACTOR[unit] / UNIT_FACTOR[gold_unit]
    if converted == gold:
        return True
    finer = UNIT_FACTOR[unit] < UNIT_FACTOR[gold_unit]
    return finer and converted.quantize(gold, rounding=ROUND_HALF_UP) == gold


def _amount_value_correct(fact, value):
    if isinstance(value, bool):
        return False
    gold, gold_unit = Decimal(str(fact['value'])), fact.get('unit')
    if isinstance(value, (int, float)):
        return Decimal(str(value)) == gold
    found = set(amounts_in(value))
    if len(found) != 1:
        return False
    number, unit = found.pop()
    return _same_amount(number, unit or gold_unit, gold, gold_unit)


def _titles_ok(text, fact):
    required = fact['grounding'].get('required_titles') or norm_text(fact['value']).split('、')
    return BASE._has_titles(norm_text(text), dict(fact, value='、'.join(required)))


def _affirms(value):
    if value is True:
        return True
    if value is False:
        return False
    t = norm_text(value)
    return not BASE._DENIAL_RE.search(t) and not t.startswith('否') and bool(AFFIRM_RE.search(t))


def value_correct(fact, value):
    rule = fact['grounding']['rule']
    if rule == 'doc_number':
        return set(BASE._DOC_NUMBER_RE.findall(norm_text(value))) == set(BASE._DOC_NUMBER_RE.findall(norm_text(fact['value'])))
    if rule == 'title_set':
        return not isinstance(value, bool) and _titles_ok(value, fact)
    if rule == 'affirmation':
        return _affirms(value)
    if rule == 'negation':
        return BASE._denies(value)
    if rule == 'date':
        return not isinstance(value, bool) and BASE.V2.value_equal_v2({'value': BASE._claim_date(value)}, fact)
    return _amount_value_correct(fact, value)


def quote_grounds(fact, quote):
    g = fact['grounding']
    text = norm_text(quote)
    for anchor in (g.get('subject_anchor'), g.get('predicate_anchor')):
        if anchor and norm_text(anchor) not in text:
            return False
    rule = g['rule']
    if rule == 'doc_number':
        gold = set(BASE._DOC_NUMBER_RE.findall(norm_text(fact['value'])))
        return gold <= set(BASE._DOC_NUMBER_RE.findall(text))
    if rule == 'title_set':
        return _titles_ok(text, fact)
    if rule == 'affirmation':
        return '触及' in text and not BASE._DENIAL_RE.search(text)
    if rule == 'negation':
        return bool(BASE._DENIAL_RE.search(text))
    if rule == 'penalty_line_sum':
        return bool(re.search(r'\d万元的?罚款', text))
    if rule == 'date':
        gold = tuple(int(x) for x in str(fact['value']).split('-'))
        return gold in {tuple(int(x) for x in m) for m in re.findall(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)}
    gold, gold_unit = Decimal(str(fact['value'])), fact.get('unit')
    return any(u and _same_amount(n, u, gold, gold_unit) for n, u in amounts_in(text))


def _row_status(fact, answer, docs):
    doc = str(answer.get('doc') or '').strip()
    quote = norm_text(answer.get('quote'))
    verbatim = doc in docs and len(quote) >= MIN_QUOTE_CHARS and quote in docs[doc]
    if not value_correct(fact, answer.get('value')):
        return 'VALUE_WRONG', False
    if not verbatim or doc not in fact['allowed_citation_docs']:
        return 'LOC_WRONG', verbatim
    if not quote_grounds(fact, answer.get('quote')):
        return 'UNSUPPORTED', verbatim
    return 'TP', verbatim


def score(sink, contract):
    """Score one parsed SINK object; every slot gets a status and the result is never NULL."""
    facts = contract['required_facts']
    gold_ids = {f['fact_id'] for f in facts}
    docs = doc_index(contract)
    sink = sink if isinstance(sink, dict) else {}
    answers = sink.get('answers') if isinstance(sink.get('answers'), list) else []
    unknown = sink.get('unknown_slots') if isinstance(sink.get('unknown_slots'), list) else []
    unknown = {str(u) for u in unknown}

    grouped, abstained, out_of_contract, malformed = {}, set(), [], 0
    for a in answers:
        if not isinstance(a, dict):
            malformed += 1
            continue
        fid = a.get('fact_id')
        if fid not in gold_ids:
            out_of_contract.append(str(fid))
        elif is_abstention(a.get('value')):
            abstained.add(fid)
        else:
            grouped.setdefault(fid, []).append(a)

    rows = []
    for f in facts:
        fid = f['fact_id']
        rec = {'fact_id': fid, 'critical': bool(f.get('critical'))}
        given = grouped.get(fid)
        if not given:
            rec.update(status='ABSENT', declared_unknown=fid in unknown or fid in abstained,
                       value_correct=False, literal_cite=False)
            rows.append(rec)
            continue
        if len({norm_text(a.get('value')) for a in given}) > 1:
            status, verbatim = 'CONFLICT', False
        else:
            status, verbatim = _row_status(f, given[0], docs)
        rec.update(status=status, value=given[0].get('value'), doc=given[0].get('doc'), quote=given[0].get('quote'),
                   value_correct=status in ('TP', 'LOC_WRONG', 'UNSUPPORTED'),
                   literal_cite=status in ('TP', 'LOC_WRONG', 'UNSUPPORTED') and verbatim,
                   answered_and_unknown=fid in unknown)
        rows.append(rec)

    n = len(facts)
    asserted = sum(r['status'] != 'ABSENT' for r in rows)
    correct = sum(r['value_correct'] for r in rows)
    tp = sum(r['status'] == 'TP' for r in rows)
    literal = sum(r['literal_cite'] for r in rows)
    wrong = sum(r['status'] in ('VALUE_WRONG', 'CONFLICT') for r in rows)
    critical = [r for r in rows if r['critical']]
    critical_tp = sum(r['status'] == 'TP' for r in critical)
    F = correct / asserted if asserted else 0.0
    E = tp / asserted if asserted else 0.0
    C = asserted / n
    return {
        'Q_all': round(tp / n, 6),
        'Q_terminal': round(WEIGHTS['F'] * F + WEIGHTS['E'] * E + WEIGHTS['C'] * C, 6),
        'F': round(F, 6), 'E': round(E, 6), 'C': round(C, 6),
        'E_literal': round(literal / asserted, 6) if asserted else 0.0,
        'asserted': asserted, 'correct': correct, 'tp': tp, 'wrong': wrong, 'total': n,
        'critical_tp': critical_tp, 'critical_total': len(critical),
        'critical_gate': 'PASS' if critical_tp == len(critical) else 'FAIL',
        'out_of_contract': out_of_contract, 'malformed_answers': malformed, 'zero_assertions': asserted == 0,
        'rows': rows,
    }
